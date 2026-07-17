from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from app.services.bid_type import TECHNICAL_BID_TYPE
from app.services.technical_wiki_preview_prompt import (
    PREVIEW_BATCH_SIZE,
    PREVIEW_SCHEMA_VERSION,
    build_batch_preview_prompt,
    build_evidence_segments,
    parse_batch_preview_reply,
)
from app.services.wiki_blueprint_common import MAX_SYNC_DOCX_BYTES, extract_docx_profile

logger = logging.getLogger(__name__)

PREVIEW_EXT_FIELD = "techWikiPreview"
PREVIEW_CONCURRENCY = 4
LOCAL_FALLBACK_POINT_LIMIT = 5
TIER_LABELS = {
    "standard": "标准文件",
    "customer": "客户定制",
    "project": "项目定制",
}


def _now_display() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _preview_signature(name: str, profile: dict[str, Any]) -> str:
    basis = {
        "schema": PREVIEW_SCHEMA_VERSION,
        "name": str(name or ""),
        "headings": [str(h.get("title") or "") for h in (profile.get("headings") or [])],
        "paragraphs": list(profile.get("paragraphs") or []),
        "tableCount": int(profile.get("tableCount") or 0),
    }
    raw = json.dumps(basis, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _iter_index_files(index_payload: dict[str, Any]) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for tier in index_payload.get("tiers") or []:
        tier_code = str(tier.get("tier") or "")
        tier_label = str(tier.get("name") or TIER_LABELS.get(tier_code) or tier_code)
        for folder in tier.get("folders") or []:
            for file_item in folder.get("files") or []:
                if not isinstance(file_item, dict):
                    continue
                file_id = str(file_item.get("id") or "")
                if file_id.startswith("RAW-"):
                    files.append(
                        {
                            "fileId": file_id,
                            "tierCode": tier_code,
                            "tierLabel": tier_label,
                            "file": file_item,
                        }
                    )
    return files


def _raw_numeric_id(file_id: str) -> int | None:
    try:
        return int(str(file_id).replace("RAW-", ""))
    except ValueError:
        return None


def _should_generate_preview(ext: str, profile: dict[str, Any]) -> tuple[bool, str]:
    if str(ext or "").lower() != "docx":
        return False, "非 docx，无可解析正文"
    if profile.get("parseError"):
        return False, str(profile.get("parseError"))
    if not profile.get("headings") and not profile.get("paragraphs"):
        return False, "未抽取到 Heading 或正文摘录"
    return True, ""


def _docx_profile_for_raw_file(item: Any) -> tuple[str, dict[str, Any]]:
    from app.services.minio_client import minio_client

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
    except Exception as exc:  # noqa: BLE001
        return ext, {**empty, "parseError": f"docx 读取失败：{exc}"}
    return ext, extract_docx_profile(data)


def _safe_build_evidence_segments(
    material_id: str,
    name: str,
    path: str,
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    try:
        return build_evidence_segments(material_id, name, path, profile)
    except Exception:  # noqa: BLE001 - 证据切分失败不能阻断 Wiki 预览
        logger.warning("technical wiki evidence segment build failed", exc_info=True)
        return []


def _base_payload(
    signature: str,
    evidence_segments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schemaVersion": PREVIEW_SCHEMA_VERSION,
        "signature": signature,
        "generatedAt": _now_display(),
    }
    if evidence_segments:
        payload["evidenceSegments"] = evidence_segments
    return payload


def _clean_text(value: Any, limit: int = 80) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _path_parts(path: str) -> list[str]:
    return [part for part in str(path or "").replace("\\", "/").split("/") if part]


def _local_preview_from_profile(
    *,
    name: str,
    path: str,
    tier_label: str,
    ext: str,
    clean_status: str,
    profile: dict[str, Any],
    reason: str = "",
) -> dict[str, Any]:
    """LLM 不可用时的确定性 TLDR，保证 Wiki 文件卡片不退化成纯定位信息。"""
    parts = _path_parts(path)
    folder_name = parts[-2] if len(parts) >= 2 else ""
    headings = [
        _clean_text(item.get("title"), 60)
        for item in (profile.get("headings") or [])
        if isinstance(item, dict) and _clean_text(item.get("title"), 60)
    ]
    paragraphs = [_clean_text(item, 90) for item in (profile.get("paragraphs") or []) if _clean_text(item, 90)]

    lead_basis = paragraphs[0] if paragraphs else ""
    if lead_basis:
        lead = f"{lead_basis} 可用于{tier_label or '技术标'}中「{folder_name or Path(name).stem}」相关内容检索与引用。"
    else:
        lead = f"{name} 位于{tier_label or '技术标'}素材目录，可用于「{folder_name or Path(name).stem}」相关内容检索与引用。"

    points: list[str] = []
    for title in headings[:LOCAL_FALLBACK_POINT_LIMIT]:
        if title and title not in points:
            points.append(f"包含章节：{title}")
    for paragraph in paragraphs[:LOCAL_FALLBACK_POINT_LIMIT]:
        if paragraph and paragraph not in points:
            points.append(paragraph)
        if len(points) >= LOCAL_FALLBACK_POINT_LIMIT:
            break
    if not points:
        points.append(f"文件路径已归入 {tier_label or '技术标'} / {folder_name or '未命名目录'}。")
    if reason:
        points.append(f"AI 预览未完成，当前为本地 TLDR：{_clean_text(reason, 90)}")

    key_params = [
        {"label": "文件类型", "value": ext or Path(name).suffix.lower().lstrip(".") or "file"},
        {"label": "所属目录", "value": folder_name or "未识别"},
        {"label": "清洗状态", "value": clean_status or "未知"},
    ]
    table_count = int(profile.get("tableCount") or 0)
    if table_count:
        key_params.append({"label": "表格数量", "value": str(table_count)})

    hints: list[str] = []
    for value in [Path(name).stem, folder_name, *headings[:4]]:
        value = _clean_text(value, 40)
        if value and value not in hints:
            hints.append(value)

    return {
        "lead": _clean_text(lead, 120),
        "points": points[:LOCAL_FALLBACK_POINT_LIMIT + 1],
        "keyParams": key_params,
        "retrievalHints": hints[:6],
        "source": "local",
    }


def _fallback_payload(plan: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        **plan["base"],
        "status": "fallback",
        "skipReason": reason,
        "metadata": {"cleanStatus": str(plan.get("clean_status") or "")},
        "preview": _local_preview_from_profile(
            name=str(plan.get("name") or plan.get("fileId") or ""),
            path=str(plan.get("path") or ""),
            tier_label=str(plan.get("tier_label") or ""),
            ext=str(plan.get("ext") or ""),
            clean_status=str(plan.get("clean_status") or ""),
            profile=plan.get("profile") or {},
            reason=reason,
        ),
    }


async def _build_preview_plans(index_files: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models import async_session
    from app.models.materials import RawFile

    wanted_ids = [raw_id for raw_id in (_raw_numeric_id(item["fileId"]) for item in index_files) if raw_id]
    if not wanted_ids:
        return [], {"total": 0, "completed": 0, "cached": 0, "skipped": 0, "failed": 0, "errors": []}

    meta_by_file_id = {item["fileId"]: item for item in index_files}
    plans: list[dict[str, Any]] = []
    stats = {"total": len(wanted_ids), "completed": 0, "cached": 0, "fallback": 0, "skipped": 0, "failed": 0, "errors": []}

    async with async_session() as session:
        result = await session.execute(
            select(RawFile)
            .where(RawFile.id.in_(wanted_ids))
            .options(selectinload(RawFile.folder))
        )
        raw_items = list(result.scalars().all())

    found_ids = {int(raw.id) for raw in raw_items}
    for missing_id in sorted(set(wanted_ids) - found_ids):
        file_id = f"RAW-{missing_id:04d}"
        stats["failed"] += 1
        stats["errors"].append({"fileId": file_id, "message": "JSON 索引引用的原始文件不存在"})

    for raw in raw_items:
        file_id = f"RAW-{int(raw.id):04d}"
        meta = meta_by_file_id.get(file_id)
        if not meta:
            continue
        try:
            ext, profile = await asyncio.to_thread(_docx_profile_for_raw_file, raw)
            signature = _preview_signature(str(raw.name or ""), profile)
            ext_fields = dict(raw.ext_fields or {})
            cached = ext_fields.get(PREVIEW_EXT_FIELD) if isinstance(ext_fields.get(PREVIEW_EXT_FIELD), dict) else {}
            if (
                cached.get("schemaVersion") == PREVIEW_SCHEMA_VERSION
                and cached.get("signature") == signature
                and cached.get("status") == "completed"
                and isinstance(cached.get("preview"), dict)
                and cached.get("preview")
            ):
                plans.append({"fileId": file_id, "hit": True, "payload": cached})
                stats["cached"] += 1
                continue

            folder_path = raw.folder.path if raw.folder else ""
            file_path = f"{folder_path}/{raw.name}".strip("/")
            base = _base_payload(
                signature,
                _safe_build_evidence_segments(file_id, str(raw.name or ""), file_path, profile),
            )
            should, skip_reason = _should_generate_preview(ext, profile)
            clean_status = str(ext_fields.get("cleanStatus") or "")
            if not should:
                preview = _local_preview_from_profile(
                    name=str(raw.name or ""),
                    path=file_path,
                    tier_label=str(meta.get("tierLabel") or ""),
                    ext=ext,
                    clean_status=clean_status,
                    profile=profile,
                    reason=skip_reason,
                )
                plans.append(
                    {
                        "fileId": file_id,
                        "hit": False,
                        "payload": {
                            **base,
                            "status": "fallback",
                            "skipReason": skip_reason,
                            "metadata": {"cleanStatus": clean_status},
                            "preview": preview,
                        },
                    }
                )
                stats["skipped"] += 1
                continue

            plans.append(
                {
                    "fileId": file_id,
                    "hit": False,
                    "name": str(raw.name or ""),
                    "path": file_path,
                    "tier_label": str(meta.get("tierLabel") or ""),
                    "ext": ext,
                    "clean_status": clean_status,
                    "profile": profile,
                    "base": base,
                }
            )
        except Exception as exc:  # noqa: BLE001
            stats["failed"] += 1
            stats["errors"].append({"fileId": file_id, "message": str(exc)[:200]})
    return plans, stats


async def _persist_preview_payloads(payload_by_id: dict[str, dict[str, Any]]) -> None:
    from sqlalchemy import select

    from app.models import async_session
    from app.models.materials import RawFile

    wanted_ids = [raw_id for raw_id in (_raw_numeric_id(file_id) for file_id in payload_by_id) if raw_id]
    if not wanted_ids:
        return

    async with async_session() as session:
        result = await session.execute(select(RawFile).where(RawFile.id.in_(wanted_ids)))
        raw_items = list(result.scalars().all())
        for raw in raw_items:
            file_id = f"RAW-{int(raw.id):04d}"
            payload = payload_by_id.get(file_id)
            if not isinstance(payload, dict):
                continue
            ext_fields = dict(raw.ext_fields or {})
            ext_fields[PREVIEW_EXT_FIELD] = payload
            raw.ext_fields = ext_fields
        await session.commit()


def _compute_batch_preview_payloads(plans: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    from app.services.opencode_client import OpencodeClient

    out: dict[str, dict[str, Any]] = {}
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
                for plan in plans
            ]
        )
        result = client.send_text_prompt("技术标素材预览", prompt)
        previews = parse_batch_preview_reply(str(result.get("reply") or ""), OpencodeClient._parse_json_payload)
        model = str(result.get("modelId") or "")
    except Exception as exc:  # noqa: BLE001
        for plan in plans:
            out[plan["fileId"]] = _fallback_payload(plan, str(exc)[:200])
        return out

    for plan in plans:
        preview = previews.get(plan["fileId"])
        if preview:
            out[plan["fileId"]] = {
                **plan["base"],
                "status": "completed",
                "skipReason": "",
                "model": model,
                "metadata": {"cleanStatus": str(plan.get("clean_status") or "")},
                "preview": preview,
            }
        else:
            out[plan["fileId"]] = _fallback_payload(plan, "LLM 批量回复缺该文件或无效")
    return out


def _apply_preview_payloads(index_payload: dict[str, Any], payload_by_id: dict[str, dict[str, Any]]) -> None:
    for tier in index_payload.get("tiers") or []:
        for folder in tier.get("folders") or []:
            for file_item in folder.get("files") or []:
                file_id = str(file_item.get("id") or "")
                payload = payload_by_id.get(file_id)
                if not isinstance(payload, dict):
                    continue
                preview = payload.get("preview")
                if payload.get("status") in {"completed", "fallback"} and isinstance(preview, dict) and preview:
                    file_item["preview"] = preview
                else:
                    file_item.pop("preview", None)
                evidence_segments = payload.get("evidenceSegments")
                if isinstance(evidence_segments, list) and evidence_segments:
                    file_item["evidenceSegments"] = evidence_segments
                else:
                    file_item.pop("evidenceSegments", None)


async def enrich_technical_wiki_previews(index_payload: dict[str, Any]) -> dict[str, Any]:
    """增量生成/复用文件内容预览，并把成功预览写回传入 index payload。"""
    index_files = _iter_index_files(index_payload)
    plans, stats = await _build_preview_plans(index_files)
    stats.setdefault("fallback", 0)
    stats.setdefault("errors", [])
    pending = [plan for plan in plans if not plan.get("hit") and not plan.get("payload")]
    payload_by_id = {
        plan["fileId"]: plan["payload"]
        for plan in plans
        if isinstance(plan.get("payload"), dict)
    }
    payload_by_id.update(
        {
            plan["fileId"]: plan["payload"]
            for plan in plans
            if plan.get("hit") and isinstance(plan.get("payload"), dict)
        }
    )

    sem = asyncio.Semaphore(PREVIEW_CONCURRENCY)
    batches = [pending[i : i + PREVIEW_BATCH_SIZE] for i in range(0, len(pending), PREVIEW_BATCH_SIZE)]

    async def run_batch(batch: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        async with sem:
            return await asyncio.to_thread(_compute_batch_preview_payloads, batch)

    if batches:
        for result_map in await asyncio.gather(*[run_batch(batch) for batch in batches]):
            payload_by_id.update(result_map)

    for file_id, payload in payload_by_id.items():
        status = payload.get("status") if isinstance(payload, dict) else ""
        if status == "completed":
            stats["completed"] += 1
        elif status == "fallback":
            stats["fallback"] += 1
            reason = str(payload.get("skipReason") or "")
            if reason:
                stats["errors"].append({"fileId": file_id, "message": reason[:200]})
        elif status == "failed":
            stats["failed"] += 1
            stats["errors"].append({"fileId": file_id, "message": str(payload.get("skipReason") or "")[:200]})

    if payload_by_id:
        try:
            await _persist_preview_payloads(payload_by_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("technical wiki preview cache persist failed", exc_info=True)
            stats["failed"] += 1
            stats["errors"].append({"fileId": "", "message": f"预览缓存写回失败：{exc}"[:200]})

    _apply_preview_payloads(index_payload, payload_by_id)
    stats["errors"] = stats["errors"][:20]
    stats["enabled"] = True
    stats["batchCount"] = len(batches)
    logger.info("technical wiki preview: %s", stats)
    return stats
