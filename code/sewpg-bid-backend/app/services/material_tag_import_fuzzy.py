"""技术标标签导入的模糊匹配桥接。

把后端精确匹配剩下的 ``unmatched`` 行 + 候选文件清单组装成 prompt，
调用 opencode ``bid-tech-tag-importer`` skill 做 AI 语义模糊匹配，
再把结果整理成预览用的 ``fuzzy`` 分区。

关键：先用廉价的字符 n-gram 重合度在 Python 侧为每一行预筛出 Top-K 候选，
只把这个短候选清单送进模型 —— 否则把上百个候选全发出去会让模型生成超时。

任何异常都向上抛出，由调用方（``TechnicalMaterialStore._augment_with_fuzzy``）
捕获并降级 —— 模糊匹配是兜底增强，绝不能阻断核心确定性匹配。
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from app.services.material_tags import normalize_material_tags

# 控制送进 prompt 的规模，避免模型生成超时
_MAX_UNMATCHED = 40       # 一次最多处理多少未匹配行
_TOP_K_PER_ROW = 6        # 每行预筛保留的候选数
_MAX_TOTAL_CANDIDATES = 60  # 整个 prompt 里去重后的候选总数上限
# 模糊匹配是预览时的兜底增强，模型（big-pickle）冷启动/排队常 >30s，
# 这里给一个比系统默认（30s）更宽裕的专用超时，避免动不动就超时降级。
_FUZZY_TIMEOUT_MS = 180_000


def _normalize(text: str) -> str:
    # 去掉括号、空格、标点，保留中英文与数字，便于做 n-gram 重合
    return re.sub(r"[\s\(\)（）【】\[\]，,。.\-_/]+", "", str(text or "")).casefold()


def _bigrams(text: str) -> set[str]:
    norm = _normalize(text)
    if len(norm) <= 2:
        return {norm} if norm else set()
    return {norm[i : i + 2] for i in range(len(norm) - 1)}


def _similarity(a: str, b: str) -> float:
    ga, gb = _bigrams(a), _bigrams(b)
    if not ga or not gb:
        return 0.0
    inter = len(ga & gb)
    if not inter:
        return 0.0
    # Jaccard，对包含关系友好
    return inter / len(ga | gb)


def _prefilter_candidates(
    unmatched: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """为每行挑 Top-K 候选，返回 (去重后的候选清单, fileId->候选 映射)。"""

    by_id: dict[str, dict[str, Any]] = {}
    for item in candidates:
        fid = str(item.get("id") or "")
        if fid:
            by_id.setdefault(fid, item)

    selected_ids: list[str] = []
    seen: set[str] = set()
    for row in unmatched:
        name = str(row.get("fileName") or "")
        scored = sorted(
            (
                (_similarity(name, str(item.get("name") or "")), fid)
                for fid, item in by_id.items()
            ),
            key=lambda pair: pair[0],
            reverse=True,
        )
        for score, fid in scored[:_TOP_K_PER_ROW]:
            if score <= 0:
                break
            if fid not in seen:
                seen.add(fid)
                selected_ids.append(fid)
        if len(selected_ids) >= _MAX_TOTAL_CANDIDATES:
            break

    shortlist = [by_id[fid] for fid in selected_ids[:_MAX_TOTAL_CANDIDATES]]
    return shortlist, by_id


def _build_prompt(unmatched: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> str:
    manifest = {
        "unmatched": [
            {
                "rowIndex": row.get("rowIndex"),
                "fileName": row.get("fileName"),
                "levelPath": row.get("levelPath") or [],
                "tags": row.get("tags") or [],
            }
            for row in unmatched
        ],
        "candidates": [
            {
                "fileId": str(item.get("id") or ""),
                "name": str(item.get("name") or ""),
                "folderPath": str(item.get("folderPath") or ""),
            }
            for item in candidates
            if str(item.get("id") or "")
        ],
    }
    manifest_json = json.dumps(manifest, ensure_ascii=False)
    return (
        "请使用 skill `bid-tech-tag-importer` 完成技术标标签导入的模糊匹配。\n"
        "遵守该 skill 的全部铁律：只能从 candidates 里选 fileId，无合理候选返回 null，"
        "宁缺毋滥，只输出 bid-tech-tag-match-v1 JSON，不要任何额外文字。\n"
        "输入 manifest 如下：\n"
        f"{manifest_json}\n"
    )


def _run_sync(unmatched: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # 延迟导入，避免在无 opencode 配置的环境（如纯单测）下加载 httpx/settings 失败
    from app.services.opencode_client import OpencodeClient

    rows = unmatched[:_MAX_UNMATCHED]
    shortlist, by_id = _prefilter_candidates(rows, candidates)
    if not shortlist:
        return []  # 没有任何字符上沾边的候选，直接放弃，省一次模型调用

    prompt = _build_prompt(rows, shortlist)
    result = OpencodeClient(timeout_ms=_FUZZY_TIMEOUT_MS).run_bid_tech_tag_importer_with_trace(prompt)
    matches = result.get("matches") or []

    valid_ids = {str(item.get("id") or "") for item in shortlist}
    by_row = {row.get("rowIndex"): row for row in rows}

    fuzzy: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for match in matches:
        if not isinstance(match, dict):
            continue
        suggested = str(match.get("suggestedFileId") or "")
        if not suggested or suggested not in valid_ids or suggested in used_ids:
            continue  # 铁律：只接受候选清单内的 fileId，且不重复建议
        row = by_row.get(match.get("rowIndex"))
        if row is None:
            continue
        candidate = by_id.get(suggested, {})
        existing = normalize_material_tags(candidate.get("tags"))
        incoming = normalize_material_tags(row.get("tags"))
        merged = normalize_material_tags([*existing, *incoming])
        try:
            confidence = float(match.get("confidence"))
        except (TypeError, ValueError):
            confidence = 0.0
        used_ids.add(suggested)
        fuzzy.append(
            {
                "rowIndex": row.get("rowIndex"),
                "fileName": row.get("fileName"),
                "levelPath": row.get("levelPath") or [],
                "incomingTags": incoming,
                "suggestedFileId": suggested,
                "matchedName": str(candidate.get("name") or ""),
                "folderPath": str(candidate.get("folderPath") or ""),
                "existingTags": existing,
                "mergedTags": merged,
                "addedTags": [tag for tag in merged if tag not in existing],
                "confidence": confidence,
                "reason": str(match.get("reason") or ""),
            }
        )
    # 按置信度从高到低排序，方便人工先看靠谱的建议
    fuzzy.sort(key=lambda entry: entry.get("confidence") or 0.0, reverse=True)
    return fuzzy


async def run_tag_import_fuzzy_match(
    *,
    unmatched: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """异步入口：在线程池里跑同步的 opencode 调用。"""

    if not unmatched or not candidates:
        return []
    return await asyncio.to_thread(_run_sync, unmatched, candidates)
