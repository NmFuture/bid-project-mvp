"""商务标 Wiki 生成（LLM 精修主路径 + 多级确定性回退，独立于技术标）。

本模块是从原 `wiki_generation.py` 中商务标这条线整体搬迁而来，**行为保持不变**：

    LLM 精修（opencode 调 wikibuild 产骨架后语义精修）
      → 失败回退：subprocess 跑 bid-business-wiki-material-builder 脚本（确定性骨架）
      → 再失败回退（仅在显式允许时）：内联确定性蓝图

依赖素材清单（_summarize_material_inventory）、OCR、docx 解析等商务标专属逻辑，
与技术标的三级目录镜像链路完全解耦。
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import re
import tempfile
import zipfile
from collections import Counter
from io import BytesIO
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import BASE_DIR, settings
from app.models import async_session
from app.models.materials import RawFile, RawFolder
from app.services.bid_type import BUSINESS_BID_TYPE, GENERAL_BID_TYPE, TECHNICAL_BID_TYPE
from app.services.business_material_store import business_material_store
from app.services.business_wiki_blueprint import build_business_wiki_blueprint
from app.services.identity import canonical_customer, classify_material_path, material_identity
from app.services.material_cleaned_artifact import cleaned_artifact_is_current
from app.services.material_deep_parse import (
    deep_parse_profile_for,
    deep_parse_status_allows_enqueue,
    enqueue_deep_parse_job,
)
from app.services.material_tags import normalize_material_tags
from app.services.material_cleaning import is_cleanable_material
from app.services.material_taxonomy import infer_business_material_category, infer_business_material_subcategory
from app.services.minio_client import minio_client
from app.services.ocr_service import IMAGE_SUFFIXES, ocr_service
from app.services.opencode_client import OpencodeClient
from app.services.peripheral import PeripheralError
from app.services.wiki_blueprint_common import (
    MAX_SYNC_DOCX_BYTES,
    extract_docx_profile as _extract_docx_profile,
    format_heading_tree as _format_heading_tree,
    load_wiki_blueprint_result,
    material_level_range as _material_level_range,
    normalize_blueprint,
    now_iso,
    run_local_wiki_skill,
)

DEFAULT_REFERENCE_WIKI_PATH = Path(
    "/Users/anbocheng/Desktop/20260412_技术标/20260413_技术标_组织优化/素材库-20260413-wlb-clean-wiki/wiki"
)
BUSINESS_WIKI_OCR_VERSION = 1
# 商务标 Wiki 素材 OCR 并发度：单素材失败已在 _ensure_business_wiki_ocr_cache 内部隔离，
# 这里只控制同时进行 OCR 的素材数量，风格对齐技术标 PREVIEW_CONCURRENCY。
BUSINESS_WIKI_OCR_CONCURRENCY = 8
OCR_IMAGE_EXTS = {item.lstrip(".") for item in IMAGE_SUFFIXES}
OCR_SOURCE_EXTS = OCR_IMAGE_EXTS

BUSINESS_WIKI_SKILL_NAME = "bid-business-wiki-material-builder"
BUSINESS_WIKI_RUNNER = (
    BASE_DIR / "opencode" / "skills" / BUSINESS_WIKI_SKILL_NAME / "scripts" / "run_from_manifest.py"
)
BUSINESS_WIKI_ROOT_TITLE = f"{BUSINESS_BID_TYPE}Wiki（自动生成）"


def _read_excerpt(path: Path) -> str:
    if not path.exists():
        return ""
    # 全量读取：index/rules/synonyms/skeleton 是 Wiki 蓝图生成的核心参考，不再截断。
    return path.read_text(encoding="utf-8").strip()


def _summarize_reference_wiki(reference_root: Path) -> dict[str, Any]:
    card_root = reference_root / "卡片"
    common_dirs = []
    custom_dirs = []
    if card_root.exists():
        common_root = card_root / "通用"
        custom_root = card_root / "定制"
        if common_root.exists():
            common_dirs = sorted([item.name for item in common_root.iterdir() if item.is_dir()])
        if custom_root.exists():
            custom_dirs = sorted([item.name for item in custom_root.iterdir() if item.is_dir()])

    return {
        "referenceRoot": str(reference_root),
        "hasReference": reference_root.exists(),
        "indexExcerpt": _read_excerpt(reference_root / "index.md"),
        "rulesExcerpt": _read_excerpt(reference_root / "rules.md"),
        "synonymsExcerpt": _read_excerpt(reference_root / "synonyms.md"),
        "skeletonExcerpt": _read_excerpt(reference_root / "skeleton.md"),
        "commonCardGroups": common_dirs,
        "customCardGroups": custom_dirs,
    }


def _classify_material_group(folder_path: str, file_name: str) -> str:
    text = f"{folder_path}/{file_name}"
    if "标前概述" in text or "封面" in text or "评分" in text or "业绩" in text:
        return "标前概述"
    if "投标说明函" in text or "承诺函" in text or "函件" in text:
        return "投标函件"
    if "总体方案" in text or "供货范围" in text or "塔筒" in text:
        return "总体方案"
    if "交货" in text or "运输" in text or "安装" in text or "调试" in text or "运维" in text or "质量" in text or "技术支持" in text:
        return "设备全周期"
    if "风资源" in text or "机位" in text or "发电量" in text:
        return "风资源评估"
    if "叶片" in text or "齿轮箱" in text or "主轴" in text or "发电机" in text or "变流器" in text or "控制系统" in text or "偏航" in text or "变桨" in text or "制动" in text or "轮毂" in text or "机舱" in text or "液压" in text or "消防" in text or "视频监控" in text or "防雷系统" in text:
        return "风机子系统"
    if "低温" in text or "高温" in text or "潮湿" in text or "腐蚀" in text or "覆冰" in text or "风沙" in text or "紫外" in text or "绝缘" in text or "环境适应" in text:
        return "环境适应性"
    if "技术标准" in text or "标准" in text:
        return "技术标准"
    if "交付" in text or "验收" in text or "考核" in text:
        return "交付验收"
    return "专项技术"


def _classify_business_group(folder_path: str, file_name: str) -> str:
    text = f"{folder_path}/{file_name}"
    if "报价" in text or "分项报价" in text or "价格" in text or "清单" in text:
        return "报价与分项表"
    if "法定代表人" in text or "授权" in text or "委托" in text:
        return "法定代表人/授权"
    if "资格" in text or "资质" in text or "证书" in text or "营业执照" in text:
        return "资格资质"
    if "财务" in text or "审计" in text or "信用" in text or "银行" in text:
        return "财务与信用"
    if "业绩" in text or "合同" in text:
        return "业绩证明"
    if "商务偏差" in text or "偏差表" in text:
        return "商务偏差"
    if "合同条款" in text or "付款" in text or "质保" in text or "交付" in text:
        return "合同条款响应"
    if "承诺" in text or "函" in text:
        return "承诺函件"
    if "投标函" in text or "开标" in text:
        return "投标函与开标文件"
    return "商务通用"


TECH_CARD_GROUP_ORDER = [
    "标前概述",
    "投标函件",
    "总体方案",
    "设备全周期",
    "专项技术",
    "风资源评估",
    "风机子系统",
    "环境适应性",
    "技术标准",
    "交付验收",
    "项目数据",
]
BUSINESS_CARD_GROUP_ORDER = [
    "投标函与开标文件",
    "法定代表人/授权",
    "资格资质",
    "财务与信用",
    "业绩证明",
    "商务偏差",
    "合同条款响应",
    "承诺函件",
    "报价与分项表",
    "商务通用",
    "项目商务数据",
]
BUSINESS_FRAMEWORK_GROUPS = [
    "投标函与开标文件",
    "法定代表人/授权",
    "资格资质",
    "财务与信用",
    "业绩证明",
    "商务偏差",
    "合同条款响应",
    "承诺函件",
    "报价与分项表",
]


def _material_scope(folder_path: str, file_name: str, folder_tier: str = "") -> str:
    text = f"{folder_path}/{file_name}"
    if "投标资料库-通用" in text or "通用项目信息" in text or folder_tier == "standard":
        return "通用"
    if "客户素材" in text or "项目素材" in text or "客户定制" in text or folder_tier in {"customer", "project"}:
        return "定制"
    if "定制" in text or "招标文件" in text:
        return "定制"
    return "通用"


def _material_bid_type(folder_path: str, file_name: str, folder_bid_type: str = "") -> str:
    if folder_bid_type in {TECHNICAL_BID_TYPE, BUSINESS_BID_TYPE, GENERAL_BID_TYPE}:
        return folder_bid_type
    text = f"{folder_path}/{file_name}"
    if "商务标" in text or "商务" in text or "报价" in text or "开标" in text:
        return BUSINESS_BID_TYPE
    if "技术标" in text or "风资源" in text or "机组" in text or "风机" in text or "技术" in text:
        return TECHNICAL_BID_TYPE
    return GENERAL_BID_TYPE


def _docx_embedded_images(data: bytes) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            for name in sorted(archive.namelist()):
                if not name.startswith("word/media/"):
                    continue
                suffix = Path(name).suffix.lower()
                if suffix.lstrip(".") not in OCR_IMAGE_EXTS:
                    continue
                # 内嵌图片全量 OCR，不再只取前 N 张。
                images.append(
                    {
                        "name": name,
                        "fileName": Path(name).name,
                        "mimeType": mimetypes.guess_type(name)[0] or "image/png",
                        "content": archive.read(name),
                    }
                )
    except Exception:
        return []
    return images


def _ocr_cache_signature(item: RawFile) -> dict[str, Any]:
    ext = item.ext_fields or {}
    return {
        "version": int(item.version or 0),
        "sourceMinioKey": str(item.minio_key or ""),
        "sourceSizeBytes": int(item.size_bytes or 0),
        "cleanedMinioKey": str(ext.get("cleanedMinioKey") or ""),
        "cleanedSize": int(ext.get("cleanedSize") or 0),
    }


def _ocr_cache_is_fresh(payload: dict[str, Any], signature: dict[str, Any]) -> bool:
    return (
        isinstance(payload, dict)
        and int(payload.get("schemaVersion") or 0) == BUSINESS_WIKI_OCR_VERSION
        and payload.get("signature") == signature
        and str(payload.get("status") or "") != "failed"
    )


def _truncate_ocr_text(text: str) -> str:
    # OCR 文本全量入库（ext_fields.businessWikiOcr / profile.ocrText），不再截断；
    # 保留函数入口统一做空值归一化，避免调用方散落 str() 处理。
    return str(text or "").strip()


def _candidate_ocr_fields(text: str) -> dict[str, Any]:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    dates = []
    seen: set[str] = set()
    for token in re.findall(r"(?:20\d{2}|19\d{2})[年./-]\d{1,2}[月./-]\d{1,2}日?", clean):
        if token not in seen:
            seen.add(token)
            dates.append(token)
    doc_no = ""
    match = re.search(r"(?:编号|证书编号|文号|合同编号|No\.?|NO\.?)[:：\s]*([A-Za-z0-9\-_/]+)", clean, re.IGNORECASE)
    if match:
        doc_no = match.group(1).strip()
    issuer = ""
    match = re.search(r"(?:发证机构|签发单位|出具单位|认证机构|开户行|银行)[:：\s]*([^，。；;]{2,50})", clean)
    if match:
        issuer = match.group(1).strip()
    model_candidates = []
    for token in re.findall(r"\b[A-Z]{1,6}\d{2,6}(?:[-_/][A-Z0-9]{1,12}){0,4}\b", clean, re.IGNORECASE):
        normalized = token.strip()
        if normalized and normalized not in model_candidates:
            model_candidates.append(normalized)
    component_candidates = []
    for token in ("叶片", "齿轮箱", "发电机", "变流器", "主轴", "轮毂", "塔筒", "轴承", "偏航", "变桨", "大部件", "机型认证", "型式认证"):
        if token in clean and token not in component_candidates:
            component_candidates.append(token)
    return {
        "documentNumber": doc_no,
        "issuer": issuer,
        "issueDate": dates[0] if dates else "",
        "expiryDate": dates[1] if len(dates) > 1 else "",
        "dates": dates[:8],
        "turbineModels": model_candidates[:8],
        "components": component_candidates[:8],
    }


def _successful_ocr_payload(text: str, *, source_type: str, page_count: Any = 1, image_count: int = 0) -> dict[str, Any]:
    normalized = _truncate_ocr_text(text)
    return {
        "status": "completed" if normalized else "empty",
        "sourceType": source_type,
        "text": normalized,
        "fields": _candidate_ocr_fields(normalized),
        "pageCount": page_count,
        "imageCount": image_count,
        "confidence": "0.80" if normalized else "0.00",
        "updatedAt": now_iso(),
    }


def _failed_ocr_payload(message: str, *, source_type: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "sourceType": source_type,
        "text": "",
        "fields": {},
        "pageCount": 0,
        "imageCount": 0,
        "confidence": "0.00",
        "message": message,
        "updatedAt": now_iso(),
    }


async def _recognize_source_file_for_wiki(item: RawFile, source_ext: str) -> dict[str, Any]:
    bucket = str(item.minio_bucket or "")
    key = str(item.minio_key or "")
    data = await asyncio.to_thread(minio_client.get_object, bucket, key)
    text, raw = await ocr_service.recognize_text_for_parse(
        file_name=str(item.name or f"RAW-{int(item.id):04d}.{source_ext}"),
        content=data,
        mime_type=str(item.mime_type or mimetypes.guess_type(str(item.name or ""))[0] or ""),
    )
    return _successful_ocr_payload(
        text,
        source_type="source_file",
        page_count=(raw or {}).get("pageCount") or 1,
    )


async def _recognize_docx_embedded_images_for_wiki(item: RawFile, profile: dict[str, Any]) -> dict[str, Any]:
    bucket = str(profile.get("bucket") or item.minio_bucket or "")
    key = str(profile.get("minioKey") or item.minio_key or "")
    data = await asyncio.to_thread(minio_client.get_object, bucket, key)
    images = _docx_embedded_images(data)
    if not images:
        return {
            "status": "not_required",
            "sourceType": "docx_embedded_images",
            "text": "",
            "fields": {},
            "pageCount": 0,
            "imageCount": 0,
            "confidence": "n/a",
            "updatedAt": now_iso(),
        }
    texts: list[str] = []
    for index, image in enumerate(images, start=1):
        text, _ = await ocr_service.recognize_text_for_parse(
            file_name=str(image.get("fileName") or f"embedded-{index}.png"),
            content=image["content"],
            mime_type=str(image.get("mimeType") or "image/png"),
        )
        if str(text or "").strip():
            texts.append(f"[embedded_image_{index} {image.get('fileName')}]\n{text}")
    return _successful_ocr_payload(
        "\n\n".join(texts),
        source_type="docx_embedded_images",
        page_count=0,
        image_count=len(images),
    )


async def _ensure_business_wiki_ocr_cache(item: RawFile, profile: dict[str, Any]) -> dict[str, Any]:
    ext_fields = dict(item.ext_fields or {})
    signature = _ocr_cache_signature(item)
    cached = ext_fields.get("businessWikiOcr") if isinstance(ext_fields.get("businessWikiOcr"), dict) else {}
    source_ext = str(profile.get("sourceExt") or "").lower()
    ext = str(profile.get("ext") or "").lower()
    cache_allowed = source_ext in OCR_SOURCE_EXTS or ext == "docx"
    if cache_allowed and _ocr_cache_is_fresh(cached, signature):
        return cached

    try:
        if source_ext in OCR_SOURCE_EXTS:
            payload = await _recognize_source_file_for_wiki(item, source_ext)
        elif ext == "docx":
            payload = await _recognize_docx_embedded_images_for_wiki(item, profile)
        else:
            payload = {
                "status": "not_required",
                "sourceType": "none",
                "text": "",
                "fields": {},
                "pageCount": 0,
                "imageCount": 0,
                "confidence": "n/a",
                "updatedAt": now_iso(),
            }
    except PeripheralError as exc:
        payload = _failed_ocr_payload(str(exc.detail), source_type="source_file" if source_ext in OCR_SOURCE_EXTS else "docx_embedded_images")
    except Exception as exc:  # pragma: no cover - OCR/provider availability varies.
        payload = _failed_ocr_payload(str(exc), source_type="source_file" if source_ext in OCR_SOURCE_EXTS else "docx_embedded_images")

    payload = {
        "schemaVersion": BUSINESS_WIKI_OCR_VERSION,
        "signature": signature,
        **payload,
    }
    ext_fields["businessWikiOcr"] = payload
    item.ext_fields = ext_fields
    return payload


def _apply_business_wiki_ocr_to_profile(profile: dict[str, Any], ocr_payload: dict[str, Any]) -> None:
    if not isinstance(ocr_payload, dict):
        return
    profile["businessWikiOcr"] = ocr_payload
    text = str(ocr_payload.get("text") or "").strip()
    fields = ocr_payload.get("fields") if isinstance(ocr_payload.get("fields"), dict) else {}
    if text:
        profile["ocrText"] = text
        profile.setdefault("paragraphs", [])
        existing = {str(item) for item in profile["paragraphs"]}
        for line in [line.strip() for line in text.splitlines() if line.strip()]:
            if line not in existing:
                # OCR 行全量并入段落，不截断单行长度。
                profile["paragraphs"].append(line)
                existing.add(line)
        profile["parseError"] = "" if profile.get("sourceExt") in OCR_SOURCE_EXTS else str(profile.get("parseError") or "")
    profile["ocrStatus"] = str(ocr_payload.get("status") or "")
    profile["ocrConfidence"] = str(ocr_payload.get("confidence") or "")
    profile["ocrSourceType"] = str(ocr_payload.get("sourceType") or "")
    profile["ocrFields"] = fields
    if fields:
        profile["documentNumber"] = str(fields.get("documentNumber") or "")
        profile["issuer"] = str(fields.get("issuer") or "")
        profile["issueDate"] = str(fields.get("issueDate") or "")
        profile["expiryDate"] = str(fields.get("expiryDate") or "")
        profile["turbineModels"] = list(fields.get("turbineModels") or [])[:8]
        profile["components"] = list(fields.get("components") or [])[:8]


def _infer_skeleton_section(material: dict[str, Any]) -> str:
    text = " / ".join(
        [
            str(material.get("path") or ""),
            str(material.get("title") or ""),
            " / ".join(str(item.get("title") or "") for item in material.get("headings") or []),
        ]
    )
    rules = [
        ("风资源评估、机组选型排布及发电量计算", ("风资源", "发电量", "机位", "排布", "机组选型")),
        ("投标机型与总体技术方案", ("总体方案", "供货范围", "投标机型", "机组参数")),
        ("风力发电机组关键部件", ("叶片", "齿轮箱", "主轴", "发电机", "变流器", "控制系统", "轮毂", "机舱")),
        ("环境适应性与可靠性", ("低温", "高温", "潮湿", "腐蚀", "覆冰", "风沙", "防雷", "绝缘")),
        ("交货、运输、安装与调试", ("交货", "运输", "安装", "调试", "吊装")),
        ("质量保证、验收与考核", ("质量", "验收", "考核", "质保", "试运行")),
        ("运维服务、培训与技术支持", ("运维", "培训", "服务", "技术支持", "备品备件")),
        ("技术标准和规范响应", ("技术标准", "标准", "规范", "偏差")),
        ("投标函件与承诺", ("投标说明函", "承诺函", "函件")),
        ("业绩、资质与标前概述", ("业绩", "资质", "封面", "评分", "标前")),
    ]
    for section, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return section
    return str(material.get("group") or "专项技术")


def _keyword_candidates(material: dict[str, Any]) -> list[str]:
    title = str(material.get("title") or "")
    text = f"{title} " + " ".join(str(item.get("title") or "") for item in material.get("headings") or [])
    keywords: list[str] = []
    domain_terms = [
        "风资源",
        "机组选型",
        "发电量",
        "机位",
        "排布",
        "总体方案",
        "供货范围",
        "叶片",
        "齿轮箱",
        "主轴",
        "发电机",
        "变流器",
        "控制系统",
        "低温",
        "高温",
        "腐蚀",
        "覆冰",
        "运输",
        "安装",
        "调试",
        "质量",
        "验收",
        "技术标准",
        "承诺函",
        "业绩",
    ]
    for term in domain_terms:
        if term in text and term not in keywords:
            keywords.append(term)
    clean_title = re.sub(r"^技术标[-_：:]*", "", title)
    clean_title = re.sub(r"(专题|方案|报告|情况|一览表|计算)$", "", clean_title).strip(" -_：:")
    if clean_title and clean_title not in keywords:
        keywords.insert(0, clean_title)
    return keywords[:8] or [title]


def _profile_raw_file(item: RawFile) -> dict[str, Any]:
    ext_fields = item.ext_fields or {}
    folder_path = item.folder.path if item.folder else ""
    folder_tier = str(item.folder.tier or "") if item.folder else ""
    folder_bid_type = str(item.folder.bid_type or "") if item.folder else ""
    file_name = str(item.name or "")
    source_ext = Path(file_name).suffix.lower().lstrip(".") or "file"
    cleaned_minio_key = (
        str(ext_fields.get("cleanedMinioKey") or "")
        if cleaned_artifact_is_current(int(getattr(item, "version", 1) or 1), ext_fields)
        else ""
    )
    cleaned_bucket = str(ext_fields.get("cleanedMinioBucket") or item.minio_bucket or "")
    cleaned_file_name = str(ext_fields.get("cleanedFileName") or "")
    tags = normalize_material_tags(ext_fields.get("tags"))
    clean_report = ext_fields.get("cleanReport") if isinstance(ext_fields.get("cleanReport"), dict) else {}
    clean_report_record = clean_report.get("record") if isinstance(clean_report.get("record"), dict) else {}
    has_cleaned_word = is_cleanable_material(file_name) and bool(cleaned_minio_key)
    ext = "docx" if source_ext == "docx" or has_cleaned_word else source_ext
    inferred_bid_type = _material_bid_type(folder_path, file_name, folder_bid_type)
    path_identity = classify_material_path(
        folder_path,
        str(ext_fields.get("bidType") or folder_bid_type or inferred_bid_type),
    )
    bid_type = str(ext_fields.get("bidType") or path_identity.get("bidType") or inferred_bid_type)
    scope = _material_scope(folder_path, file_name, folder_tier)
    material_tier = str(ext_fields.get("materialTier") or path_identity.get("materialTier") or folder_tier or "")
    if material_tier == "standard":
        scope = "通用"
    elif material_tier in {"customer", "project"}:
        scope = "定制"
    if bid_type == BUSINESS_BID_TYPE:
        material_category = str(ext_fields.get("materialCategory") or "") or infer_business_material_category(
            folder_path,
            file_name,
            material_tier,
        )
        material_subcategory = str(ext_fields.get("materialSubcategory") or "") or infer_business_material_subcategory(
            folder_path,
            file_name,
        )
        group = "项目商务数据" if scope == "定制" else _classify_business_group(folder_path, file_name)
    else:
        material_category = ""
        material_subcategory = ""
        group = "项目数据" if scope == "定制" else _classify_material_group(folder_path, file_name)
    path = f"{folder_path}/{file_name}".strip("/")
    identity = material_identity(
        material_tier=material_tier,
        bid_type=bid_type,
        customer_name=str(ext_fields.get("customerName") or path_identity.get("customerName") or ""),
        project_id=str(ext_fields.get("projectId") or path_identity.get("projectId") or ""),
        project_code=str(ext_fields.get("projectCode") or ext_fields.get("projectId") or path_identity.get("projectId") or ""),
        project_name=str(ext_fields.get("projectName") or ""),
    )
    identity.update(
        {
            key: ext_fields[key]
            for key in (
                "identityScope",
                "materialScope",
                "customerId",
                "customerCanonicalName",
                "customerAliases",
                "projectId",
                "projectCode",
                "projectName",
                "identityDisplay",
            )
            if key in ext_fields and ext_fields[key] not in (None, "")
        }
    )
    profile: dict[str, Any] = {
        "id": f"RAW-{int(item.id):04d}",
        "name": file_name,
        "title": Path(file_name).stem,
        "folderPath": folder_path,
        "path": path,
        "ext": ext,
        "sourceExt": source_ext,
        "tags": tags,
        "businessMaterialKind": str(ext_fields.get("businessMaterialKind") or ""),
        "businessMaterialKindLabel": str(ext_fields.get("businessMaterialKindLabel") or ""),
        "materialCategory": material_category,
        "materialCategoryLabel": str(ext_fields.get("materialCategoryLabel") or ""),
        "materialSubcategory": material_subcategory,
        "hasCleanedWord": has_cleaned_word,
        "cleanStatus": str(ext_fields.get("cleanStatus") or ""),
        "cleanMessage": str(ext_fields.get("cleanMessage") or ""),
        "cleanUpdatedAt": str(ext_fields.get("cleanUpdatedAt") or ""),
        "cleanResultStatus": str(ext_fields.get("cleanResultStatus") or ""),
        "cleanError": str(ext_fields.get("cleanError") or ""),
        "cleanNeedsHumanReview": bool(ext_fields.get("cleanNeedsHumanReview")),
        "cleanUsableForRetrieval": bool(ext_fields.get("cleanUsableForRetrieval", has_cleaned_word)),
        "cleanRelativeSourcePath": str(ext_fields.get("cleanRelativeSourcePath") or clean_report_record.get("relativeSourcePath") or ""),
        "cleanRelativeOutputPath": str(ext_fields.get("cleanRelativeOutputPath") or clean_report_record.get("relativeOutputPath") or ""),
        "cleanReport": clean_report,
        "cleanedFileName": cleaned_file_name,
        "cleanedMinioBucket": cleaned_bucket,
        "cleanedMinioKey": cleaned_minio_key,
        "bidType": bid_type,
        "scope": scope,
        "materialTier": material_tier,
        "identityScope": identity.get("identityScope") or ("general" if scope == "通用" else "project"),
        "materialScope": identity.get("materialScope") or ("general" if scope == "通用" else "project"),
        "identityDisplay": identity.get("identityDisplay") or "",
        "customerName": str(ext_fields.get("customerName") or path_identity.get("customerName") or ""),
        "customerId": identity.get("customerId") or "",
        "customerCanonicalName": identity.get("customerCanonicalName") or "",
        "customerAliases": identity.get("customerAliases") or [],
        "projectId": identity.get("projectId") or "",
        "projectCode": identity.get("projectCode") or "",
        "projectName": identity.get("projectName") or "",
        "group": group,
        "folderTier": folder_tier,
        "bucket": cleaned_bucket if has_cleaned_word else item.minio_bucket,
        "minioKey": cleaned_minio_key if has_cleaned_word else item.minio_key,
        "sourceBucket": item.minio_bucket,
        "sourceMinioKey": item.minio_key,
        "sizeBytes": int(item.size_bytes or 0),
        "headings": [],
        "paragraphs": [],
        "tables": [],
        "tableCount": 0,
        "parseError": "",
    }
    parse_size = int(ext_fields.get("cleanedSize") or item.size_bytes or 0) if has_cleaned_word else int(item.size_bytes or 0)
    if ext == "docx":
        # 后台深度解析产物优先：sourceKey 与当前 cleaned/原始对象一致时直接采用
        deep_profile = deep_parse_profile_for(
            ext_fields,
            cleaned_minio_key or str(item.minio_key or ""),
        )
        if deep_profile is not None:
            profile.update({**deep_profile, "parseError": ""})
        elif parse_size > MAX_SYNC_DOCX_BYTES:
            size_mb = parse_size / 1024 / 1024
            if deep_parse_status_allows_enqueue(ext_fields):
                enqueue_deep_parse_job(str(profile["id"]))
            profile["parseError"] = (
                f"文件 {size_mb:.1f}MB，超过同步解析上限 30MB；"
                "已排队后台深度解析，完成后自动补充 Heading 和正文摘录。"
            )
            profile["deepParsePending"] = True
        else:
            try:
                data = minio_client.get_object(str(profile["bucket"]), str(profile["minioKey"]))
                profile.update(_extract_docx_profile(data))
            except Exception as exc:  # pragma: no cover - depends on object store state
                profile["parseError"] = f"MinIO 读取失败：{exc}"
    else:
        profile["parseError"] = "非 docx 文件，未进入 Wiki 卡片正文解析"

    profile["headingCount"] = len(profile["headings"])
    profile["materialLevelRange"] = _material_level_range(profile["headings"])
    profile["skeletonSection"] = _infer_skeleton_section(profile)
    profile["keywords"] = _keyword_candidates(profile)
    return profile


async def _summarize_material_inventory() -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    groups: dict[str, list[str]] = {}
    custom_items: list[str] = []
    parsed_count = 0

    async with async_session() as session:
        # 商务标 Wiki 只需商务/通用素材：SQL 侧尽早排除「明确标为技术标」的文件夹，
        # 避免全库扫描；folder.bid_type 为空的文件保留，交给 _profile_raw_file 按路径推断，
        # 不改变原有归类结果。
        result = await session.execute(
            select(RawFile)
            .join(RawFolder, RawFile.folder_id == RawFolder.id)
            .where(
                (RawFolder.bid_type.is_(None)) | (RawFolder.bid_type != TECHNICAL_BID_TYPE)
            )
            .options(selectinload(RawFile.folder))
        )
        files = result.scalars().all()
        business_materials: list[tuple[RawFile, dict[str, Any]]] = []
        for item in files:
            material = _profile_raw_file(item)
            if material.get("bidType") == BUSINESS_BID_TYPE:
                business_materials.append((item, material))
            items.append(material)
            groups.setdefault(f"{material['bidType']}/{material['scope']}/{material['group']}", []).append(material["name"])
            if material["scope"] == "定制":
                custom_items.append(material["name"])
            if material["ext"] == "docx" and not material.get("parseError"):
                parsed_count += 1
        ocr_dirty = bool(business_materials)
        if business_materials:
            # 并发执行 OCR；单素材失败已在 _ensure_business_wiki_ocr_cache 内部转成
            # failed 缓存并继续，不阻断其他素材。
            semaphore = asyncio.Semaphore(BUSINESS_WIKI_OCR_CONCURRENCY)

            async def _apply_ocr(item: RawFile, material: dict[str, Any]) -> None:
                async with semaphore:
                    ocr_payload = await _ensure_business_wiki_ocr_cache(item, material)
                _apply_business_wiki_ocr_to_profile(material, ocr_payload)

            await asyncio.gather(*[_apply_ocr(item, material) for item, material in business_materials])
        # 仅在确有 OCR 缓存写回时提交，避免无谓写库。
        if ocr_dirty:
            await session.commit()

    return {
        "total": len(items),
        "docxTotal": sum(1 for item in items if item["ext"] == "docx"),
        "parsedDocxTotal": parsed_count,
        "groups": {key: sorted(value) for key, value in sorted(groups.items())},
        "items": sorted(items, key=lambda item: (item["scope"], item["group"], item["name"])),
        "customItems": sorted(custom_items),
    }


def _filter_inventory_for_bid_type(inventory: dict[str, Any], bid_type: str) -> dict[str, Any]:
    materials = [
        item
        for item in (inventory.get("items") or [])
        if isinstance(item, dict) and _matches_bid_type(item, bid_type)
    ]
    groups: dict[str, list[str]] = {}
    custom_items: list[str] = []
    parsed_count = 0
    for item in materials:
        groups.setdefault(f"{item.get('bidType')}/{item.get('scope')}/{item.get('group')}", []).append(str(item.get("name") or ""))
        if item.get("scope") == "定制":
            custom_items.append(str(item.get("name") or ""))
        if item.get("ext") == "docx" and not item.get("parseError"):
            parsed_count += 1
    return {
        "total": len(materials),
        "docxTotal": sum(1 for item in materials if item.get("ext") == "docx"),
        "parsedDocxTotal": parsed_count,
        "groups": {key: sorted(value) for key, value in sorted(groups.items())},
        "items": sorted(materials, key=lambda item: (str(item.get("scope")), str(item.get("group")), str(item.get("name")))),
        "customItems": sorted(custom_items),
        "sourceInventoryTotal": inventory.get("total", 0),
        "bidType": bid_type,
    }


def _compact_material_for_manifest(material: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "id",
        "name",
        "title",
        "folderPath",
        "path",
        "ext",
        "sourceExt",
        "hasCleanedWord",
        "cleanedFileName",
        "bidType",
        "scope",
        "materialTier",
        "identityScope",
        "materialScope",
        "identityDisplay",
        "customerName",
        "customerId",
        "customerCanonicalName",
        "customerAliases",
        "projectId",
        "projectCode",
        "projectName",
        "group",
        "headings",
        "paragraphs",
        "tables",
        "tableCount",
        "parseError",
        "headingCount",
        "materialLevelRange",
        "skeletonSection",
        "keywords",
        "ocrStatus",
        "ocrConfidence",
        "ocrSourceType",
        "ocrText",
        "ocrFields",
        "businessWikiOcr",
        "documentNumber",
        "issuer",
        "issueDate",
        "expiryDate",
        "turbineModels",
        "components",
    ]
    compact = {key: material.get(key) for key in keys if key in material}
    # manifest 压缩层已放开：headings/paragraphs/tables 全量喂给 Wiki 构建 skill。
    compact["headings"] = list(material.get("headings") or [])
    compact["paragraphs"] = list(material.get("paragraphs") or [])
    compact["tables"] = list(material.get("tables") or [])
    return compact


def _build_wiki_manifest(reference: dict[str, Any], material_inventory: dict[str, Any], bid_type: str) -> dict[str, Any]:
    compact_inventory = dict(material_inventory)
    compact_inventory["items"] = [
        _compact_material_for_manifest(item)
        for item in (material_inventory.get("items") or [])
        if isinstance(item, dict)
    ]
    return {
        "referenceWiki": {
            "hasReference": bool(reference.get("hasReference")),
            "commonCardGroups": reference.get("commonCardGroups") or [],
            "customCardGroups": reference.get("customCardGroups") or [],
        },
        "materialInventory": compact_inventory,
        "targetBidType": bid_type,
        "targetSkill": BUSINESS_WIKI_SKILL_NAME,
        "rootTitle": BUSINESS_WIKI_ROOT_TITLE,
        "workDir": "",
        "outputFile": "",
    }


def _write_wiki_manifest(reference: dict[str, Any], material_inventory: dict[str, Any], bid_type: str) -> Path:
    shared_root = settings.parsed_dir / "_wiki_build"
    shared_root.mkdir(parents=True, exist_ok=True)
    target_dir = Path(tempfile.mkdtemp(prefix="bid-wiki-build-", dir=shared_root))
    manifest_path = target_dir / "wiki_build_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                **_build_wiki_manifest(reference, material_inventory, bid_type),
                "workDir": str(target_dir),
                "outputFile": str(target_dir / "wiki_blueprint.json"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return manifest_path


def _build_wiki_refine_prompt(skill_name: str, manifest_path: Path, bid_type: str) -> str:
    """脚本产骨架 + LLM 精修：先用 wikibuild 生成确定性骨架，再在骨架上做语义增强。"""
    return f"""
Use the {skill_name} skill.

这是「脚本产骨架 + LLM 精修」流程，分两步，必须按顺序完成：

## 第一步：调用 wikibuild 生成确定性骨架
直接调用一次 Bash 工具执行下面命令，Bash 工具 timeout 必须设置为 1800000 毫秒或更高。不要先检查工作目录，不要先执行 pwd/ls/cat，不要拆成多条命令，不要改写命令或路径：

```bash
wikibuild {manifest_path}
```

命令会把确定性 `{bid_type}` Wiki 骨架写入 outputFile（路径在 stdout 的 JSON 里），并保证：五个一级节点齐全、素材不遗漏不重复、模块映射固定、绝不编造金额/承诺/证书编号。

## 第二步：在骨架上做语义精修
读取 outputFile 后，在**不破坏结构、不编造事实**的前提下增强：
1. 修正脚本规则误判的 business_category / evidence_topic / usage_mode。
2. 补全脚本留空或标「待识别」「待映射」的语义字段（关键词、适用章节、摘要）。
3. 复核脚本标 needs_human_confirm=yes、validity_status=pending_verify 的项，让 risk_notes 更聚焦，便于人工复核。
4. 映射表 candidate_card_ids 为空但确有合适素材时，按 fallback_scope 给出更精准的候选。

铁律：精修只能改「判断/描述」，不能改「事实」。inventory 里从未出现过的价格、日期、证书编号、授权人、业绩数据一律不得新增；找不到就保持 pending 并写进待确认清单。issue_date/expiry_date/document_number/issuer 等正则抽取字段是提示性的，不要当成已核实事实对外承诺。

## 输出
把精修后的完整 blueprint（保持骨架的 nodes 结构与五节点顺序）写回 outputFile，然后只返回 stdout 中含 outputFile 的 JSON，不要解释，不要 Markdown 代码块。
""".strip()


def _escape_table_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", "<br>")


def _first_heading_titles(material: dict[str, Any], limit: int = 5) -> str:
    headings = material.get("headings") or []
    if not headings:
        return "未检测到 Heading"
    return "；".join(str(item.get("title") or "") for item in headings[:limit])


def _render_material_card(material: dict[str, Any]) -> str:
    title = str(material.get("title") or material.get("name") or "未命名素材")
    headings = material.get("headings") or []
    paragraphs = material.get("paragraphs") or []
    tables = material.get("tables") or []
    keywords = material.get("keywords") or [title]
    parse_error = str(material.get("parseError") or "")
    skeleton_section = str(material.get("skeletonSection") or material.get("group") or "未明确")
    material_level_range = str(material.get("materialLevelRange") or "none")
    heading_count = int(material.get("headingCount") or 0)
    aliases = material.get("customerAliases") or []
    alias_text = "、".join(str(item) for item in aliases if str(item).strip())
    identity_scope = str(material.get("identityScope") or "general")

    lines = [
        f"# {title}",
        "",
        "## 素材来源",
        f"- 原始文件：`{material.get('path')}`",
        f"- 文件编号：`{material.get('id')}`",
        f"- 素材范围：{material.get('scope')} / {material.get('group')}",
        f"- 文件类型：{material.get('sourceExt') or material.get('ext')}",
        f"- 清洗后 Word：{material.get('cleanedFileName') or ('原始文件即 Word' if material.get('ext') == 'docx' else '')}",
        "",
        "## AI 检索身份",
        f"- identity_scope: {identity_scope}",
        f"- bid_type: {material.get('bidType')}",
        f"- customer_id: {material.get('customerId') or ''}",
        f"- customer_name: {material.get('customerCanonicalName') or material.get('customerName') or ''}",
        f"- customer_aliases: {alias_text}",
        f"- project_id: {material.get('projectId') or ''}",
        f"- project_code: {material.get('projectCode') or ''}",
        f"- identity_display: {material.get('identityDisplay') or ''}",
        "",
        "## 该填进什么章节",
        f"- 主关键词：{'、'.join(str(item) for item in keywords)}",
        f"- 典型父章节：{skeleton_section}",
        f"- 推荐用途：作为“{skeleton_section}”章节的正文素材、表格依据或技术附件说明。",
        "",
        "## 文档结构审计",
        f"- Heading 数量：{heading_count}",
        f"- 素材内部层级：{material_level_range}",
        f"- 表格数量：{material.get('tableCount') or 0}",
        "",
        "### Heading 树",
        _format_heading_tree(headings),
        "",
        "## 内容摘要（来自原始 docx）",
    ]

    if paragraphs:
        # 段落已全量读取，卡片正文同样全量写入，不再只取前 N 段。
        for item in paragraphs:
            lines.append(f"- {item}")
    elif parse_error:
        lines.append(f"- {parse_error}")
    else:
        lines.append("- 未抽取到普通正文段落；请检查 Word 段落样式或是否主要由表格组成。")

    if tables:
        lines.extend(["", "## 表格预览（来自原始 docx）"])
        # 表格全量写入卡片正文，不再只取前 N 张。
        for item in tables:
            lines.append(f"- {item}")

    lines.extend(
        [
            "",
            "## 适用条件",
            f"- 触发条件：目录或评分点命中“{' / '.join(str(item) for item in keywords)}”时优先引用。",
            "- 项目素材优先级高于通用素材；同章节同时命中时采用 override / append / reference 规则裁决。",
            "- 若招标文件要求明确技术响应、计算依据或附件证明，应保留原始 docx 作为证据来源。",
            "",
            "## 关联素材",
            f"- `{material.get('path')}`",
            "",
            "## 可替换字段",
            "- 项目名称、业主名称、场址、机型、容量、台数、坐标、发电量、交货期等以项目解析结果覆盖。",
            "",
            "## Merge 信息",
            f"- path: {material.get('path')}",
            f"- material_id: {material.get('id')}",
            f"- scope: {material.get('scope')}",
            f"- category: {material.get('group')}",
            f"- identity_scope: {identity_scope}",
            f"- material_scope: {material.get('materialScope') or identity_scope}",
            f"- bid_type: {material.get('bidType')}",
            f"- customer_id: {material.get('customerId') or ''}",
            f"- customer_name: {material.get('customerCanonicalName') or material.get('customerName') or ''}",
            f"- customer_aliases: {alias_text}",
            f"- project_id: {material.get('projectId') or ''}",
            f"- project_code: {material.get('projectCode') or ''}",
            f"- cleaned_file_name: {material.get('cleanedFileName') or ''}",
            f"- skeleton_section: {skeleton_section}",
            "- skeleton_level: section",
            f"- material_level_range: {material_level_range}",
            f"- heading_count: {heading_count}",
            "- shift: 0",
            "- attach_mode: normal",
        ]
    )
    if parse_error:
        lines.extend(["", "## 解析状态", f"- {parse_error}"])
    return "\n".join(lines).strip() + "\n"


def _material_card_node(material: dict[str, Any]) -> dict[str, Any]:
    scope = str(material.get("scope") or "通用")
    bid_type = str(material.get("bidType") or "通用")
    return {
        "title": str(material.get("title") or material.get("name") or "未命名素材"),
        "markdownContent": _render_material_card(material),
        "tags": ["素材卡片", bid_type, scope, str(material.get("group") or "")],
        "applicableTypes": ["通用", bid_type] if scope == "通用" else [bid_type],
        "children": [],
    }


def _matches_bid_type(material: dict[str, Any], bid_type: str) -> bool:
    material_bid_type = str(material.get("bidType") or "").strip()
    if not material_bid_type:
        path_text = " ".join(
            str(material.get(key) or "")
            for key in ("path", "folderPath", "name", "title")
        )
        folder_tier = str(material.get("materialTier") or "").strip().lower()
        identity_scope = str(material.get("identityScope") or "").strip().lower()
        if (
            any(keyword in path_text for keyword in ("通用素材", "客户素材", "项目素材"))
            and (folder_tier in {"standard", "customer", "project"} or identity_scope in {"general", "customer", "project"})
        ):
            material_bid_type = bid_type
        elif any(keyword in path_text for keyword in ("商务标", "商务", "报价", "开标", "投标函", "授权", "偏差", "保证金")):
            material_bid_type = BUSINESS_BID_TYPE
        elif any(keyword in path_text for keyword in ("技术标", "技术", "风机", "机组", "风资源")):
            material_bid_type = TECHNICAL_BID_TYPE
        else:
            material_bid_type = GENERAL_BID_TYPE
    if bid_type == BUSINESS_BID_TYPE:
        return material_bid_type == BUSINESS_BID_TYPE
    return material_bid_type == bid_type or material_bid_type == GENERAL_BID_TYPE


def _group_material_nodes(materials: list[dict[str, Any]], scope: str, bid_type: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for material in materials:
        if material.get("scope") != scope or material.get("ext") != "docx" or not _matches_bid_type(material, bid_type):
            continue
        grouped.setdefault(str(material.get("group") or "专项技术"), []).append(material)
    order = BUSINESS_CARD_GROUP_ORDER if bid_type == BUSINESS_BID_TYPE else TECH_CARD_GROUP_ORDER
    rank = {name: index for index, name in enumerate(order)}
    children: list[dict[str, Any]] = []
    for group, group_items in sorted(grouped.items(), key=lambda item: (rank.get(item[0], 99), item[0])):
        group_items = sorted(group_items, key=lambda item: str(item.get("title") or ""))
        children.append(
            {
                "title": group,
                "markdownContent": (
                    f"# {group}\n\n"
                    f"本组由 {len(group_items)} 份 `{scope}` docx 素材生成。"
                    "每张卡片均保留原始文件路径、Heading 审计、正文摘录和 Merge 信息。"
                ),
                "tags": ["素材分组", scope, group],
                "applicableTypes": ["通用", bid_type] if scope == "通用" else [bid_type],
                "children": [_material_card_node(material) for material in group_items],
            }
        )
    return children


def _render_framework_card_groups(groups: list[str], bid_type: str, scope: str = "通用") -> list[dict[str, Any]]:
    return [
        {
            "title": group,
            "markdownContent": (
                f"# {group}\n\n"
                f"当前素材库尚未检出 `{bid_type}` 的 `{group}` docx。该节点作为补料占位，"
                "后续上传对应素材后会生成真实卡片。"
            ),
            "tags": ["待补料", bid_type, scope, group],
            "applicableTypes": [bid_type],
            "children": [],
        }
        for group in groups
    ]


def _filtered_docx_materials(materials: list[dict[str, Any]], bid_type: str) -> list[dict[str, Any]]:
    return [item for item in materials if item.get("ext") == "docx" and _matches_bid_type(item, bid_type)]


def _identity_label(material: dict[str, Any]) -> str:
    scope = str(material.get("identityScope") or "general")
    if scope == "customer":
        return f"客户:{material.get('customerCanonicalName') or material.get('customerName') or '未命名客户'}"
    if scope == "project":
        return f"项目:{material.get('projectCode') or material.get('projectId') or '未命名项目'}"
    return "通用"


def _render_index_markdown(materials: list[dict[str, Any]], inventory: dict[str, Any], bid_type: str) -> str:
    filtered = _filtered_docx_materials(materials, bid_type)
    lines = [
        f"# {bid_type}素材速查索引（{len(filtered)} 份 docx）",
        "",
        f"- 原始材料总数：{inventory.get('total', 0)}",
        f"- 本体系 docx 数量：{len(filtered)}",
        f"- 全库成功解析 docx：{inventory.get('parsedDocxTotal', 0)}",
        "",
        "| 素材 | AI身份 | 范围/分类 | 推荐章节 | Heading | 内容线索 | 原始路径 |",
        "|---|---|---|---|---:|---|---|",
    ]
    if not filtered:
        lines.extend(
            [
                "| 待补料 | - | - | - | 0 | 当前素材库未检出该标类素材 | - |",
                "",
                "## 待补料建议",
                "- 上传 docx 后重新执行“创建Wiki”。",
                "- 文件名或目录建议包含标类关键词，例如：商务标、报价、授权、资质、合同条款响应。",
            ]
        )
        return "\n".join(lines) + "\n"
    for material in filtered:
        lines.append(
            "| {title} | {identity} | {scope}/{group} | {section} | {count} | {heading} | `{path}` |".format(
                title=_escape_table_cell(material.get("title")),
                identity=_escape_table_cell(_identity_label(material)),
                scope=_escape_table_cell(material.get("scope")),
                group=_escape_table_cell(material.get("group")),
                section=_escape_table_cell(material.get("skeletonSection")),
                count=int(material.get("headingCount") or 0),
                heading=_escape_table_cell(_first_heading_titles(material)),
                path=_escape_table_cell(material.get("path")),
            )
        )
    return "\n".join(lines) + "\n"


def _render_skeleton_markdown(materials: list[dict[str, Any]], bid_type: str) -> str:
    by_section: dict[str, list[dict[str, Any]]] = {}
    for material in materials:
        if material.get("ext") == "docx" and _matches_bid_type(material, bid_type):
            by_section.setdefault(str(material.get("skeletonSection") or "未明确"), []).append(material)
    lines = [
        f"# {bid_type}目录骨架与素材挂载",
        "",
        "本页是平台 Wiki 的 merge 真源草案。每个章节下面列出可挂载的原始 docx，并标明 AI 身份、素材内部 Heading 层级。",
    ]
    if not by_section and bid_type == BUSINESS_BID_TYPE:
        lines.extend(
            [
                "",
                "## 商务标标准骨架（待补料）",
                "- 投标函与开标文件",
                "- 法定代表人身份证明与授权委托",
                "- 投标人资格资质证明",
                "- 财务与信用资料",
                "- 业绩证明材料",
                "- 商务偏差表",
                "- 合同条款响应",
                "- 商务承诺函件",
                "- 报价与分项报价表",
            ]
        )
        return "\n".join(lines) + "\n"
    for section, section_items in sorted(by_section.items()):
        lines.extend(["", f"## {section}"])
        for material in sorted(section_items, key=lambda item: str(item.get("title") or "")):
            lines.append(
                f"- merge 素材：`{material.get('path')}`；身份：{_identity_label(material)}；层级：{material.get('materialLevelRange')}；"
                f"Heading：{material.get('headingCount')}；模式：normal"
            )
    return "\n".join(lines) + "\n"


def _render_rules_markdown(materials: list[dict[str, Any]], bid_type: str) -> str:
    sections = Counter(
        str(material.get("skeletonSection") or "未明确")
        for material in materials
        if material.get("ext") == "docx" and _matches_bid_type(material, bid_type)
    )
    lines = [
        f"# {bid_type}装配规则",
        "",
        "## 全局裁决",
        "- 项目素材命中同一章节时，优先于通用素材；通用素材作为标准底稿。",
        "- 同一章节存在多个素材时，先按招标目录/评分点关键词匹配，再按素材 Heading 命中度排序。",
        "- 计算书、承诺函、表格类素材不改写事实数据，只做引用、摘录或附件挂载。",
        "- 未检测到 Heading 的素材按整篇挂载，并进入 Heading 审计清单。",
        "",
        "## AI 身份匹配",
        "- `identity_scope=general` 的通用素材可被同标类项目读取。",
        "- `identity_scope=customer` 的客户素材只有在项目 `customer_id` 或客户同义词命中时才能读取。",
        "- `identity_scope=project` 的项目素材只有在项目 `project_id` 或 `project_code` 命中时才能读取。",
        "- 身份不命中的素材不得进入目录建议，也不得作为正文拼装证据。",
        "",
        "## 章节素材覆盖面",
    ]
    if bid_type == BUSINESS_BID_TYPE:
        lines.extend(
            [
                "- 商务标优先保持表单、函件、证明材料原格式，不做事实改写。",
                "- 报价、保证金、授权、资质证书等材料只允许字段替换和附件挂载。",
                "- 缺商务标素材时，只生成待补料框架，不虚构商务卡片。",
            ]
        )
    for section, count in sections.most_common():
        lines.append(f"- {section}：{count} 份素材")
    return "\n".join(lines) + "\n"


def _render_synonyms_markdown(materials: list[dict[str, Any]], bid_type: str) -> str:
    keyword_map: dict[str, set[str]] = {}
    for material in materials:
        if material.get("ext") != "docx" or not _matches_bid_type(material, bid_type):
            continue
        title = str(material.get("title") or "")
        section = str(material.get("skeletonSection") or "")
        for keyword in material.get("keywords") or []:
            keyword_map.setdefault(str(keyword), set()).update({title, section})
    lines = [f"# {bid_type}同义词映射", "", "| 检索词 | 映射到 |", "|---|---|"]
    if bid_type == BUSINESS_BID_TYPE and not keyword_map:
        keyword_map = {
            "投标函": {"投标书", "开标文件"},
            "授权": {"法定代表人授权", "授权委托书"},
            "资格": {"资质", "资格证明"},
            "报价": {"投标报价", "分项报价表"},
            "商务偏差": {"偏差表", "商务响应"},
            "合同条款": {"合同响应", "付款条件"},
        }
    for keyword, values in sorted(keyword_map.items()):
        cleaned = sorted(value for value in values if value)
        lines.append(f"| {_escape_table_cell(keyword)} | {_escape_table_cell('、'.join(cleaned[:8]))} |")
    return "\n".join(lines) + "\n"


def _render_bid_type_overview(materials: list[dict[str, Any]], bid_type: str) -> str:
    filtered = _filtered_docx_materials(materials, bid_type)
    common_count = sum(1 for item in filtered if item.get("scope") == "通用")
    custom_count = sum(1 for item in filtered if item.get("scope") == "定制")
    parsed_count = sum(1 for item in filtered if not item.get("parseError"))
    return (
        f"# {bid_type}体系\n\n"
        f"`{bid_type}体系` 是一套独立的标书装配规则库，包含索引、骨架、规则、同义词和卡片。"
        "目录生成与正文拼装必须优先读取本体系下的规则真源。\n\n"
        "## 当前素材覆盖\n"
        f"- docx 素材：{len(filtered)}\n"
        f"- 通用卡片：{common_count}\n"
        f"- 定制卡片：{custom_count}\n"
        f"- 已解析内容：{parsed_count}\n\n"
        "## 使用顺序\n"
        "1. 先查素材速查索引。\n"
        "2. 再查同义词映射扩展关键词。\n"
        "3. 按装配规则做必选、条件触发、剔除、覆盖、叠加、附加裁决。\n"
        "4. 最后按目录骨架写入 assembly_plan。\n"
    )


def _build_bid_type_system_node(materials: list[dict[str, Any]], inventory: dict[str, Any], bid_type: str) -> dict[str, Any]:
    common_children = _group_material_nodes(materials, "通用", bid_type)
    custom_children = _group_material_nodes(materials, "定制", bid_type)
    if bid_type == BUSINESS_BID_TYPE and not common_children:
        common_children = _render_framework_card_groups(BUSINESS_FRAMEWORK_GROUPS, bid_type, "通用")
    if bid_type == BUSINESS_BID_TYPE and not custom_children:
        custom_children = _render_framework_card_groups(["项目商务数据", "业主专属承诺", "项目报价附件"], bid_type, "定制")
    return {
        "title": f"01-{bid_type}体系",
        "markdownContent": _render_bid_type_overview(materials, bid_type),
        "tags": [bid_type, "体系"],
        "applicableTypes": [bid_type],
        "children": [
            {
                "title": f"{bid_type}素材速查索引",
                "markdownContent": _render_index_markdown(materials, inventory, bid_type),
                "tags": [bid_type, "素材索引"],
                "applicableTypes": [bid_type],
                "children": [],
            },
            {
                "title": f"{bid_type}目录骨架 skeleton",
                "markdownContent": _render_skeleton_markdown(materials, bid_type),
                "tags": [bid_type, "章节骨架", "merge"],
                "applicableTypes": [bid_type],
                "children": [],
            },
            {
                "title": f"{bid_type}装配规则 rules",
                "markdownContent": _render_rules_markdown(materials, bid_type),
                "tags": [bid_type, "装配规则"],
                "applicableTypes": [bid_type],
                "children": [],
            },
            {
                "title": f"{bid_type}同义词 synonyms",
                "markdownContent": _render_synonyms_markdown(materials, bid_type),
                "tags": [bid_type, "同义词"],
                "applicableTypes": [bid_type],
                "children": [],
            },
            {
                "title": f"{bid_type}通用卡片",
                "markdownContent": f"# {bid_type}通用卡片\n\n沉淀可复用标准素材。正文真源仍是原始 docx，卡片只承载索引、适用条件和 Merge 信息。",
                "tags": [bid_type, "通用素材"],
                "applicableTypes": ["通用", bid_type],
                "children": common_children,
            },
            {
                "title": f"{bid_type}定制卡片",
                "markdownContent": f"# {bid_type}定制卡片\n\n沉淀项目、客户、业主专属素材。定制卡片优先于通用卡片参与覆盖、叠加或附加。",
                "tags": [bid_type, "项目材料"],
                "applicableTypes": [bid_type],
                "children": custom_children,
            },
        ],
    }


def _render_shared_fields_markdown() -> str:
    return """# 字段替换表

字段替换在拼装阶段执行，Wiki 只维护字段定义和来源，不直接改写原始 docx。

| 字段 | 来源 | 典型用途 |
|---|---|---|
| PROJECT_NAME | 招标文件/项目解析 | 封面、投标函、技术方案正文 |
| CLIENT_NAME | 招标文件/客户档案 | 全文客户称谓 |
| BID_TYPE | 创建任务 | 技术标/商务标分流 |
| MODEL_NO | 技术参数/招标要求 | 技术标机型、参数表 |
| RATED_POWER | 机型参数 | 技术标参数和子系统专题 |
| SITE_LOCATION | 招标文件/项目资料 | 场址、运输、环境适应性 |
| DELIVERY_DATE | 招标文件 | 交货计划、商务响应 |
| WARRANTY_YEARS | 招标文件/合同条款 | 质保、服务、商务条款 |
| BID_PRICE | 报价清单 | 商务标报价页 |
| AUTHORIZED_REPRESENTATIVE | 授权资料 | 商务标授权委托 |
"""


def _render_shared_customer_synonyms_markdown(materials: list[dict[str, Any]] | None = None) -> str:
    rows: dict[str, set[str]] = {
        "华能集团": {"华能", "中国华能", "华能新能源"},
        "大唐集团": {"大唐", "中国大唐", "大唐新能源"},
        "国家能源集团": {"国能", "国家能源", "国能投"},
        "招标方": {"业主", "客户", "甲方", "建设单位"},
        "投标方": {"投标人", "乙方", "供应商", "承包人"},
    }
    for material in materials or []:
        name = str(material.get("customerCanonicalName") or material.get("customerName") or "").strip()
        if not name or name == "平台标准":
            continue
        canonical = canonical_customer(name)
        standard = str(canonical.get("customerCanonicalName") or name)
        aliases = rows.setdefault(standard, set())
        aliases.update(str(item) for item in (canonical.get("customerAliases") or []) if str(item).strip())
        aliases.update(str(item) for item in (material.get("customerAliases") or []) if str(item).strip())
        aliases.add(name)
    lines = ["# 客户/业主同义词", "", "| 标准名 | customer_id | 同义词 |", "|---|---|---|"]
    for standard, aliases in sorted(rows.items()):
        customer_id = canonical_customer(standard).get("customerId") or ""
        cleaned = "、".join(sorted(alias for alias in aliases if alias and alias != standard))
        lines.append(f"| {standard} | {customer_id} | {cleaned} |")
    return "\n".join(lines) + "\n"


def _render_shared_project_mapping_markdown() -> str:
    return """# 项目参数映射

项目级 Wiki 只记录差异，不复制平台卡片正文。

| 参数类型 | 技术标用途 | 商务标用途 |
|---|---|---|
| PROJECT_ID / PROJECT_CODE | 匹配项目素材、回写目录 JSON | 匹配项目商务附件、报价与授权材料 |
| CUSTOMER_ID / CUSTOMER_NAME | 匹配客户素材和业主专属规则 | 匹配客户资质要求、合同条款和承诺函称谓 |
| 项目名称/编号 | 封面、方案正文、承诺函 | 投标函、授权、报价文件 |
| 业主/客户 | 条件触发客户专属素材 | 资格、合同条款、承诺函称谓 |
| 场址/地块 | 风资源、环境适应性、校核报告 | 交付、合同履约地点 |
| 机型/容量 | 参数表、子系统、发电量 | 报价清单、供货范围 |
| 交货期/质保期 | 交付验收、运维服务 | 商务响应、合同条款 |
"""


def _render_shared_merge_rules_markdown() -> str:
    return """# override / append / reference 规则

| 关系 | 含义 | 典型场景 |
|---|---|---|
| override | 定制素材覆盖通用素材，只使用定制版 | 项目技术承诺函、项目风资源方案 |
| append | 定制素材追加到通用素材后，两份都进入计划 | 业绩补充、客户专属合作说明 |
| reference | 只挂证据或附件，不改写正文 | 校核报告、证书、报价附件 |
| exclude | 与项目条件冲突时剔除 | 直驱机型剔除齿轮箱专题 |
"""


def _build_shared_rules_node(materials: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "title": "03-共用规则",
        "markdownContent": "# 共用规则\n\n技术标和商务标共用项目参数、客户词典和素材关系裁决，但不共用各自的目录骨架与装配规则。",
        "tags": ["共用规则"],
        "applicableTypes": ["通用", "技术标", "商务标"],
        "children": [
            {"title": "字段替换表", "markdownContent": _render_shared_fields_markdown(), "tags": ["字段替换"], "applicableTypes": ["通用"], "children": []},
            {"title": "客户/业主同义词", "markdownContent": _render_shared_customer_synonyms_markdown(materials), "tags": ["同义词"], "applicableTypes": ["通用"], "children": []},
            {"title": "项目参数映射", "markdownContent": _render_shared_project_mapping_markdown(), "tags": ["项目参数"], "applicableTypes": ["通用"], "children": []},
            {"title": "override / append / reference 规则", "markdownContent": _render_shared_merge_rules_markdown(), "tags": ["装配规则"], "applicableTypes": ["通用"], "children": []},
        ],
    }


def _build_quality_log_node(materials: list[dict[str, Any]]) -> dict[str, Any]:
    docx = [item for item in materials if item.get("ext") == "docx"]
    no_heading = [item for item in docx if int(item.get("headingCount") or 0) == 0]
    oversized = [item for item in docx if int(item.get("sizeBytes") or 0) > MAX_SYNC_DOCX_BYTES]
    unassigned = [item for item in docx if str(item.get("skeletonSection") or item.get("group") or "") in {"", "专项技术", "项目数据", "商务通用"}]
    duplicate_titles = [title for title, count in Counter(str(item.get("title") or "") for item in docx).items() if title and count > 1]

    def list_markdown(title: str, rows: list[Any], formatter: Any) -> str:
        lines = [f"# {title}", ""]
        if not rows:
            lines.append("暂无。")
        else:
            for row in rows[:120]:
                lines.append(f"- {formatter(row)}")
            if len(rows) > 120:
                lines.append(f"- ... 另有 {len(rows) - 120} 条")
        return "\n".join(lines) + "\n"

    return {
        "title": "04-质量日志",
        "markdownContent": (
            "# 质量日志\n\n"
            f"- docx 总数：{len(docx)}\n"
            f"- 无 Heading：{len(no_heading)}\n"
            f"- 超大文件待后台解析：{len(oversized)}\n"
            f"- 未明确归位：{len(unassigned)}\n"
            f"- 重名素材：{len(duplicate_titles)}\n"
        ),
        "tags": ["质量日志"],
        "applicableTypes": ["通用", "技术标", "商务标"],
        "children": [
            {"title": "缺卡片", "markdownContent": "# 缺卡片\n\n本次生成按 docx 自动建卡，未发现缺卡片。后续应由 check.py 对文件系统版 wiki 继续校验。\n", "tags": ["质量日志"], "applicableTypes": ["通用"], "children": []},
            {"title": "孤儿卡片", "markdownContent": "# 孤儿卡片\n\n数据库生成链路不会产生孤儿卡片；文件系统版 wiki 需运行 `wiki/scripts/check.py` 校验。\n", "tags": ["质量日志"], "applicableTypes": ["通用"], "children": []},
            {"title": "Heading异常", "markdownContent": list_markdown("Heading异常", no_heading, lambda item: f"`{item.get('path')}` 未检测到 Word Heading，拼装时按整篇挂载。"), "tags": ["质量日志"], "applicableTypes": ["通用"], "children": []},
            {"title": "超大文件待后台解析", "markdownContent": list_markdown("超大文件待后台解析", oversized, lambda item: f"`{item.get('path')}` {int(item.get('sizeBytes') or 0)/1024/1024:.1f}MB，需后台深度解析。"), "tags": ["质量日志"], "applicableTypes": ["通用"], "children": []},
            {"title": "未归位素材", "markdownContent": list_markdown("未归位素材", unassigned, lambda item: f"`{item.get('path')}` 当前归入 `{item.get('skeletonSection')}`，建议人工确认 skeleton_section。"), "tags": ["质量日志"], "applicableTypes": ["通用"], "children": []},
            {"title": "重名素材", "markdownContent": list_markdown("重名素材", duplicate_titles, lambda title: f"`{title}` 存在多个来源路径，需确认覆盖/叠加关系。"), "tags": ["质量日志"], "applicableTypes": ["通用"], "children": []},
        ],
    }


def _build_material_wiki_blueprint(
    reference: dict[str, Any],
    inventory: dict[str, Any],
    bid_type: str,
) -> dict[str, Any]:
    if bid_type == BUSINESS_BID_TYPE:
        return build_business_wiki_blueprint(inventory, root_title=BUSINESS_WIKI_ROOT_TITLE)

    materials = list(inventory.get("items") or [])
    docx_materials = [item for item in materials if item.get("ext") == "docx"]
    parsed = [item for item in docx_materials if not item.get("parseError")]
    bid_count = len(_filtered_docx_materials(materials, bid_type))
    root_title = f"{bid_type}Wiki（自动生成）"
    skill_name = BUSINESS_WIKI_SKILL_NAME
    root_markdown = (
        f"# {root_title}\n\n"
        f"本 Wiki 由 `{skill_name}` 根据 `{bid_type}` 原始材料库中的真实 docx 和参考 Wiki 结构生成。"
        "它不是素材文件夹浏览器，而是面向投标文件目录生成和正文拼装的规则库。\n\n"
        "## 本次生成范围\n"
        f"- 原始材料总数：{inventory.get('total', 0)}\n"
        f"- docx 素材：{inventory.get('docxTotal', 0)}\n"
        f"- 成功解析 docx：{inventory.get('parsedDocxTotal', 0)}\n"
        f"- 生成卡片：{len(docx_materials)}\n\n"
        "## 标类覆盖\n"
        f"- {bid_type}体系：{bid_count} 份 docx\n\n"
        "## 顶层体系\n"
        f"- `01-{bid_type}体系`：{bid_type}专属索引、目录骨架、装配规则、同义词和卡片。\n"
        "- `共用规则`：字段替换、客户词典、项目参数和 override / append / reference 裁决。\n"
        "- `质量日志`：Heading、超大文件、未归位和重名素材检查。\n\n"
        "## 生产使用约定\n"
        f"- `{bid_type}` 使用自己的 skeleton / rules；目录生成和正文拼装先按标类分流。\n"
        "- Wiki 是给 AI 检索和装配看的规则库，不是人工文件夹；前端只展示结果，AI 必须读取卡片中的身份字段。\n"
        "- 通用素材总是可读；客户素材按 `customer_id/客户同义词` 命中；项目素材按 `project_id/project_code` 命中。\n"
        "- 卡片不承载 docx 全文，只承载路径、关键词、适用条件、Heading 审计和 Merge 信息。\n"
        "- 目录生成优先读取 skeleton，再按 rules 裁决素材关系。\n"
    )
    if reference.get("hasReference"):
        root_markdown += f"\n参考 Wiki 摘要已读取：`{reference.get('referenceRoot')}`。\n"

    return {
        "summary": f"已解析 {len(parsed)}/{len(docx_materials)} 份 {bid_type} docx，并生成 {bid_type} Wiki。",
        "rootTitle": root_title,
        "rootMarkdownContent": root_markdown,
        "nodes": [
            {
                "title": "00-Wiki使用说明",
                "markdownContent": root_markdown,
                "tags": [bid_type, "素材库", skill_name],
                "applicableTypes": [bid_type],
                "children": [],
            },
            _build_bid_type_system_node(materials, inventory, bid_type),
            _build_shared_rules_node(materials),
            _build_quality_log_node(materials),
        ],
    }


def _run_llm_wiki_skill(manifest_path: Path, bid_type: str) -> dict[str, Any]:
    """LLM 主路径：让 opencode 调 wikibuild 生成骨架，再在骨架上语义精修。"""
    if not BUSINESS_WIKI_RUNNER.exists():
        raise RuntimeError(f"{bid_type} Wiki Skill runner 不存在：{BUSINESS_WIKI_RUNNER}")

    prompt = _build_wiki_refine_prompt(BUSINESS_WIKI_SKILL_NAME, manifest_path, bid_type)
    result = OpencodeClient().generate_wiki_blueprint_with_trace(prompt)
    result.setdefault("schema_version", "bid-wiki-blueprint-v1")
    return result


async def generate_business_wiki(
    *,
    reference_path: str = "",
    mode: str = "create",
    fallback_to_deterministic: bool = False,
) -> dict[str, Any]:
    """商务标 Wiki：LLM 精修主路径 + local_skill 回退 + 内联确定性回退。"""
    bid_type = BUSINESS_BID_TYPE
    reference_root = Path(reference_path).expanduser().resolve() if reference_path else DEFAULT_REFERENCE_WIKI_PATH
    reference = _summarize_reference_wiki(reference_root)
    full_inventory = await _summarize_material_inventory()
    material_inventory = _filter_inventory_for_bid_type(full_inventory, bid_type)
    manifest_path = _write_wiki_manifest(reference, material_inventory, bid_type)
    generator = "llm_refine"
    fallback_used = False

    try:
        # 主路径：LLM 调 wikibuild 产骨架，再语义精修。
        skill_result = await asyncio.to_thread(_run_llm_wiki_skill, manifest_path, bid_type)
        blueprint = normalize_blueprint(load_wiki_blueprint_result(skill_result))
        blueprint["rootTitle"] = BUSINESS_WIKI_ROOT_TITLE
        opencode_output: dict[str, Any] = skill_result.get("opencodeOutput") or {}
    except Exception as llm_exc:
        # 一级回退：opencode 不可用/精修失败时，直接用确定性脚本骨架。
        try:
            skill_result = await asyncio.to_thread(
                run_local_wiki_skill,
                manifest_path,
                skill_name=BUSINESS_WIKI_SKILL_NAME,
                runner=BUSINESS_WIKI_RUNNER,
            )
            blueprint = normalize_blueprint(load_wiki_blueprint_result(skill_result))
            blueprint["rootTitle"] = BUSINESS_WIKI_ROOT_TITLE
            opencode_output = skill_result.get("opencodeOutput") or {}
            opencode_output = {
                **opencode_output,
                "fallback": "local_skill",
                "llmError": str(llm_exc),
            }
            generator = "local_skill"
            fallback_used = True
        except Exception as exc:
            failed_output = {
                "status": "failed",
                "sessionId": str(manifest_path),
                "providerId": "local-skill",
                "modelId": BUSINESS_WIKI_SKILL_NAME,
                "receivedAt": now_iso(),
                "parts": [
                    {
                        "type": "text",
                        "text": f"LLM 精修失败（{llm_exc}）；脚本骨架回退也失败（{exc}）。",
                    }
                ],
            }
            if not fallback_to_deterministic:
                raise PeripheralError(
                    502,
                    f"创建 {bid_type} Wiki 调用 {BUSINESS_WIKI_SKILL_NAME} 失败：{exc}",
                    "WIKI_SKILL_FAILED",
                    {"opencodeOutput": failed_output},
                ) from exc
            # 二级回退：仅在显式允许时使用内联确定性蓝图。
            blueprint = normalize_blueprint(
                _build_material_wiki_blueprint(reference, material_inventory, bid_type)
            )
            opencode_output = {
                **failed_output,
                "fallback": "deterministic",
            }
            generator = "deterministic_fallback"
            fallback_used = True

    imported = await business_material_store.import_generated_wiki_blueprint(
        root_title=blueprint["rootTitle"],
        root_markdown_content=blueprint.get("rootMarkdownContent") or "",
        nodes=blueprint["nodes"],
        mode=mode,
    )
    imported["generation"] = {
        "summary": blueprint["summary"],
        "referencePath": str(reference_root),
        "bidType": bid_type,
        "skill": BUSINESS_WIKI_SKILL_NAME,
        "generator": generator,
        "fallbackUsed": fallback_used,
        "materialInventory": {
            "total": material_inventory.get("total", 0),
            "docxTotal": material_inventory.get("docxTotal", 0),
            "parsedDocxTotal": material_inventory.get("parsedDocxTotal", 0),
            "groupCount": len(material_inventory.get("groups") or {}),
        },
        "opencodeOutput": opencode_output,
    }
    return imported
