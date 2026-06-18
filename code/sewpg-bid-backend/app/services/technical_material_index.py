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

# 预览缓存结构版本，与索引 SCHEMA_VERSION 解耦：仅当 prompt 或 preview 字段结构
# 变化时升此版本，让所有文件缓存指纹失效、触发重算。
PREVIEW_SCHEMA_VERSION = 1

# 首次全量重建时对未缓存 docx 并发调 LLM 的上限（opencode 同步 httpx，跑线程池）。
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


def _build_preview_prompt(name: str, path: str, tier_label: str, profile: dict[str, Any]) -> str:
    """组单文件预览 prompt。复用 wiki_generation 的 heading 树格式化。"""
    from app.services.wiki_generation import _format_heading_tree  # 延迟导入避免循环引用

    headings = profile.get("headings") or []
    paragraphs = profile.get("paragraphs") or []
    heading_tree = _format_heading_tree(headings) if headings else "（无）"
    paragraph_block = "\n".join(f"- {p}" for p in paragraphs) if paragraphs else "（无）"

    return (
        "你是投标素材库的资料员。下面是一份技术标素材文件的结构化摘要，"
        "请生成一张「内容预览卡片」。\n\n"
        f"文件名：{name}\n"
        f"所在路径：{path}\n"
        f"所属档位：{tier_label}\n"
        f"检测到的标题：\n{heading_tree}\n"
        f"正文摘录（最多10段）：\n{paragraph_block}\n\n"
        "要求：\n"
        "1. 只输出严格 JSON，不要解释、不要代码块。\n"
        "2. 不要编造文中没有的事实；信息不足的字段给空数组/空串。\n"
        "3. 结构严格满足：\n"
        '{"lead":"一句话导读 ≤80字，说明这份材料是什么、能用于投标哪个环节",'
        '"points":["3到5条要点，每条≤40字"],'
        '"keyParams":[{"label":"参数名","value":"参数值"}],'
        '"retrievalHints":["2到6个检索关键词或适用场景"]}'
    )


def _parse_preview_reply(reply: str) -> dict[str, Any] | None:
    """把 LLM 回复解析成裁剪后的 preview 子对象；无有效内容返回 None。"""
    from app.services.opencode_client import OpencodeClient  # 延迟导入避免循环引用

    try:
        parsed = OpencodeClient._parse_json_payload(str(reply or ""))
    except Exception:  # noqa: BLE001 - 解析失败按降级处理
        return None
    if not isinstance(parsed, dict):
        return None

    lead = str(parsed.get("lead") or "").strip()[:120]

    points: list[str] = []
    for item in parsed.get("points") or []:
        text = str(item or "").strip()
        if text:
            points.append(text[:80])
        if len(points) >= 5:
            break

    key_params: list[dict[str, str]] = []
    for kv in parsed.get("keyParams") or []:
        if not isinstance(kv, dict):
            continue
        label = str(kv.get("label") or "").strip()[:40]
        value = str(kv.get("value") or "").strip()[:120]
        if label or value:
            key_params.append({"label": label, "value": value})
        if len(key_params) >= 8:
            break

    hints: list[str] = []
    for item in parsed.get("retrievalHints") or []:
        text = str(item or "").strip()
        if text:
            hints.append(text[:40])
        if len(hints) >= 6:
            break

    if not lead and not points:
        return None

    return {
        "lead": lead,
        "points": points,
        "keyParams": key_params,
        "retrievalHints": hints,
    }


def _compute_preview_payload(
    *,
    name: str,
    path: str,
    tier_label: str,
    ext: str,
    signature: str,
    profile: dict[str, Any],
) -> dict[str, Any]:
    """纯计算（跑在线程池）：降级判定 -> 调 LLM -> 解析 -> 组完整缓存 payload。

    全程吞异常，永不抛出；失败记为 status=failed，让上层降级为纯索引卡片。
    """
    from app.services.opencode_client import OpencodeClient  # 延迟导入避免循环引用

    base = {
        "schemaVersion": PREVIEW_SCHEMA_VERSION,
        "signature": signature,
        "generatedAt": _now_display(),
    }

    should, skip_reason = _should_generate_preview(ext, profile)
    if not should:
        return {**base, "status": "skipped", "skipReason": skip_reason, "preview": {}}

    try:
        client = OpencodeClient()
        prompt = _build_preview_prompt(name, path, tier_label, profile)
        result = client.send_text_prompt("技术标素材预览", prompt)
        preview = _parse_preview_reply(str(result.get("reply") or ""))
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
    from app.services.wiki_generation import MAX_SYNC_DOCX_BYTES, _extract_docx_profile

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
    return ext, _extract_docx_profile(data)


async def _ensure_preview_for_item(
    item: Any,
    sem: asyncio.Semaphore,
) -> tuple[str, dict[str, Any]]:
    """为单个 RawFile 生成/复用预览缓存。返回 (RAW-id, techWikiPreview payload)。

    缓存命中（指纹一致且已完成/已跳过）则复用，不调 LLM；否则解析 docx + 调 LLM。
    所有解析与 LLM 调用走线程池，ext_fields 写回与最终 commit 由调用方在主协程做。
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
        return file_id, cached

    async with sem:
        payload = await asyncio.to_thread(
            _compute_preview_payload,
            name=name,
            path=path,
            tier_label=tier_label,
            ext=ext,
            signature=signature,
            profile=profile,
        )

    # 写回 ext_fields（主协程，调用方统一 commit）。
    ext_fields[PREVIEW_EXT_FIELD] = payload
    item.ext_fields = ext_fields
    return file_id, payload


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
            if (
                isinstance(cached, dict)
                and cached.get("status") == "completed"
                and isinstance(cached.get("preview"), dict)
                and cached["preview"]
            ):
                preview_by_id[f"RAW-{int(raw_id):04d}"] = cached["preview"]
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

        sem = asyncio.Semaphore(PREVIEW_CONCURRENCY)
        outcomes: list[Any] = []

        async def _run_one(it: Any) -> Any:
            nonlocal done
            try:
                outcome = await _ensure_preview_for_item(it, sem)
            except Exception as exc:  # noqa: BLE001 - 单文件失败不拖垮整批
                outcome = exc
            done += 1
            if callable(progress_cb):
                progress_cb(done, total)
            return outcome

        outcomes = await asyncio.gather(*[_run_one(it) for it in items])
        await session.commit()

    completed = skipped = failed = 0
    for outcome in outcomes:
        if isinstance(outcome, BaseException):
            logger.warning("tech wiki preview generation failed for one file", exc_info=outcome)
            failed += 1
            continue
        file_id, payload = outcome
        status = payload.get("status")
        if status == "completed" and payload.get("preview"):
            preview_by_id[file_id] = payload["preview"]
            completed += 1
        elif status == "skipped":
            skipped += 1
        else:
            failed += 1
    logger.info(
        "tech wiki preview enrich: %d completed, %d skipped, %d failed (of %d docx)",
        completed,
        skipped,
        failed,
        len(items),
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

    # AI 内容预览：仅注入已生成（completed）的 preview 子对象；缺失即降级渲染。
    preview = (preview_by_id or {}).get(file_id)
    if preview:
        entry["preview"] = preview

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
