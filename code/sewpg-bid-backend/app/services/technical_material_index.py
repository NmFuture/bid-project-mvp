from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.bid_runtime_state import read_json_file, write_json_file_atomic
from app.services.bid_type import TECHNICAL_BID_TYPE
from app.services.material_tags import normalize_material_tags
from app.services.material_taxonomy import normalize_material_tier
from app.services.technical_wiki_preview_prompt import (
    PREVIEW_BATCH_SIZE,
    PREVIEW_SCHEMA_VERSION,
    build_batch_preview_prompt,
    build_evidence_segments,
    build_preview_prompt,
    parse_batch_preview_reply,
    parse_preview_reply,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2

# 标签真值归属：自 v2 起，技术标 tag 的真值在本 JSON 索引自身，
# 而非 DB raw_files.ext_fields.tags（后者退役为非真值，仅在首次迁移时作种子）。
TAGS_SOURCE_OF_TRUTH = "index"

# --------------------------------------------------------------------------- #
# 文件卡片 AI 内容预览（preview）
# --------------------------------------------------------------------------- #
# 预览结果缓存在 DB raw_files.ext_fields["techWikiPreview"]（按内容指纹增量重算），
# 重建索引时把命中的 preview 子对象注入 file entry，供镜像脚本渲染。tag 真值在
# JSON、preview 缓存在 DB —— 两套机制相互独立。镜像脚本对缺 preview 字段的 entry
# 自动降级为纯目录卡片，故老索引与新脚本兼容。

# ext_fields 缓存键。
PREVIEW_EXT_FIELD = "techWikiPreview"

# PREVIEW_SCHEMA_VERSION / PREVIEW_BATCH_SIZE 由 skill 侧 prompt 模块定义，
# 经 technical_wiki_preview_prompt 桥接 import（见上方 import）。

# 后台批量生成时对未缓存 docx 调 LLM 的并发上限。批量合并后，限的是「批」而非「文件」。
PREVIEW_CONCURRENCY = 4

# 档位标签，仅用于 prompt 里给 LLM 的语境提示。
_TIER_LABELS = {
    "standard": "标准文件",
    "customer": "客户定制",
    "project": "项目定制",
}

# 后端数据目录下的索引文件（非素材库、非数据库）。
TECHNICAL_MATERIAL_INDEX_PATH = (
    settings.documents_dir / "_runtime" / "materials" / "technical_material_index.json"
)

# 写盘串行化：rebuild（结构变更钩子触发）与 set_tags_for_node（人工打 tag）
# 都改写同一份 JSON。JSON 当真值后，写丢就是真丢，故全程持锁 + 原子写。
_INDEX_WRITE_LOCK = asyncio.Lock()


def _resolve_tier(folder_name: str) -> str:
    """按 2 级目录名判定 tier（standard/customer/project）。

    实际库的 2 级目录名为「标准文件/客户定制/项目定制」，且其 DB tier 字段
    并不可靠（实测三档均为 standard），故以目录名为准：
    - 复用 normalize_material_tier()，它已覆盖「客户定制→customer / 项目定制→project」
      以及「客户素材/项目素材/通用素材」等历史别名；
    - 它未覆盖「标准文件」（返回空），技术标 2 级目录只有这三类，非客户/项目即标准。
    """
    tier = normalize_material_tier(folder_name)
    return tier or "standard"


def _now_display() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalize_path(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip().strip("/")


def _third_level_path(folder_path: str) -> str:
    """把任意 folderPath 归并到它所属的 3 级祖先目录。

    技术标/通用素材/公司介绍/子目录/x -> 技术标/通用素材/公司介绍
    技术标/通用素材                  -> ""（2 级及以上不属于任何 3 级目录）
    """
    parts = [part for part in _normalize_path(folder_path).split("/") if part]
    if len(parts) < 3 or parts[0] != TECHNICAL_BID_TYPE:
        return ""
    return "/".join(parts[:3])


def _coerce_folder_id(value: Any) -> str:
    """把 tree 节点的 folderId 归一为字符串键（认领表用）。空/缺失 -> ""。"""
    if value is None:
        return ""
    return str(value).strip()


# --------------------------------------------------------------------------- #
# 文件卡片 AI 内容预览：指纹 / prompt / 调 LLM / 缓存
# --------------------------------------------------------------------------- #


def _preview_signature(name: str, profile: dict[str, Any]) -> str:
    """基于文件名 + docx 摘要 + 预览版本算内容指纹；内容变/改名/升版本即失效。"""
    basis = {
        "schema": PREVIEW_SCHEMA_VERSION,
        "name": str(name or ""),
        "headings": [str(h.get("title") or "") for h in (profile.get("headings") or [])],
        "paragraphs": list(profile.get("paragraphs") or []),
        "tableCount": int(profile.get("tableCount") or 0),
    }
    raw = json.dumps(basis, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _safe_build_segments(material_id: str, name: str, path: str, profile: dict[str, Any]) -> list[dict[str, Any]]:
    """确定性切分证据片段，吞异常（切分失败不应拖垮预览/索引）。"""
    try:
        return build_evidence_segments(material_id, name, path, profile)
    except Exception:  # noqa: BLE001 - 切分尽力而为，失败返回空
        return []


def _should_generate_preview(ext: str, profile: dict[str, Any]) -> tuple[bool, str]:
    """是否值得调 LLM 生成预览。返回 (should, skipReason)。"""
    if str(ext or "").lower() != "docx":
        return False, "非 docx，无可解析正文"
    if profile.get("parseError"):
        return False, str(profile.get("parseError"))
    has_headings = bool(profile.get("headings"))
    has_paragraphs = bool(profile.get("paragraphs"))
    if not has_headings and not has_paragraphs:
        return False, "未抽取到 Heading 或正文摘录"
    return True, ""


def _compute_preview_payload(
    *,
    name: str,
    path: str,
    tier_label: str,
    ext: str,
    signature: str,
    profile: dict[str, Any],
    material_id: str = "",
) -> dict[str, Any]:
    """纯计算（跑在线程池）：降级判定 -> 调 LLM -> 解析 -> 组完整缓存 payload。

    全程吞异常，永不抛出；失败记为 status=failed，让上层降级为纯索引卡片。
    evidenceSegments 由 profile 确定性切分（不依赖 LLM），只要 docx 解析出
    heading/正文就附上，供非附表正文缺口召回；LLM 预览失败不影响它。
    """
    from app.services.opencode_client import OpencodeClient  # 延迟导入避免循环引用

    segments = _safe_build_segments(material_id, name, path, profile)
    base = {
        "schemaVersion": PREVIEW_SCHEMA_VERSION,
        "signature": signature,
        "generatedAt": _now_display(),
        "evidenceSegments": segments,
    }

    should, skip_reason = _should_generate_preview(ext, profile)
    if not should:
        return {**base, "status": "skipped", "skipReason": skip_reason, "preview": {}}

    try:
        client = OpencodeClient()
        prompt = build_preview_prompt(name, path, tier_label, profile)
        result = client.send_text_prompt("技术标素材预览", prompt)
        preview = parse_preview_reply(str(result.get("reply") or ""), OpencodeClient._parse_json_payload)
        if not preview:
            return {**base, "status": "failed", "skipReason": "LLM 回复无有效内容", "preview": {}}
        return {
            **base,
            "status": "completed",
            "skipReason": "",
            "model": str(result.get("modelId") or ""),
            "preview": preview,
        }
    except Exception as exc:  # noqa: BLE001 - LLM 不可用/超时一律降级
        return {**base, "status": "failed", "skipReason": str(exc)[:200], "preview": {}}


def _docx_profile_for_raw_file(item: Any) -> tuple[str, dict[str, Any]]:
    """取 RawFile 对应的 docx 摘要 profile。返回 (ext, profile)。

    优先解析清洗后的 Word；无清洗稿则用原始文件。超过同步上限或非 docx 返回带
    parseError/空 profile，交由 _should_generate_preview 降级。同步函数，跑线程池。
    """
    from app.services.minio_client import minio_client  # 延迟导入避免循环引用
    from app.services.wiki_blueprint_common import MAX_SYNC_DOCX_BYTES, extract_docx_profile

    ext_fields = item.ext_fields or {}
    name = str(item.name or "")
    source_ext = Path(name).suffix.lower().lstrip(".") or "file"
    cleaned_key = str(ext_fields.get("cleanedMinioKey") or "")
    has_cleaned = bool(cleaned_key)
    ext = "docx" if source_ext == "docx" or has_cleaned else source_ext

    empty: dict[str, Any] = {
        "headings": [],
        "paragraphs": [],
        "tables": [],
        "tableCount": 0,
        "parseError": "",
    }
    if ext != "docx":
        return ext, empty

    if has_cleaned:
        bucket = str(ext_fields.get("cleanedMinioBucket") or item.minio_bucket or "")
        key = cleaned_key
        parse_size = int(ext_fields.get("cleanedSize") or item.size_bytes or 0)
    else:
        bucket = str(item.minio_bucket or "")
        key = str(item.minio_key or "")
        parse_size = int(item.size_bytes or 0)

    if parse_size > MAX_SYNC_DOCX_BYTES:
        return ext, {**empty, "parseError": f"文件超过同步解析上限 {MAX_SYNC_DOCX_BYTES // 1024 // 1024}MB"}

    try:
        data = minio_client.get_object(bucket, key)
    except Exception as exc:  # noqa: BLE001 - 取文件失败按降级
        return ext, {**empty, "parseError": f"docx 读取失败：{exc}"}
    return ext, extract_docx_profile(data)


async def _resolve_preview_plan(item: Any) -> dict[str, Any]:
    """为单个 RawFile 算指纹并判缓存命中。返回一个 plan dict：

    - 命中（指纹一致且已是终态 completed/skipped）：{"fileId", "hit": True, "payload": <复用的缓存>}
    - 未命中：{"fileId","hit":False,"name","path","tier_label","ext","signature","profile","base"}
      —— 携带后续批量/单文件计算所需的全部上下文。

    docx 解析跑线程池，不碰 session、不调 LLM。
    """
    file_id = f"RAW-{int(item.id):04d}"
    name = str(item.name or "")
    folder_path = item.folder.path if item.folder else ""
    path = f"{folder_path}/{name}".strip("/")
    tier_label = _TIER_LABELS.get(_resolve_tier(folder_path.split("/")[1] if "/" in folder_path else ""), "")
    ext_fields = dict(item.ext_fields or {})
    cached = ext_fields.get(PREVIEW_EXT_FIELD) if isinstance(ext_fields.get(PREVIEW_EXT_FIELD), dict) else {}

    # 取 docx 摘要并算指纹（解析跑线程池，不碰 session）。
    ext, profile = await asyncio.to_thread(_docx_profile_for_raw_file, item)
    signature = _preview_signature(name, profile)

    # 缓存命中：版本一致 + 指纹一致 + 已是终态（completed/skipped）则复用，不重算。
    # failed 默认重试（可能是临时超时）。
    if (
        cached.get("schemaVersion") == PREVIEW_SCHEMA_VERSION
        and cached.get("signature") == signature
        and cached.get("status") in {"completed", "skipped"}
    ):
        return {"fileId": file_id, "hit": True, "payload": cached}

    return {
        "fileId": file_id,
        "hit": False,
        "name": name,
        "path": path,
        "tier_label": tier_label,
        "ext": ext,
        "signature": signature,
        "profile": profile,
        "base": {
            "schemaVersion": PREVIEW_SCHEMA_VERSION,
            "signature": signature,
            "generatedAt": _now_display(),
            # 证据片段确定性切分，与 LLM 预览无关；无论预览成功/跳过/失败都附带。
            "evidenceSegments": _safe_build_segments(file_id, name, path, profile),
        },
    }


def _compute_batch_preview_payloads(plans: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """批量计算一批未命中文件的预览 payload。返回 {fileId: payload}。

    流程（纯计算，跑线程池）：
    1. 先按 _should_generate_preview 把不值得调 LLM 的标 skipped，不进 LLM 请求。
    2. 余下的合并成一次 batch prompt 调 LLM，按 fileId 拆回。
    3. 拆回有 preview 的标 completed；缺失/无效的标 failed（下次重试）。
    全程吞异常：整批 LLM 失败则该批所有待算文件标 failed，不抛出。
    """
    from app.services.opencode_client import OpencodeClient  # 延迟导入避免循环引用

    out: dict[str, dict[str, Any]] = {}
    to_llm: list[dict[str, Any]] = []
    for plan in plans:
        base = plan["base"]
        should, skip_reason = _should_generate_preview(plan["ext"], plan["profile"])
        if not should:
            out[plan["fileId"]] = {**base, "status": "skipped", "skipReason": skip_reason, "preview": {}}
        else:
            to_llm.append(plan)

    if not to_llm:
        return out

    try:
        client = OpencodeClient()
        prompt = build_batch_preview_prompt(
            [
                {
                    "fileId": plan["fileId"],
                    "name": plan["name"],
                    "path": plan["path"],
                    "tier_label": plan["tier_label"],
                    "profile": plan["profile"],
                }
                for plan in to_llm
            ]
        )
        result = client.send_text_prompt("技术标素材预览", prompt)
        previews = parse_batch_preview_reply(str(result.get("reply") or ""), OpencodeClient._parse_json_payload)
        model = str(result.get("modelId") or "")
    except Exception as exc:  # noqa: BLE001 - 整批 LLM 失败一律降级，该批文件下次重试
        for plan in to_llm:
            out[plan["fileId"]] = {**plan["base"], "status": "failed", "skipReason": str(exc)[:200], "preview": {}}
        return out

    for plan in to_llm:
        base = plan["base"]
        preview = previews.get(plan["fileId"])
        if preview:
            out[plan["fileId"]] = {**base, "status": "completed", "skipReason": "", "model": model, "preview": preview}
        else:
            out[plan["fileId"]] = {**base, "status": "failed", "skipReason": "LLM 批量回复缺该文件或无效", "preview": {}}
    return out


def _wanted_docx_ids(file_items: list[dict[str, Any]]) -> set[int]:
    """从索引 file_items 里筛出「归并进 3 级目录、且可能可解析的 docx」的 RAW-id 整数集。"""
    wanted_ids: set[int] = set()
    for item in file_items:
        if not _third_level_path(item.get("folderPath")):
            continue
        ext = str(item.get("ext") or item.get("type") or "").lower()
        raw_id = str(item.get("id") or "")
        # docx 原稿，或有清洗后 Word（hasCleanedWord）的非 docx 原稿，都可能可解析。
        if ext == "docx" or item.get("hasCleanedWord"):
            if raw_id.startswith("RAW-"):
                try:
                    wanted_ids.add(int(raw_id[4:]))
                except ValueError:
                    continue
    return wanted_ids


def _slim_preview_payload(cached: dict[str, Any]) -> dict[str, Any]:
    """从一份缓存 payload 抽出要注入索引的轻量子对象。

    - preview：仅当 LLM 生成完成（completed）且非空时带上。
    - evidenceSegments：确定性切分结果，与 LLM 状态无关，有就带上（供正文缺口召回）。

    两者都没有时返回空 dict，调用方据此跳过注入。
    """
    if not isinstance(cached, dict):
        return {}
    slim: dict[str, Any] = {}
    if cached.get("status") == "completed" and isinstance(cached.get("preview"), dict) and cached["preview"]:
        slim["preview"] = cached["preview"]
    segments = cached.get("evidenceSegments")
    if isinstance(segments, list) and segments:
        slim["evidenceSegments"] = segments
    return slim


async def _collect_cached_previews(file_items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """只读 DB 里已缓存（completed）的预览，不调 LLM、不写盘。
    供 Wiki 镜像「快路径」使用：重建/刷新 Wiki 时秒级注入已生成的预览卡片，
    尚未生成预览的 docx 自动降级为纯目录卡片，等后台任务补齐。
    """
    from sqlalchemy import select

    from app.models import async_session
    from app.models.materials import RawFile

    wanted_ids = _wanted_docx_ids(file_items)
    if not wanted_ids:
        return {}

    preview_by_id: dict[str, dict[str, Any]] = {}
    async with async_session() as session:
        result = await session.execute(
            select(RawFile.id, RawFile.ext_fields).where(RawFile.id.in_(wanted_ids))
        )
        for raw_id, ext_fields in result.all():
            cached = (ext_fields or {}).get(PREVIEW_EXT_FIELD)
            if not isinstance(cached, dict):
                continue
            file_id = f"RAW-{int(raw_id):04d}"
            slim = _slim_preview_payload(cached)
            if slim:
                preview_by_id[file_id] = slim
    return preview_by_id


async def _enrich_previews(
    file_items: list[dict[str, Any]],
    *,
    progress_cb: Any | None = None,
) -> dict[str, dict[str, Any]]:
    """为索引内的 docx 文件批量生成/复用预览，返回 {RAW-id: preview 子对象}。

    仅含 status==completed 的文件。命中缓存（指纹一致）的不调 LLM。整段 best-effort：
    任何异常都不阻断索引重建，最坏情况退化为「无预览」的纯目录索引。

    progress_cb(done, total)：可选回调，每处理完一个文件回报一次进度（供后台任务落盘）。
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models import async_session
    from app.models.materials import RawFile

    # 只对当前归并进 3 级目录、且看起来是 docx 的文件取预览，省掉无谓 ORM/LLM。
    wanted_ids = _wanted_docx_ids(file_items)
    if not wanted_ids:
        if callable(progress_cb):
            progress_cb(0, 0)
        return {}

    preview_by_id: dict[str, dict[str, Any]] = {}
    async with async_session() as session:
        result = await session.execute(
            select(RawFile)
            .where(RawFile.id.in_(wanted_ids))
            .options(selectinload(RawFile.folder))
        )
        items = list(result.scalars().all())

        total = len(items)
        done = 0
        if callable(progress_cb):
            progress_cb(done, total)

        # 第一步：逐文件算指纹 + 判缓存命中（解析跑线程池，不调 LLM）。
        # 命中的直接复用；未命中的进「待算列表」，稍后切批合并请求。
        plans: list[dict[str, Any]] = []
        pending: list[dict[str, Any]] = []
        for it in items:
            try:
                plan = await _resolve_preview_plan(it)
            except Exception as exc:  # noqa: BLE001 - 单文件解析失败不拖垮整批
                logger.warning("tech wiki preview plan failed for one file", exc_info=exc)
                plan = None
            plans.append(plan)
            if plan is not None and not plan["hit"]:
                pending.append(plan)

        # 第二步：把待算文件切成 PREVIEW_BATCH_SIZE 一批，每批一次 LLM 调用（限「批」并发）。
        # payload_by_id 收集未命中文件计算出的 payload。
        payload_by_id: dict[str, dict[str, Any]] = {}
        sem = asyncio.Semaphore(PREVIEW_CONCURRENCY)
        batches = [pending[i : i + PREVIEW_BATCH_SIZE] for i in range(0, len(pending), PREVIEW_BATCH_SIZE)]

        async def _run_batch(batch: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
            nonlocal done
            async with sem:
                try:
                    result_map = await asyncio.to_thread(_compute_batch_preview_payloads, batch)
                except Exception as exc:  # noqa: BLE001 - 整批失败：该批全部标 failed，下次重试
                    logger.warning("tech wiki preview batch failed", exc_info=exc)
                    result_map = {
                        plan["fileId"]: {**plan["base"], "status": "failed", "skipReason": str(exc)[:200], "preview": {}}
                        for plan in batch
                    }
            done += len(batch)
            if callable(progress_cb):
                progress_cb(min(done, total), total)
            return result_map

        for result_map in await asyncio.gather(*[_run_batch(b) for b in batches]):
            payload_by_id.update(result_map)

        # 第三步：把未命中文件计算出的 payload 写回各自 ext_fields（主协程，统一 commit）。
        id_to_item = {f"RAW-{int(it.id):04d}": it for it in items}
        for file_id, payload in payload_by_id.items():
            it = id_to_item.get(file_id)
            if it is None:
                continue
            ext_fields = dict(it.ext_fields or {})
            ext_fields[PREVIEW_EXT_FIELD] = payload
            it.ext_fields = ext_fields

        await session.commit()

    # 汇总：命中复用的 payload 与新算的 payload 合在一起，挑 completed 的回填预览。
    completed = skipped = failed = 0
    for plan in plans:
        if plan is None:
            failed += 1
            continue
        file_id = plan["fileId"]
        payload = plan["payload"] if plan["hit"] else payload_by_id.get(file_id)
        if not isinstance(payload, dict):
            failed += 1
            continue
        status = payload.get("status")
        slim = _slim_preview_payload(payload)
        if status == "completed" and payload.get("preview"):
            if slim:
                preview_by_id[file_id] = slim
            completed += 1
        elif status == "skipped":
            # 预览跳过（无正文），但确定性切分可能仍有片段，照样回填供召回。
            if slim:
                preview_by_id[file_id] = slim
            skipped += 1
        else:
            if slim:
                preview_by_id[file_id] = slim
            failed += 1
    logger.info(
        "tech wiki preview enrich: %d completed, %d skipped, %d failed (of %d docx, %d batches)",
        completed,
        skipped,
        failed,
        len(items),
        (len(pending) + PREVIEW_BATCH_SIZE - 1) // PREVIEW_BATCH_SIZE,
    )
    return preview_by_id


# --------------------------------------------------------------------------- #
# 旧索引 -> tag 认领表
# --------------------------------------------------------------------------- #


def _collect_prior_tags(prev: dict[str, Any]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """从旧 JSON 索引提取 tag 真值，建认领表。

    返回 (files_by_id, folders_by_id)：
    - files_by_id:   {RAW-xxxx -> tags}
    - folders_by_id: {folderId(str) -> tags}（tier 与 3 级 folder 共用此表）

    认领键用 id（文件 RAW-xxxx / 目录 folderId），不用 path —— 改名/移动 tag 不丢。
    """
    files_by_id: dict[str, list[str]] = {}
    folders_by_id: dict[str, list[str]] = {}

    for tier in prev.get("tiers") or []:
        tier_fid = _coerce_folder_id(tier.get("folderId"))
        if tier_fid:
            folders_by_id[tier_fid] = list(tier.get("tags") or [])
        for folder in tier.get("folders") or []:
            fid = _coerce_folder_id(folder.get("folderId"))
            if fid:
                folders_by_id[fid] = list(folder.get("tags") or [])
            for file_item in folder.get("files") or []:
                file_id = str(file_item.get("id") or "")
                if file_id:
                    files_by_id[file_id] = list(file_item.get("tags") or [])

    return files_by_id, folders_by_id


def _is_seedable(prev: dict[str, Any]) -> bool:
    """旧索引是否仍需从 DB 种 tag（首次迁移）。

    旧索引缺失、或 schemaVersion < 2 时，视为尚未迁移：file tag 用 DB ext.tags 作种子。
    一旦升到 v2，DB 不再是 file tag 真值，只认旧 JSON。
    """
    if not prev:
        return True
    try:
        return int(prev.get("schemaVersion") or 0) < SCHEMA_VERSION
    except (TypeError, ValueError):
        return True


# --------------------------------------------------------------------------- #
# 节点构建
# --------------------------------------------------------------------------- #


def _file_entry(
    item: dict[str, Any],
    *,
    files_by_id: dict[str, list[str]],
    seed_from_db: bool,
    preview_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    folder_path = _normalize_path(item.get("folderPath"))
    name = str(item.get("name") or "")
    full_path = f"{folder_path}/{name}" if folder_path else name
    file_id = str(item.get("id") or "")

    # tag 真值优先取旧 JSON（按 id 认领）；旧索引未迁移时从 DB ext.tags 种子。
    if file_id in files_by_id:
        tags = files_by_id[file_id]
    elif seed_from_db:
        tags = normalize_material_tags(item.get("tags"))
    else:
        tags = []

    entry = {
        "id": file_id,
        "name": name,
        "path": full_path,
        "ext": str(item.get("ext") or item.get("type") or ""),
        "cleanStatus": str(item.get("cleanStatus") or ""),
        "tags": tags,
    }

    # AI 内容预览 + 证据片段：preview 仅在 LLM 生成完成时有值；evidenceSegments
    # 由 profile 确定性切分，与 LLM 无关，故可独立存在（即便预览 skipped/failed）。
    enriched = (preview_by_id or {}).get(file_id)
    if isinstance(enriched, dict):
        if enriched.get("preview"):
            entry["preview"] = enriched["preview"]
        if enriched.get("evidenceSegments"):
            entry["evidenceSegments"] = enriched["evidenceSegments"]

    return entry


def _build_payload(
    tree: dict[str, Any],
    file_items: list[dict[str, Any]],
    *,
    prev: dict[str, Any],
    preview_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    generated_at = _now_display()
    files_by_id, folders_by_id = _collect_prior_tags(prev)
    seed_from_db = _is_seedable(prev)

    # 把文件按所属 3 级目录归并。
    files_by_third: dict[str, list[dict[str, Any]]] = {}
    for item in file_items:
        third = _third_level_path(item.get("folderPath"))
        if not third:
            continue
        entry = _file_entry(
            item,
            files_by_id=files_by_id,
            seed_from_db=seed_from_db,
            preview_by_id=preview_by_id,
        )
        files_by_third.setdefault(third, []).append(entry)

    # 技术标 root（1 级）的直接子节点 = 2 级 tier 目录。
    root_nodes = [
        node
        for node in (tree.get("tree") or [])
        if _normalize_path(node.get("path")) == TECHNICAL_BID_TYPE
    ]
    root_children = root_nodes[0].get("children") if root_nodes else []

    tiers: list[dict[str, Any]] = []
    total_files = 0
    total_third_folders = 0

    for tier_node in root_children or []:
        tier_name = str(tier_node.get("name") or "")
        tier_value = _resolve_tier(tier_name)
        tier_path = _normalize_path(tier_node.get("path"))
        tier_fid = _coerce_folder_id(tier_node.get("folderId"))

        folders: list[dict[str, Any]] = []
        tier_file_count = 0

        for third_node in tier_node.get("children") or []:
            third_path = _normalize_path(third_node.get("path"))
            third_fid = _coerce_folder_id(third_node.get("folderId"))
            files = files_by_third.get(third_path, [])
            file_count = len(files)
            tier_file_count += file_count
            total_third_folders += 1

            folders.append(
                {
                    "name": str(third_node.get("name") or ""),
                    "path": third_path,
                    "tier": tier_value,
                    "folderId": third_fid,
                    "customerName": "",
                    "customerId": "",
                    "projectId": "",
                    "projectCode": "",
                    "description": "",
                    "fileCount": file_count,
                    "updatedAt": generated_at,
                    # 目录 tag 真值在 JSON：按 folderId 从旧索引认领，新目录默认空。
                    "tags": folders_by_id.get(third_fid, []),
                    "files": files,
                }
            )

        # 客户/项目档的 3 级目录名即客户名/项目标识，回填到对应字段。
        for folder in folders:
            if tier_value == "customer":
                folder["customerName"] = folder["name"]
            elif tier_value == "project":
                folder["projectId"] = folder["name"]

        total_files += tier_file_count
        tiers.append(
            {
                "name": tier_name,
                "tier": tier_value,
                "path": tier_path,
                "folderId": tier_fid,
                "fileCount": tier_file_count,
                "tags": folders_by_id.get(tier_fid, []),
                "folders": folders,
            }
        )

    return {
        "bidType": TECHNICAL_BID_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "tagsSourceOfTruth": TAGS_SOURCE_OF_TRUTH,
        "generatedAt": generated_at,
        "stats": {
            "tierCount": len(tiers),
            "thirdLevelFolderCount": total_third_folders,
            "fileCount": total_files,
        },
        "tiers": tiers,
    }


def _write_index(payload: dict[str, Any]) -> None:
    write_json_file_atomic(TECHNICAL_MATERIAL_INDEX_PATH, payload)


async def _rebuild_payload(
    prev: dict[str, Any],
    *,
    preview_mode: str = "cached",
    progress_cb: Any | None = None,
) -> dict[str, Any]:
    """从 DB 实时结构 + 旧索引 tag 重建 payload（不写盘）。

    preview_mode 控制 AI 内容预览的注入策略：
    - "none"    跳过预览（如人工打 tag 触发的兜底重建），只重建结构 + 认领 tag。
    - "cached"  只读 DB 里已生成（completed）的预览缓存注入，不调 LLM（秒级）。
                Wiki 重建/刷新走此路径：已生成的预览立即出卡片，未生成的降级为纯目录。
    - "generate" 增量生成缺失预览（调 LLM，慢），供后台任务使用。
    """
    # 延迟导入，避免与 technical_material_store 形成循环引用。
    from app.services.technical_material_store import technical_material_store

    tree = await technical_material_store.raw_tree()
    files = await technical_material_store.raw_files(
        folder_path=TECHNICAL_BID_TYPE,
        recursive=True,
        page=1,
        page_size=100000,
    )
    file_items = list(files.get("items") or [])

    # AI 内容预览（best-effort）：失败不阻断索引重建。
    preview_by_id: dict[str, dict[str, Any]] = {}
    if preview_mode == "generate":
        try:
            preview_by_id = await _enrich_previews(file_items, progress_cb=progress_cb)
        except Exception:  # noqa: BLE001 - 预览是增量增强，挂了也要出纯目录索引
            logger.warning("technical material preview enrich failed", exc_info=True)
    elif preview_mode == "cached":
        try:
            preview_by_id = await _collect_cached_previews(file_items)
        except Exception:  # noqa: BLE001
            logger.warning("technical material cached preview read failed", exc_info=True)

    return _build_payload(tree, file_items, prev=prev, preview_by_id=preview_by_id)


async def rebuild_technical_material_index(
    *,
    preview_mode: str = "none",
    progress_cb: Any | None = None,
) -> dict[str, Any]:
    """从数据库实时结构重建技术标三级目录 JSON 索引并写盘。

    结构真值在 DB，tag 真值在旧 JSON：按 id 认领把 tag 贴回新树（merge-preserve），
    全程持写锁 + 原子写，避免与人工打 tag 互相覆写。

    preview_mode（见 _rebuild_payload）：
    - "none"     默认。结构变更钩子（上传/移动/删除）很频繁，不碰预览。
    - "cached"   Wiki 重建/刷新走此路径：秒级注入已缓存预览，不调 LLM。
    - "generate" 后台预览任务走此路径：增量调 LLM 补齐缺失预览。

    best-effort：内部异常被捕获并记录，绝不向上抛出，以免影响主素材操作。
    """
    try:
        async with _INDEX_WRITE_LOCK:
            prev = load_technical_material_index()
            payload = await _rebuild_payload(prev, preview_mode=preview_mode, progress_cb=progress_cb)
            _write_index(payload)
            return payload
    except Exception:  # noqa: BLE001 - 钩子是 best-effort，失败不阻断主流程
        logger.warning("technical material index rebuild failed", exc_info=True)
        return {}


def load_technical_material_index() -> dict[str, Any]:
    """读取已落盘的技术标三级目录 JSON 索引；不存在或损坏时返回 {}。"""
    return read_json_file(TECHNICAL_MATERIAL_INDEX_PATH)


# --------------------------------------------------------------------------- #
# 写 tag（人工就地标注，真值落 JSON）
# --------------------------------------------------------------------------- #


def _match_file(node_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    for tier in payload.get("tiers") or []:
        for folder in tier.get("folders") or []:
            for file_item in folder.get("files") or []:
                if str(file_item.get("id") or "") == node_id:
                    return file_item
    return None


def _match_folder(target_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """按 folderId 或 path 定位 tier / 3 级 folder 节点。"""
    target = _coerce_folder_id(target_id)
    target_path = _normalize_path(target_id)
    for tier in payload.get("tiers") or []:
        if (target and _coerce_folder_id(tier.get("folderId")) == target) or (
            target_path and _normalize_path(tier.get("path")) == target_path
        ):
            return tier
        for folder in tier.get("folders") or []:
            if (target and _coerce_folder_id(folder.get("folderId")) == target) or (
                target_path and _normalize_path(folder.get("path")) == target_path
            ):
                return folder
    return None


async def set_tags_for_node(*, target_id: str, tags: Any) -> dict[str, Any]:
    """对索引中某节点（文件 RAW-xxxx / 目录 folderId 或 path）设置 tag。

    tag 真值落 JSON：定位节点 -> normalize_material_tags 规整 -> 写回 -> 返回该节点。
    全程持写锁 + 原子写，与 rebuild 串行。
    """
    target = str(target_id or "").strip()
    if not target:
        raise ValueError("targetId 不能为空")

    normalized = normalize_material_tags(tags)

    async with _INDEX_WRITE_LOCK:
        payload = load_technical_material_index()
        if not payload:
            payload = await _rebuild_payload({}, preview_mode="cached")

        if target.startswith("RAW-"):
            node = _match_file(target, payload)
        else:
            node = _match_folder(target, payload)

        if node is None:
            raise LookupError(f"未在索引中找到节点：{target}")

        node["tags"] = normalized
        _write_index(payload)
        return node
