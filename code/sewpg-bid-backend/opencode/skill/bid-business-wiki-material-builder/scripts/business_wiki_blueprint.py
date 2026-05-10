from __future__ import annotations

import json
import re
import hashlib
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

IMAGE_EXTS = {"png", "jpg", "jpeg", "bmp", "gif", "webp", "tif", "tiff"}
BUSINESS_ROOT_TITLES = [
    "01-素材总表",
    "02-模板模块映射表",
    "03-证据卡片",
    "04-待填写与待确认清单",
    "05-使用规则",
]
COMMON_GROUPS = [
    "01-资质合规库",
    "02-企业能力库",
    "03-业绩资产池",
    "04-财务资料库",
    "05-专题证书库",
    "06-通用模板底稿库",
]
SPECIAL_COMMON_SUBGROUPS = {
    "05-专题证书库": ["01-机型认证证书", "02-大部件型式认证证书"],
}
CUSTOM_GROUPS = [
    "01-客户关系与专项证明",
    "02-商务响应文件",
    "03-模板底稿与过程文件",
]
MODULE_CONFIGS = [
    {
        "module_code": "BM-01",
        "module_name": "01-商务评分索引表",
        "usage_mode": "reference_only",
        "path_prefixes": [
            "通用素材/01-资质合规库",
            "通用素材/02-企业能力库",
            "通用素材/03-业绩资产池",
            "客户素材/*/01-客户关系与专项证明",
            "项目素材/*/01-客户关系与专项证明",
        ],
        "categories": ["资格资质", "企业能力", "业绩证明", "客户关系与专项证明"],
        "keywords": ["评分", "评价", "资质", "证书", "业绩", "示范应用", "优秀供应商", "框架协议"],
        "fallback_scope": "当前身份可读范围下的资质、能力、业绩、客户关系材料",
        "missing_hint": "补充与评分点直接对应的资质、业绩或客户关系证明材料。",
    },
    {
        "module_code": "BM-02",
        "module_name": "02-投标函与授权模块",
        "usage_mode": "extract_fields",
        "path_prefixes": [
            "通用素材/06-通用模板底稿库",
            "客户素材/*/02-商务响应文件",
            "项目素材/*/02-商务响应文件",
        ],
        "categories": ["法定代表人/授权", "商务响应文件", "模板底稿"],
        "keywords": ["投标函", "授权", "委托", "法定代表人", "签字", "盖章", "授权书"],
        "fallback_scope": "当前项目/客户的商务响应文件与通用模板底稿",
        "missing_hint": "补充本项目投标函、授权委托书或对应空白模板。",
    },
    {
        "module_code": "BM-03",
        "module_name": "03-投标价格表模块",
        "usage_mode": "fill_table",
        "path_prefixes": ["客户素材/*/02-商务响应文件", "项目素材/*/02-商务响应文件"],
        "categories": ["报价与分项表", "商务响应文件"],
        "keywords": ["投标价格", "报价", "分项报价", "总价", "价格表", "报价表"],
        "fallback_scope": "当前项目的商务响应文件与整理底稿",
        "missing_hint": "补充本项目投标价格表或报价数据源。",
    },
    {
        "module_code": "BM-04",
        "module_name": "04-货物规格一览表模块",
        "usage_mode": "fill_table",
        "path_prefixes": ["客户素材/*/02-商务响应文件", "项目素材/*/02-商务响应文件"],
        "categories": ["报价与分项表", "商务响应文件"],
        "keywords": ["规格", "货物规格", "一览表", "供货范围", "参数表", "配置表"],
        "fallback_scope": "当前项目的商务响应文件与过程底稿",
        "missing_hint": "补充货物规格一览表或可回填该表的数据底稿。",
    },
    {
        "module_code": "BM-05",
        "module_name": "05-商务偏差表模块",
        "usage_mode": "fill_table",
        "path_prefixes": ["客户素材/*/02-商务响应文件", "项目素材/*/02-商务响应文件"],
        "categories": ["商务偏差", "商务响应文件"],
        "keywords": ["商务偏差", "偏差表", "偏离", "响应表"],
        "fallback_scope": "当前项目的商务响应文件",
        "missing_hint": "补充商务偏差表或合同条款响应底稿。",
    },
    {
        "module_code": "BM-06",
        "module_name": "06-投标保证金模块",
        "usage_mode": "attach_whole",
        "path_prefixes": [
            "客户素材/*/02-商务响应文件",
            "项目素材/*/02-商务响应文件",
            "通用素材/04-财务资料库",
        ],
        "categories": ["投标保证金", "财务与信用", "商务响应文件"],
        "keywords": ["保证金", "回单", "保函", "电汇", "担保", "银行"],
        "fallback_scope": "当前项目商务响应文件与财务资料库",
        "missing_hint": "补充投标保证金回单、保函或对应支付凭证。",
    },
    {
        "module_code": "BM-07",
        "module_name": "07-履约保证承诺模块",
        "usage_mode": "attach_whole",
        "path_prefixes": [
            "通用素材/06-通用模板底稿库",
            "客户素材/*/02-商务响应文件",
            "项目素材/*/02-商务响应文件",
        ],
        "categories": ["承诺函件", "商务响应文件", "模板底稿"],
        "keywords": ["履约", "保证函", "承诺书", "履约保证", "承诺"],
        "fallback_scope": "当前项目商务响应文件与通用模板底稿",
        "missing_hint": "补充履约保证函格式承诺书或项目定制承诺件。",
    },
    {
        "module_code": "BM-08",
        "module_name": "08-资格证明文件模块（附件7）",
        "usage_mode": "attach_whole",
        "path_prefixes": [
            "通用素材/01-资质合规库",
            "通用素材/04-财务资料库",
            "通用素材/05-专题证书库",
        ],
        "categories": ["资格资质", "财务与信用", "专题证书"],
        "keywords": ["营业执照", "资质", "认证", "信用", "资信", "纳税", "开户", "证书"],
        "fallback_scope": "通用素材的资质、财务、专题证书范围",
        "missing_hint": "补充资格证明文件所需的营业执照、资质、认证、资信或信用截图。",
    },
    {
        "module_code": "BM-09",
        "module_name": "09-业绩情况表模块（附件7I）",
        "usage_mode": "fill_table",
        "path_prefixes": [
            "通用素材/03-业绩资产池",
            "客户素材/*/01-客户关系与专项证明",
            "项目素材/*/01-客户关系与专项证明",
        ],
        "categories": ["业绩证明", "客户关系与专项证明"],
        "keywords": ["业绩", "合同", "中标通知书", "验收", "运行", "240h", "示范应用"],
        "fallback_scope": "业绩资产池与客户专项证明材料",
        "missing_hint": "补充可筛选的合同、通知书、运行证明或示范应用证明。",
    },
    {
        "module_code": "BM-10",
        "module_name": "10-开标价格表模块",
        "usage_mode": "fill_table",
        "path_prefixes": ["客户素材/*/02-商务响应文件", "项目素材/*/02-商务响应文件"],
        "categories": ["报价与分项表", "商务响应文件"],
        "keywords": ["开标", "开标价格表", "唱标", "报价"],
        "fallback_scope": "当前项目商务响应文件",
        "missing_hint": "补充开标价格表或与其一一对应的报价底稿。",
    },
    {
        "module_code": "BM-11",
        "module_name": "11-其他说明与承诺模块（附件9）",
        "usage_mode": "attach_whole",
        "path_prefixes": [
            "客户素材/*/02-商务响应文件",
            "项目素材/*/02-商务响应文件",
            "客户素材/*/03-模板底稿与过程文件",
            "项目素材/*/03-模板底稿与过程文件",
        ],
        "categories": ["承诺函件", "商务响应文件", "模板底稿与过程文件"],
        "keywords": ["附件9", "其他说明", "补充说明", "承诺", "声明", "效力说明", "廉洁"],
        "fallback_scope": "当前项目商务响应文件与过程底稿",
        "missing_hint": "补充附件9、专项声明、效力说明或其他承诺文件。",
    },
    {
        "module_code": "BM-12",
        "module_name": "12-否决项与符合性响应模块",
        "usage_mode": "extract_fields",
        "path_prefixes": [
            "客户素材/*/02-商务响应文件",
            "项目素材/*/02-商务响应文件",
            "通用素材/01-资质合规库",
        ],
        "categories": ["商务响应文件", "资格资质", "承诺函件"],
        "keywords": ["否决", "符合性", "响应", "必须", "不得", "承诺", "资格"],
        "fallback_scope": "当前项目商务响应文件与必要资质证明",
        "missing_hint": "补充否决项响应表、符合性声明或直接支撑的资格材料。",
    },
    {
        "module_code": "BM-13",
        "module_name": "13-供应链协同模块",
        "usage_mode": "reference_only",
        "path_prefixes": [
            "通用素材/02-企业能力库",
            "客户素材/*/01-客户关系与专项证明",
            "项目素材/*/01-客户关系与专项证明",
        ],
        "categories": ["企业能力", "客户关系与专项证明"],
        "keywords": ["供应链", "协同", "战略协议", "框架协议", "产能", "服务能力", "合作"],
        "fallback_scope": "企业能力与客户关系专项证明材料",
        "missing_hint": "补充供应链协同、战略合作或服务协同证明。",
    },
]
DATE_RE = re.compile(r"((?:20\d{2}|19\d{2})[年./-]\d{1,2}[月./-]\d{1,2}日?)")
DOC_NO_RE = re.compile(r"(?:编号|证书编号|文号|合同编号)[:：\s]*([A-Za-z0-9\-_/]+)")
ISSUER_RE = re.compile(r"(?:由|发证机构|签发单位|出具单位|开户行|银行)[:：\s]*([^，。；\n]{2,40})")
FINAL_KEYWORDS = ("终版", "定稿", "签章", "盖章", "扫描件", "原件", "final")


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"manifest must be a JSON object: {path}")
    return data


def md_escape(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", "<br>")


def node(
    title: str,
    markdown: str,
    tags: list[str] | None = None,
    children: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "markdownContent": markdown,
        "tags": tags or ["商务标"],
        "applicableTypes": ["商务标"],
        "children": children or [],
    }


def material_title(item: dict[str, Any]) -> str:
    return str(item.get("title") or item.get("name") or "未命名素材")


def source_path(item: dict[str, Any]) -> str:
    path = str(item.get("path") or "").strip("/")
    if path:
        return path
    folder_path = str(item.get("folderPath") or "").strip("/")
    name = str(item.get("name") or "").strip("/")
    return "/".join(part for part in (folder_path, name) if part)


def source_segments(item: dict[str, Any]) -> list[str]:
    return [segment for segment in source_path(item).split("/") if segment]


def identity_scope(item: dict[str, Any]) -> str:
    scope = str(item.get("identityScope") or "").strip().lower()
    if scope in {"project", "customer", "general"}:
        return scope
    tier = str(item.get("materialTier") or "").strip().lower()
    if tier in {"project", "customer"}:
        return tier
    path = source_path(item)
    if path.startswith("项目素材/"):
        return "project"
    if path.startswith("客户素材/"):
        return "customer"
    return "general"


def material_tier(item: dict[str, Any]) -> str:
    scope = identity_scope(item)
    if scope == "project":
        return "项目素材"
    if scope == "customer":
        return "客户素材"
    return "通用素材"


def bucket_name(item: dict[str, Any], tier: str, segments: list[str]) -> str:
    if tier == "客户素材":
        return segments[1] if len(segments) > 1 else str(item.get("customerCanonicalName") or item.get("customerName") or "待补客户")
    if tier == "项目素材":
        return segments[1] if len(segments) > 1 else str(item.get("projectCode") or item.get("projectId") or item.get("projectName") or "待补项目")
    return ""


def second_group(item: dict[str, Any], tier: str, segments: list[str]) -> str:
    if tier == "通用素材":
        if len(segments) > 1:
            return segments[1]
        return infer_common_group(source_path(item), material_title(item))
    if len(segments) > 2:
        return segments[2]
    return "02-商务响应文件"


def third_group(item: dict[str, Any], tier: str, group_name: str, segments: list[str]) -> str:
    if tier == "通用素材" and group_name in SPECIAL_COMMON_SUBGROUPS:
        if len(segments) > 2:
            return segments[2]
        return infer_special_common_subgroup(source_path(item), material_title(item), group_name)
    return ""


def infer_special_common_subgroup(path: str, title: str, group_name: str) -> str:
    if group_name != "05-专题证书库":
        return ""
    text = f"{path}/{title}"
    if any(token in text for token in ("叶片", "齿轮箱", "主轴", "发电机", "机舱", "轮毂", "大部件", "型式认证")):
        return "02-大部件型式认证证书"
    return "01-机型认证证书"


def infer_common_group(path: str, title: str) -> str:
    text = f"{path}/{title}"
    if any(token in text for token in ("机型认证", "型式认证", "证书", "部件")):
        return "05-专题证书库"
    if any(token in text for token in ("营业执照", "资质", "认证", "信用", "资信", "纳税", "开户")):
        return "01-资质合规库"
    if any(token in text for token in ("组织架构", "能力", "工厂", "产能", "服务", "专利", "奖项", "质量管理")):
        return "02-企业能力库"
    if any(token in text for token in ("业绩", "合同", "中标通知书", "运行", "240h", "验收")):
        return "03-业绩资产池"
    if any(token in text for token in ("财务", "审计", "报表")):
        return "04-财务资料库"
    return "06-通用模板底稿库"


def infer_business_category(item: dict[str, Any], tier: str, group_name: str) -> str:
    group = str(item.get("group") or "").strip()
    if group:
        return group
    text = f"{source_path(item)}/{material_title(item)}"
    if group_name == "01-资质合规库":
        return "资格资质"
    if group_name == "02-企业能力库":
        return "企业能力"
    if group_name == "03-业绩资产池":
        return "业绩证明"
    if group_name == "04-财务资料库":
        return "财务与信用"
    if group_name == "05-专题证书库":
        return "专题证书"
    if group_name == "06-通用模板底稿库":
        return "模板底稿"
    if group_name == "01-客户关系与专项证明":
        return "客户关系与专项证明"
    if "报价" in text or "价格" in text or "开标" in text or "规格" in text:
        return "报价与分项表"
    if "偏差" in text:
        return "商务偏差"
    if "授权" in text or "委托" in text or "法定代表人" in text:
        return "法定代表人/授权"
    if "保证金" in text:
        return "投标保证金"
    if "承诺" in text or "函" in text or "说明" in text:
        return "承诺函件"
    return "商务响应文件"


def infer_evidence_topic(path: str, title: str, category: str, document_type: str) -> str:
    text = f"{path}/{title}/{category}/{document_type}"
    topic_rules = [
        ("投标函与基础响应文书", ("投标函", "法定代表人", "授权", "委托", "专用章", "廉洁")),
        ("报价与商务表格", ("报价", "价格", "开标", "规格", "供货范围", "偏差")),
        ("保证金与保函", ("保证金", "保函", "回单", "电汇", "担保")),
        ("资格资质与信用", ("营业执照", "资质", "体系认证", "信用", "资信", "纳税", "开户")),
        ("机型与大部件认证", ("机型认证", "整机认证", "大部件", "型式认证", "叶片", "齿轮箱", "发电机", "主轴承")),
        ("业绩合同与运行证明", ("业绩", "合同", "中标通知书", "240h", "试运行", "验收")),
        ("企业能力与供货保障", ("公司简介", "工厂", "生产能力", "服务能力", "质量管理", "供应链", "供货")),
        ("财务与诚信", ("财务", "审计", "报表", "纳税", "资信证明", "信用中国", "失信")),
        ("承诺声明与其他说明", ("承诺", "声明", "说明", "附件9", "其他内容")),
        ("客户关系与专项证明", ("战略协议", "框架协议", "评价信", "优秀供应商", "示范应用")),
    ]
    for topic, keywords in topic_rules:
        if any(keyword in text for keyword in keywords):
            return topic
    return category or "商务素材"


def infer_applicable_chapters(profile: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    values.extend(profile.get("applicable_modules") or [])
    text = f"{profile.get('path')}/{profile.get('title')}/{profile.get('document_type')}/{profile.get('business_category')}"
    chapter_rules = [
        ("投标函", ("投标函",)),
        ("法定代表人身份证明/授权书", ("法定代表人", "授权", "委托")),
        ("投标人廉洁自律承诺书", ("廉洁",)),
        ("投标价格表/开标价格表", ("报价", "价格", "开标")),
        ("货物规格一览表/供货范围", ("规格", "供货范围")),
        ("商务偏差表", ("偏差", "偏离")),
        ("投标保证金/保函", ("保证金", "保函", "回单")),
        ("履约保证承诺", ("履约",)),
        ("资格证明文件", ("营业执照", "资质", "体系认证", "信用", "资信", "纳税", "开户")),
        ("机型认证证书/大部件型式认证证书", ("机型认证", "整机认证", "大部件", "型式认证", "叶片", "齿轮箱", "发电机")),
        ("业绩情况表及支撑材料", ("业绩", "合同", "中标", "240h", "验收")),
        ("投标人需要说明的其他内容", ("承诺", "声明", "说明", "附件9", "其他内容")),
    ]
    for chapter, keywords in chapter_rules:
        if any(keyword in text for keyword in keywords):
            values.append(chapter)
    return dedupe_strings(values, limit=8)


def infer_chapter_keywords(profile: dict[str, Any]) -> list[str]:
    return dedupe_strings(
        [
            profile.get("evidence_topic"),
            profile.get("business_category"),
            profile.get("document_type"),
            profile.get("group_name"),
            profile.get("subgroup_name"),
            *(profile.get("applicable_chapters") or []),
            *(profile.get("keywords") or []),
        ],
        limit=16,
    )


def collect_headings(item: dict[str, Any], limit: int = 8) -> list[str]:
    headings = item.get("headings") or []
    if not isinstance(headings, list):
        return []
    values: list[str] = []
    for entry in headings:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or "").strip()
        if title:
            values.append(title)
        if len(values) >= limit:
            break
    return values


def collect_paragraphs(item: dict[str, Any], limit: int = 4) -> list[str]:
    paragraphs = item.get("paragraphs") or []
    if not isinstance(paragraphs, list):
        return []
    return [str(value).strip() for value in paragraphs[:limit] if str(value).strip()]


def collect_tables(item: dict[str, Any], limit: int = 2) -> list[str]:
    tables = item.get("tables") or []
    if not isinstance(tables, list):
        return []
    return [str(value).strip() for value in tables[:limit] if str(value).strip()]


def stable_short_id(value: Any) -> str:
    text = str(value or "").strip() or "segment"
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def segment_keywords_from_text(text: str, fallback: list[str] | None = None, limit: int = 12) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for raw in [*(fallback or []), *re.split(r"[/_\-\s　.。；;，,、（）()【】\\]+", str(text or ""))]:
        token = str(raw or "").strip()
        if len(token) < 2 or token in seen:
            continue
        seen.add(token)
        values.append(token)
        if len(values) >= limit:
            break
    return values


def dedupe_strings(values: list[Any], limit: int = 12) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in {"-", "[]", "待识别", "待映射", "待回退检索"}:
            continue
        if text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def ocr_payload(item: dict[str, Any]) -> dict[str, Any]:
    payload = item.get("businessWikiOcr") if isinstance(item.get("businessWikiOcr"), dict) else {}
    return payload


def ocr_text(item: dict[str, Any]) -> str:
    direct = str(item.get("ocrText") or "").strip()
    if direct:
        return direct
    return str(ocr_payload(item).get("text") or "").strip()


def ocr_fields(item: dict[str, Any]) -> dict[str, Any]:
    direct = item.get("ocrFields") if isinstance(item.get("ocrFields"), dict) else {}
    if direct:
        return direct
    fields = ocr_payload(item).get("fields")
    return fields if isinstance(fields, dict) else {}


def collect_keywords(item: dict[str, Any], title: str, category: str, limit: int = 8) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    raw_keywords = item.get("keywords") or []
    if isinstance(raw_keywords, list):
        candidates = [str(value).strip() for value in raw_keywords if str(value).strip()]
    else:
        candidates = []
    candidates.extend([category, title])
    for token in str(ocr_text(item)[:1000]).split():
        if any(marker in token for marker in ("证书", "认证", "有效期", "机型", "部件", "编号")):
            candidates.append(token.strip(" ：:，,。；;"))
    for value in candidates:
        if value and value not in seen:
            seen.add(value)
            values.append(value)
        if len(values) >= limit:
            break
    return values


def infer_cleaning_strategy(item: dict[str, Any], ext: str, path: str, title: str) -> str:
    source_ext = str(item.get("sourceExt") or ext).lower()
    if source_ext in IMAGE_EXTS:
        return "仅原件（图片直挂，不触发清洗）"
    if source_ext == "pdf" and (item.get("cleanedFileName") or item.get("hasCleanedWord")):
        return "原件+清洗稿（PDF已转换为Word）"
    if source_ext == "pdf":
        return "原件+清洗稿（PDF应转换为Word）"
    if ext in IMAGE_EXTS:
        return "仅原件（图片直挂，不触发清洗）"
    if item.get("cleanedFileName") or item.get("hasCleanedWord"):
        return "原件+清洗稿"
    if ext in {"doc", "docx", "wps", "rtf"}:
        return "建议补清洗稿"
    return "原件保留"


def infer_document_type(ext: str, path: str, title: str, category: str) -> str:
    text = f"{path}/{title}/{category}"
    if "投标函" in text:
        return "投标函"
    if "授权" in text or "委托" in text:
        return "授权文件"
    if "报价" in text or "价格表" in text:
        return "报价表"
    if "规格" in text:
        return "规格表"
    if "偏差" in text:
        return "偏差表"
    if "保证金" in text:
        return "保证金凭证"
    if "保函" in text:
        return "保函"
    if "合同" in text:
        return "合同/协议"
    if "证书" in text or "营业执照" in text or "资质" in text:
        return "证书/资质文件"
    if "回单" in text or "截图" in text:
        return "截图/回单"
    if ext in IMAGE_EXTS:
        return "图片扫描件"
    if ext == "pdf":
        return "PDF文件"
    return "商务文件"


def infer_evidence_type(ext: str, path: str, title: str, category: str) -> str:
    text = f"{path}/{title}/{category}"
    if ext in IMAGE_EXTS:
        return "scan_image"
    if ext == "pdf":
        return "pdf_attachment"
    if "模板" in text or "空白" in text:
        return "template_draft"
    if "报价" in text or "价格" in text or "规格" in text or "偏差" in text:
        return "table_source"
    if any(token in text for token in ("回单", "保函", "截图", "保证金")):
        return "payment_or_compliance_proof"
    if any(token in text for token in ("证书", "执照", "资质", "认证")):
        return "certificate_proof"
    return "document_proof"


def infer_usage_mode(ext: str, path: str, title: str, category: str) -> str:
    text = f"{path}/{title}/{category}"
    if ext in IMAGE_EXTS:
        return "extract_image"
    if any(token in text for token in ("报价", "价格表", "开标", "规格", "偏差", "供货范围")):
        return "fill_table"
    if any(token in text for token in ("投标函", "授权", "委托", "否决", "符合性")):
        return "extract_fields"
    if any(token in text for token in ("模板", "空白", "底稿")):
        return "reference_only"
    return "attach_whole"


def extract_text_blob(item: dict[str, Any], title: str, path: str, category: str) -> str:
    parts = [title, path, category]
    parts.extend(collect_headings(item, 12))
    parts.extend(collect_paragraphs(item, 6))
    parts.extend(collect_tables(item, 4))
    if ocr_text(item):
        parts.append(ocr_text(item))
    parts.extend(str(value).strip() for value in (item.get("keywords") or []) if str(value).strip())
    return "\n".join(part for part in parts if part)


def extract_dates(text: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for match in DATE_RE.findall(text):
        token = match.strip()
        if token not in seen:
            seen.add(token)
            values.append(token)
    return values


def parse_date_token(token: str) -> date | None:
    cleaned = token.strip().replace("年", "-").replace("月", "-").replace("日", "")
    cleaned = cleaned.replace(".", "-").replace("/", "-")
    parts = [part for part in cleaned.split("-") if part]
    if len(parts) != 3:
        return None
    try:
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None


def extract_document_number(text: str) -> str:
    match = DOC_NO_RE.search(text)
    return match.group(1).strip() if match else ""


def extract_issuer(text: str) -> str:
    match = ISSUER_RE.search(text)
    return match.group(1).strip() if match else ""


def infer_validity_status(text: str, path: str, title: str, ext: str) -> tuple[str, str, str, str]:
    dates = extract_dates(text)
    issue = dates[0] if dates else ""
    expiry = ""
    for token in dates:
        prefix_start = max(0, text.find(token) - 8)
        prefix = text[prefix_start:text.find(token)] if token in text else ""
        if any(flag in prefix for flag in ("有效期", "截止", "到期", "至")):
            expiry = token
            break
    if not expiry and len(dates) >= 2:
        expiry = dates[1]
    if expiry:
        parsed = parse_date_token(expiry)
        if parsed is not None:
            status = "expired" if parsed < date.today() else "valid"
        else:
            status = "pending_verify"
    elif ext in IMAGE_EXTS or "截图" in f"{path}/{title}":
        status = "pending_verify"
    else:
        status = "unknown"
    last_verified = datetime.now().strftime("%Y-%m-%d") if status in {"valid", "expired"} else ""
    return issue, expiry, status, last_verified


def infer_final_version(path: str, title: str) -> bool:
    text = f"{path}/{title}".lower()
    return any(keyword.lower() in text for keyword in FINAL_KEYWORDS)


def infer_priority_score(tier: str, usage_mode: str, final_version: bool) -> int:
    base = 60 if tier == "通用素材" else 80 if tier == "客户素材" else 95
    if usage_mode == "fill_table":
        base += 3
    if usage_mode == "extract_image":
        base -= 5
    if final_version:
        base += 5
    return max(1, min(base, 100))


def infer_applicable_conditions(item: dict[str, Any], tier: str) -> str:
    customer = str(item.get("customerCanonicalName") or item.get("customerName") or "").strip()
    project = str(item.get("projectCode") or item.get("projectId") or item.get("projectName") or "").strip()
    if tier == "项目素材":
        return f"仅在 project_id/project_code 命中 `{project or '当前项目'}` 时可用。"
    if tier == "客户素材":
        return f"仅在 customer_id/customer_name 命中 `{customer or '当前客户'}` 时可用。"
    return "同标类项目均可读取，若存在客户/项目定制版则优先级后置。"


def infer_risk_notes(item: dict[str, Any], ext: str, validity_status: str) -> str:
    notes: list[str] = []
    ocr_status = str(item.get("ocrStatus") or ocr_payload(item).get("status") or "")
    if ext in IMAGE_EXTS:
        notes.append("图片原件不做清洗，使用前需人工核验证书内容与版式。")
    if ext == "pdf":
        notes.append("PDF 应保留原件并使用清洗稿/识别文本作为检索依据。")
    if ocr_status == "failed":
        notes.append("OCR 识别失败，证书编号、有效期和机型需人工核验。")
    elif ocr_status in {"empty", "not_required"} and (ext in IMAGE_EXTS or ext == "pdf"):
        notes.append("未获得可用 OCR 文本，图片/PDF 内容需人工核验。")
    if str(item.get("parseError") or "").strip():
        notes.append(f"解析异常：{item.get('parseError')}")
    if not collect_headings(item) and ext in {"doc", "docx", "wps", "rtf"}:
        notes.append("未检测到 Heading，后续引用时优先整件挂载或人工定位。")
    if validity_status in {"pending_verify", "unknown"}:
        notes.append("有效期/签发信息未自动确认，生成前需人工复核。")
    return "；".join(notes) or "无显著自动风险。"


def build_evidence_segments(profile: dict[str, Any]) -> list[dict[str, str]]:
    segments: list[dict[str, str]] = []
    base_keywords = [str(value) for value in profile.get("keywords") or [] if str(value).strip()]

    def add_segment(
        suffix: str,
        title: str,
        segment_type: str,
        segment_scope: str,
        summary: str,
        source_pages: str = "",
        keywords: list[str] | None = None,
    ) -> None:
        clean_title = str(title or "").strip()
        clean_summary = str(summary or "").strip()
        if not clean_title and not clean_summary:
            return
        seed = f"{profile['card_id']}:{suffix}:{clean_title}:{clean_summary[:80]}"
        segments.append(
            {
                "segment_id": f"biz-seg-{stable_short_id(seed)}",
                "segment_title": clean_title or profile["title"],
                "segment_type": segment_type or profile["evidence_type"],
                "segment_scope": segment_scope,
                "segment_source_pages": source_pages or profile["source_pages"],
                "segment_summary": clean_summary or profile["summary"],
                "segment_keywords": "、".join(segment_keywords_from_text(f"{clean_title} {clean_summary}", [*base_keywords, *(keywords or [])])),
            }
        )

    add_segment(
        "primary",
        profile["title"],
        profile["evidence_type"],
        "file_primary",
        profile["summary"],
        profile["source_pages"],
    )
    for index, heading in enumerate(collect_headings(profile["raw"], 10), start=1):
        add_segment(
            f"heading-{index}",
            heading,
            "heading_section",
            "cleaned_heading",
            f"清洗稿标题片段：{heading}",
            "清洗稿标题/待页码定位",
            [heading],
        )
    for index, table in enumerate(collect_tables(profile["raw"], 6), start=1):
        add_segment(
            f"table-{index}",
            f"{profile['title']} 表格片段{index}",
            "table_source",
            "cleaned_table",
            table[:260],
            "清洗稿表格/待页码定位",
            ["表格", "报价", "规格", "偏差", "供货范围"],
        )
    ocr_lines = [line.strip() for line in str(profile.get("ocr_text_excerpt") or "").splitlines() if line.strip()]
    for index, line in enumerate(ocr_lines[:6], start=1):
        if len(line) < 4:
            continue
        add_segment(
            f"ocr-{index}",
            line[:36],
            "ocr_text",
            "ocr_excerpt",
            line[:260],
            profile["source_pages"],
            ["OCR", "证书", "编号", "有效期", "机型"],
        )
    return segments[:18]


def profile_material(item: dict[str, Any]) -> dict[str, Any]:
    title = material_title(item)
    path = source_path(item)
    segments = source_segments(item)
    tier = material_tier(item)
    group_name = second_group(item, tier, segments)
    category = infer_business_category(item, tier, group_name)
    ext = str(item.get("ext") or item.get("sourceExt") or Path(path).suffix.lstrip(".") or "").lower()
    source_ext = str(item.get("sourceExt") or ext).lower()
    cleaned_strategy = infer_cleaning_strategy(item, ext, path, title)
    document_type = infer_document_type(ext, path, title, category)
    evidence_type = infer_evidence_type(ext, path, title, category)
    evidence_topic = infer_evidence_topic(path, title, category, document_type)
    usage_mode = infer_usage_mode(ext, path, title, category)
    keywords = collect_keywords(item, title, category)
    text_blob = extract_text_blob(item, title, path, category)
    fields = ocr_fields(item)
    issue_date, expiry_date, validity_status, last_verified_at = infer_validity_status(text_blob, path, title, ext)
    issue_date = str(fields.get("issueDate") or item.get("issueDate") or issue_date)
    expiry_date = str(fields.get("expiryDate") or item.get("expiryDate") or expiry_date)
    if expiry_date:
        _, _, validity_status, last_verified_at = infer_validity_status("\n".join([issue_date, expiry_date]), path, title, ext)
    final_version = infer_final_version(path, title)
    card_id = f"biz-card-{str(item.get('id') or Path(path).stem).strip()}"
    key_fields = collect_headings(item, 5) or keywords[:4]
    summary_parts = collect_headings(item, 3) + collect_paragraphs(item, 2)
    if ocr_text(item) and not summary_parts:
        summary_parts = [line.strip() for line in ocr_text(item).splitlines() if line.strip()][:2]
    summary = "；".join(summary_parts[:4]) if summary_parts else f"{document_type}，当前主要依赖路径与标题识别。"
    ocr_status = str(item.get("ocrStatus") or ocr_payload(item).get("status") or "")
    ocr_confidence = str(item.get("ocrConfidence") or ocr_payload(item).get("confidence") or "")
    profile = {
        "card_id": card_id,
        "material_id": str(item.get("id") or ""),
        "title": title,
        "path": path,
        "segments": segments,
        "material_tier": tier,
        "group_name": group_name,
        "subgroup_name": third_group(item, tier, group_name, segments),
        "bucket_name": bucket_name(item, tier, segments),
        "business_category": category,
        "evidence_topic": evidence_topic,
        "document_type": document_type,
        "evidence_type": evidence_type,
        "cleaned_file_name": str(item.get("cleanedFileName") or ""),
        "cleaning_strategy": cleaned_strategy,
        "identity_scope": identity_scope(item),
        "customer_id": str(item.get("customerId") or ""),
        "customer_name": str(item.get("customerCanonicalName") or item.get("customerName") or ""),
        "project_id": str(item.get("projectId") or ""),
        "project_code": str(item.get("projectCode") or item.get("projectName") or ""),
        "key_fields": key_fields,
        "keywords": keywords,
        "summary": summary,
        "issuer": str(fields.get("issuer") or item.get("issuer") or extract_issuer(text_blob)),
        "document_number": str(fields.get("documentNumber") or item.get("documentNumber") or extract_document_number(text_blob)),
        "issue_date": issue_date,
        "expiry_date": expiry_date,
        "validity_status": validity_status,
        "last_verified_at": last_verified_at,
        "applicable_conditions": infer_applicable_conditions(item, tier),
        "risk_notes": "",
        "ocr_status": ocr_status or ("not_required" if source_ext not in IMAGE_EXTS and source_ext != "pdf" else "required"),
        "ocr_source_type": str(item.get("ocrSourceType") or ocr_payload(item).get("sourceType") or ""),
        "ocr_confidence": ocr_confidence or ("n/a" if ext in IMAGE_EXTS else "1.00" if ext in {"doc", "docx", "wps", "rtf"} else "待OCR"),
        "ocr_text_excerpt": ocr_text(item)[:500],
        "turbine_models": [str(value) for value in (fields.get("turbineModels") or item.get("turbineModels") or []) if str(value).strip()][:8],
        "components": [str(value) for value in (fields.get("components") or item.get("components") or []) if str(value).strip()][:8],
        "is_final_version": final_version,
        "source_pages": "待页码回填" if source_ext in IMAGE_EXTS or source_ext == "pdf" else "原始文档未分页索引",
        "usage_mode": usage_mode,
        "priority_score": infer_priority_score(tier, usage_mode, final_version),
        "needs_human_confirm": False,
        "retrieval_source": "path+title+headings+keywords",
        "applicable_modules": [],
        "applicable_chapters": [],
        "chapter_keywords": [],
        "module_matches": [],
        "search_text": text_blob,
        "ext": ext,
        "table_count": int(item.get("tableCount") or 0),
        "heading_count": len(collect_headings(item, 20)),
        "raw": item,
    }
    profile["risk_notes"] = infer_risk_notes(item, ext, validity_status)
    profile["needs_human_confirm"] = bool(
        ext in IMAGE_EXTS
        or validity_status in {"pending_verify", "unknown"}
        or str(item.get("parseError") or "").strip()
        or usage_mode in {"fill_table", "extract_fields"}
    )
    profile["evidence_segments"] = build_evidence_segments(profile)
    return profile


def wildcard_match(path: str, pattern: str) -> bool:
    escaped = re.escape(pattern).replace(r"\*", r"[^/]+")
    return re.match(f"^{escaped}(?:/.*)?$", path) is not None


def match_module(profile: dict[str, Any], config: dict[str, Any]) -> tuple[int, list[str], list[str]]:
    score = 0
    reasons: list[str] = []
    signals: list[str] = []
    path = profile["path"]
    search_text = profile["search_text"]
    category_text = f"{profile['business_category']}/{profile['group_name']}/{profile['document_type']}"

    matched_prefix = next((prefix for prefix in config["path_prefixes"] if wildcard_match(path, prefix)), "")
    if matched_prefix:
        score += 6
        signals.append("path")
        reasons.append(f"路径命中 `{matched_prefix}`")

    keyword_hits = [keyword for keyword in config["keywords"] if keyword and keyword in search_text]
    if keyword_hits:
        score += min(6, len(keyword_hits) * 2)
        signals.append("keyword")
        reasons.append(f"关键词命中 {keyword_hits[:4]}")

    category_hits = [category for category in config["categories"] if category and category in category_text]
    if category_hits:
        score += 3
        signals.append("category")
        reasons.append(f"业务分类命中 {category_hits[:3]}")

    if profile["material_tier"] == "项目素材":
        score += 1
    if profile["is_final_version"]:
        score += 1
    return score, reasons, signals


def score_to_confidence(score: int) -> float:
    if score >= 13:
        return 0.95
    if score >= 9:
        return 0.82
    if score >= 6:
        return 0.68
    if score >= 3:
        return 0.52
    return 0.20


def analyze_modules(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    profile_matches: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rows: list[dict[str, Any]] = []

    for config in MODULE_CONFIGS:
        candidates: list[dict[str, Any]] = []
        for profile in profiles:
            score, reasons, signals = match_module(profile, config)
            if score <= 0:
                continue
            candidate = {
                "card_id": profile["card_id"],
                "title": profile["title"],
                "path": profile["path"],
                "score": score,
                "confidence": score_to_confidence(score),
                "usage_mode": config["usage_mode"],
                "reasons": reasons,
                "signals": signals,
                "module_name": config["module_name"],
                "module_code": config["module_code"],
            }
            candidates.append(candidate)
            profile_matches[profile["card_id"]].append(candidate)

        candidates.sort(key=lambda entry: (-entry["score"], entry["title"], entry["card_id"]))
        top_candidates = candidates[:6]
        mapping_reason = "；".join(top_candidates[0]["reasons"]) if top_candidates else "当前未命中显式候选，需依赖后续全文搜索回退。"
        mapping_source = "+".join(top_candidates[0]["signals"]) if top_candidates else "path_rule"
        confidence = f"{top_candidates[0]['confidence']:.2f}" if top_candidates else "0.20"
        needs_human_confirm = (
            not top_candidates
            or len(top_candidates) != 1
            or config["usage_mode"] in {"fill_table", "extract_fields", "extract_image"}
        )
        rows.append(
            {
                "module_name": config["module_name"],
                "module_code": config["module_code"],
                "source_path_prefix": "；".join(config["path_prefixes"]),
                "business_category": "、".join(config["categories"]),
                "candidate_card_ids": [entry["card_id"] for entry in top_candidates],
                "candidate_cards": top_candidates,
                "usage_mode": config["usage_mode"],
                "mapping_source": mapping_source,
                "confidence": confidence,
                "needs_human_confirm": "yes" if needs_human_confirm else "no",
                "mapping_reason": mapping_reason,
                "fallback_scope": config["fallback_scope"],
                "missing_hint": config["missing_hint"],
            }
        )

    for profile in profiles:
        matches = sorted(
            profile_matches.get(profile["card_id"], []),
            key=lambda entry: (-entry["score"], entry["module_code"]),
        )
        profile["module_matches"] = matches[:5]
        profile["applicable_modules"] = [entry["module_name"] for entry in matches[:5]]
        profile["applicable_chapters"] = infer_applicable_chapters(profile)
        profile["chapter_keywords"] = infer_chapter_keywords(profile)
        if profile["ext"] not in IMAGE_EXTS and matches:
            preferred_usage = matches[0]["usage_mode"]
            if preferred_usage in {"fill_table", "extract_fields", "reference_only"}:
                profile["usage_mode"] = preferred_usage
        profile["needs_human_confirm"] = bool(
            profile["needs_human_confirm"] or len(matches) != 1 or not matches
        )
    return rows


def build_inventory_node(profiles: list[dict[str, Any]], inventory: dict[str, Any]) -> dict[str, Any]:
    lines = [
        "# 01-素材总表",
        "",
        "商务标素材总表面向 AI 先做全量感知：先知道有什么，再决定挂整件、抽字段、摘图还是填表。",
        "",
        f"- 原始材料总数：{inventory.get('sourceInventoryTotal') or inventory.get('total') or len(profiles)}",
        f"- 当前纳入商务标 Wiki 的素材数：{len(profiles)}",
        f"- 已解析 Word：{inventory.get('parsedDocxTotal', 0)}",
        "",
        "| 素材 | 层级 | AI身份 | 业务分类 | 推荐模块 | 清洗策略 | 证据类型 | 原始路径 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    if not profiles:
        lines.append("| 待补料 | - | - | 当前未检出商务标真实素材 | - | - | - | - |")
    for profile in profiles:
        lines.append(
            "| {title} | {tier} | {identity} | {category} | {modules} | {strategy} | {evidence} | `{path}` |".format(
                title=md_escape(profile["title"]),
                tier=md_escape(profile["material_tier"]),
                identity=md_escape(profile["identity_scope"]),
                category=md_escape(profile["business_category"]),
                modules=md_escape("、".join(profile["applicable_modules"][:3]) or "待映射"),
                strategy=md_escape(profile["cleaning_strategy"]),
                evidence=md_escape(profile["evidence_type"]),
                path=md_escape(profile["path"]),
            )
        )
    return node("01-素材总表", "\n".join(lines) + "\n", ["商务标", "素材总表"])


def build_mapping_detail_node(row: dict[str, Any]) -> dict[str, Any]:
    candidates = row["candidate_cards"]
    lines = [
        f"# {row['module_name']}",
        "",
        "| field | value |",
        "|---|---|",
        f"| module_name | {md_escape(row['module_name'])} |",
        f"| module_code | {md_escape(row['module_code'])} |",
        f"| source_path_prefix | {md_escape(row['source_path_prefix'])} |",
        f"| business_category | {md_escape(row['business_category'])} |",
        f"| candidate_card_ids | {md_escape('、'.join(row['candidate_card_ids']) or '[]')} |",
        f"| usage_mode | {md_escape(row['usage_mode'])} |",
        f"| mapping_source | {md_escape(row['mapping_source'])} |",
        f"| confidence | {md_escape(row['confidence'])} |",
        f"| needs_human_confirm | {md_escape(row['needs_human_confirm'])} |",
        f"| mapping_reason | {md_escape(row['mapping_reason'])} |",
        f"| fallback_scope | {md_escape(row['fallback_scope'])} |",
        f"| missing_hint | {md_escape(row['missing_hint'])} |",
    ]
    lines.extend(["", "## 候选证据卡片", "", "| card_id | title | usage_mode | confidence | path |", "|---|---|---|---|---|"])
    if not candidates:
        lines.append("| - | 当前无候选 | - | - | - |")
    for candidate in candidates:
        lines.append(
            f"| {md_escape(candidate['card_id'])} | {md_escape(candidate['title'])} | {md_escape(candidate['usage_mode'])} | {candidate['confidence']:.2f} | `{md_escape(candidate['path'])}` |"
        )
    return node(row["module_name"], "\n".join(lines) + "\n", ["商务标", "模板模块映射"])


def build_mapping_node(rows: list[dict[str, Any]]) -> dict[str, Any]:
    lines = [
        "# 02-模板模块映射表",
        "",
        "本表回答的是：某个商务模板模块，优先去哪些素材路径、找哪些证据卡片、以什么方式使用。",
        "映射优先由路径规则约束，再结合标题/Heading/关键词辅助判断；若映射未命中，后续 Agent 必须按 fallback_scope 在当前身份可读范围内继续搜索。",
        "",
        "| module_name | module_code | source_path_prefix | business_category | candidate_card_ids | usage_mode | mapping_source | confidence | needs_human_confirm | mapping_reason | fallback_scope | missing_hint |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {module_name} | {module_code} | {source_path_prefix} | {business_category} | {candidate_card_ids} | {usage_mode} | {mapping_source} | {confidence} | {needs_human_confirm} | {mapping_reason} | {fallback_scope} | {missing_hint} |".format(
                module_name=md_escape(row["module_name"]),
                module_code=md_escape(row["module_code"]),
                source_path_prefix=md_escape(row["source_path_prefix"]),
                business_category=md_escape(row["business_category"]),
                candidate_card_ids=md_escape("、".join(row["candidate_card_ids"]) or "[]"),
                usage_mode=md_escape(row["usage_mode"]),
                mapping_source=md_escape(row["mapping_source"]),
                confidence=md_escape(row["confidence"]),
                needs_human_confirm=md_escape(row["needs_human_confirm"]),
                mapping_reason=md_escape(row["mapping_reason"]),
                fallback_scope=md_escape(row["fallback_scope"]),
                missing_hint=md_escape(row["missing_hint"]),
            )
        )
    return node(
        "02-模板模块映射表",
        "\n".join(lines) + "\n",
        ["商务标", "模板模块映射表"],
        [build_mapping_detail_node(row) for row in rows],
    )


def build_card_markdown(profile: dict[str, Any]) -> str:
    lines = [
        f"# {profile['title']}",
        "",
        "## 基础字段",
        f"- card_id: {profile['card_id']}",
        f"- material_id: {profile['material_id']}",
        f"- title: {profile['title']}",
        f"- path: {profile['path']}",
        f"- cleaned_file_name: {profile['cleaned_file_name']}",
        f"- material_tier: {profile['material_tier']}",
        f"- business_category: {profile['business_category']}",
        f"- evidence_type: {profile['evidence_type']}",
        "",
        "## 身份字段",
        f"- identity_scope: {profile['identity_scope']}",
        f"- customer_id: {profile['customer_id']}",
        f"- customer_name: {profile['customer_name']}",
        f"- project_id: {profile['project_id']}",
        f"- project_code: {profile['project_code']}",
        "",
        "## 决策字段",
        f"- evidence_topic: {profile.get('evidence_topic') or '待识别'}",
        f"- applicable_modules: {'、'.join(profile['applicable_modules']) or '待回退检索'}",
        f"- applicable_chapters: {'、'.join(profile.get('applicable_chapters') or []) or '待映射'}",
        f"- chapter_keywords: {'、'.join(profile.get('chapter_keywords') or []) or '待抽取'}",
        f"- usage_mode: {profile['usage_mode']}",
        f"- priority_score: {profile['priority_score']}",
        f"- needs_human_confirm: {'yes' if profile['needs_human_confirm'] else 'no'}",
        f"- retrieval_source: {profile['retrieval_source']}",
        "",
        "## 内容字段",
        f"- key_fields: {'；'.join(profile['key_fields']) or '待抽取'}",
        f"- keywords: {'、'.join(profile['keywords']) or profile['title']}",
        f"- document_type: {profile['document_type']}",
        f"- summary: {profile['summary']}",
        "",
        "## 有效性字段",
        f"- issuer: {profile['issuer'] or '待识别'}",
        f"- document_number: {profile['document_number'] or '待识别'}",
        f"- issue_date: {profile['issue_date'] or '待核验'}",
        f"- expiry_date: {profile['expiry_date'] or '待核验'}",
        f"- validity_status: {profile['validity_status']}",
        f"- last_verified_at: {profile['last_verified_at'] or '待核验'}",
        f"- turbine_models: {'、'.join(profile.get('turbine_models') or []) or '待识别'}",
        f"- components: {'、'.join(profile.get('components') or []) or '待识别'}",
        "",
        "## 风险字段",
        f"- applicable_conditions: {profile['applicable_conditions']}",
        f"- risk_notes: {profile['risk_notes']}",
        f"- ocr_status: {profile.get('ocr_status') or 'n/a'}",
        f"- ocr_source_type: {profile.get('ocr_source_type') or 'n/a'}",
        f"- ocr_confidence: {profile['ocr_confidence']}",
        f"- is_final_version: {'yes' if profile['is_final_version'] else 'no'}",
        f"- source_pages: {profile['source_pages']}",
        f"- segment_count: {len(profile.get('evidence_segments') or [])}",
        "",
        "## 证据切片",
        "| segment_id | segment_title | segment_type | segment_scope | segment_source_pages | segment_summary | segment_keywords |",
        "|---|---|---|---|---|---|---|",
    ]
    for segment in profile.get("evidence_segments") or []:
        lines.append(
            "| {segment_id} | {segment_title} | {segment_type} | {segment_scope} | {segment_source_pages} | {segment_summary} | {segment_keywords} |".format(
                **{key: md_escape(segment.get(key, "")) for key in (
                    "segment_id",
                    "segment_title",
                    "segment_type",
                    "segment_scope",
                    "segment_source_pages",
                    "segment_summary",
                    "segment_keywords",
                )}
            )
        )
    lines.extend([
        "",
        "## OCR识别摘要",
        profile.get("ocr_text_excerpt") or "- 未获得 OCR 文本；如为图片、扫描 PDF 或 Word 内嵌证书，请人工核验。",
        "",
        "## 清洗策略",
        f"- cleaning_strategy: {profile['cleaning_strategy']}",
    ])
    return "\n".join(lines) + "\n"


def sort_key(title: str) -> tuple[int, str]:
    prefix = title.split("-", 1)[0]
    return (int(prefix) if prefix.isdigit() else 999, title)


def build_tree_container_markdown(title: str, count: int, path_hint: str) -> str:
    return (
        f"# {title}\n\n"
        f"该节点对应原始素材库路径层级 `{path_hint}` ，当前承载证据卡片 {count} 张。"
        "后续 Agent 先按身份过滤，再向下定位具体证据卡片。\n"
    )


def build_profile_tree(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    tree: dict[str, Any] = {"children": {}, "cards": []}
    for profile in profiles:
        tier = profile["material_tier"]
        cursor = tree["children"].setdefault(tier, {"children": {}, "cards": []})
        if tier == "通用素材":
            segments = [profile["group_name"]]
            if profile.get("subgroup_name"):
                segments.append(profile["subgroup_name"])
        else:
            segments = [profile["bucket_name"] or ("待补客户" if tier == "客户素材" else "待补项目"), profile["group_name"]]
        for segment in segments:
            cursor = cursor["children"].setdefault(segment, {"children": {}, "cards": []})
        cursor["cards"].append(profile)
    return tree


def count_tree_cards(tree: dict[str, Any]) -> int:
    total = len(tree.get("cards", []))
    for child in tree.get("children", {}).values():
        total += count_tree_cards(child)
    return total


def render_tree_node(title: str, subtree: dict[str, Any], path_hint: str) -> dict[str, Any]:
    children: list[dict[str, Any]] = []
    for child_title in sorted(subtree.get("children", {}).keys(), key=sort_key):
        child = subtree["children"][child_title]
        children.append(render_tree_node(child_title, child, f"{path_hint}/{child_title}".strip("/")))
    for profile in sorted(subtree.get("cards", []), key=lambda entry: entry["title"]):
        children.append(node(profile["title"], build_card_markdown(profile), ["商务标", "证据卡片", profile["material_tier"]]))
    return node(title, build_tree_container_markdown(title, count_tree_cards(subtree), path_hint), ["商务标", "证据卡片", title], children)


def build_card_framework_node() -> dict[str, Any]:
    common_children = []
    for name in COMMON_GROUPS:
        subgroups = SPECIAL_COMMON_SUBGROUPS.get(name) or []
        subgroup_children = [
            node(subgroup, build_tree_container_markdown(subgroup, 0, f"通用素材/{name}/{subgroup}"), ["商务标", "证据卡片", "通用素材"])
            for subgroup in subgroups
        ]
        common_children.append(
            node(
                name,
                build_tree_container_markdown(name, 0, f"通用素材/{name}"),
                ["商务标", "证据卡片", "通用素材"],
                subgroup_children,
            )
        )
    customer_children = [node(name, build_tree_container_markdown(name, 0, f"客户素材/待补客户/{name}"), ["商务标", "证据卡片", "客户素材"]) for name in CUSTOM_GROUPS]
    project_children = [node(name, build_tree_container_markdown(name, 0, f"项目素材/待补项目/{name}"), ["商务标", "证据卡片", "项目素材"]) for name in CUSTOM_GROUPS]
    return node(
        "03-证据卡片",
        "# 03-证据卡片\n\n当前没有真实商务标素材，先保留原始素材库镜像结构，等待上传后自动生成证据卡片。\n",
        ["商务标", "证据卡片"],
        [
            node("通用素材", build_tree_container_markdown("通用素材", 0, "通用素材"), ["商务标", "证据卡片", "通用素材"], common_children),
            node("客户素材", build_tree_container_markdown("客户素材", 0, "客户素材"), ["商务标", "证据卡片", "客户素材"], [node("待补客户", build_tree_container_markdown("待补客户", 0, "客户素材/待补客户"), ["商务标", "证据卡片", "客户素材"], customer_children)]),
            node("项目素材", build_tree_container_markdown("项目素材", 0, "项目素材"), ["商务标", "证据卡片", "项目素材"], [node("待补项目", build_tree_container_markdown("待补项目", 0, "项目素材/待补项目"), ["商务标", "证据卡片", "项目素材"], project_children)]),
        ],
    )


def build_cards_node(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    if not profiles:
        return build_card_framework_node()
    tree = build_profile_tree(profiles)
    tier_children: list[dict[str, Any]] = []
    for tier in ("通用素材", "客户素材", "项目素材"):
        subtree = tree["children"].get(tier, {"children": {}, "cards": []})
        tier_children.append(render_tree_node(tier, subtree, tier))
    return node(
        "03-证据卡片",
        "# 03-证据卡片\n\n证据卡片不复制原文，只记录证据的身份、路径、用法、有效性与风险，且目录结构尽量镜像原始素材库。\n",
        ["商务标", "证据卡片"],
        tier_children,
    )


def candidate_sources_for_module(rows: list[dict[str, Any]], module_code: str) -> str:
    row = next((entry for entry in rows if entry["module_code"] == module_code), None)
    if not row:
        return "[]"
    values = [f"{candidate['card_id']}:{candidate['title']}" for candidate in row["candidate_cards"][:3]]
    return "；".join(values) or "[]"


def todo_row(
    todo_id: str,
    todo_type: str,
    field_name: str,
    module_name: str,
    expected_value_type: str,
    candidate_sources: str,
    is_required: str,
    blocking_level: str,
    reason: str,
    owner: str,
    current_value: str = "",
    suggested_value: str = "",
    status: str = "pending",
    needs_human_confirm: str = "yes",
) -> dict[str, str]:
    return {
        "todo_id": todo_id,
        "todo_type": todo_type,
        "field_name": field_name,
        "module_name": module_name,
        "expected_value_type": expected_value_type,
        "current_value": current_value,
        "suggested_value": suggested_value,
        "candidate_sources": candidate_sources,
        "is_required": is_required,
        "status": status,
        "needs_human_confirm": needs_human_confirm,
        "blocking_level": blocking_level,
        "reason": reason,
        "owner": owner,
    }


def build_todo_groups(rows: list[dict[str, Any]], profiles: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    project_profile = next((profile for profile in profiles if profile["material_tier"] == "项目素材"), None)
    customer_profile = next((profile for profile in profiles if profile["material_tier"] == "客户素材"), None)
    groups = {
        "01-项目基础变量": [
            todo_row("todo-001", "project_variable", "project_name", "02-投标函与授权模块", "string", candidate_sources_for_module(rows, "BM-02"), "yes", "high", "投标函、授权书、附件9 中通常都要回填项目名称。", "商务标编制人", suggested_value=project_profile["project_code"] if project_profile else ""),
            todo_row("todo-002", "project_variable", "project_code", "02-投标函与授权模块", "string", candidate_sources_for_module(rows, "BM-02"), "yes", "high", "项目编号是商务响应文件和后续命名的重要主键。", "商务标编制人", suggested_value=project_profile["project_code"] if project_profile else ""),
            todo_row("todo-003", "project_variable", "customer_name", "02-投标函与授权模块", "string", candidate_sources_for_module(rows, "BM-02"), "yes", "high", "客户名称需驱动客户素材命中与投标函称谓。", "商务标编制人", suggested_value=customer_profile["customer_name"] if customer_profile else ""),
            todo_row("todo-004", "project_variable", "authorized_representative", "02-投标函与授权模块", "string", candidate_sources_for_module(rows, "BM-02"), "yes", "high", "授权代表姓名/职务需要从授权书或项目底稿确认。", "商务标编制人"),
        ],
        "02-金额与时效变量": [
            todo_row("todo-101", "amount_or_term", "bid_price", "03-投标价格表模块", "number", candidate_sources_for_module(rows, "BM-03"), "yes", "high", "投标价格必须由本项目报价底稿回填，不允许编造。", "商务标编制人"),
            todo_row("todo-102", "amount_or_term", "opening_price", "10-开标价格表模块", "number", candidate_sources_for_module(rows, "BM-10"), "yes", "high", "开标价格表通常与投标价格表关联，但仍需单独确认。", "商务标编制人"),
            todo_row("todo-103", "amount_or_term", "bid_security_amount", "06-投标保证金模块", "number", candidate_sources_for_module(rows, "BM-06"), "yes", "high", "保证金金额、形式、到账状态需要与回单/保函核对。", "商务标编制人"),
            todo_row("todo-104", "amount_or_term", "bid_validity_period", "02-投标函与授权模块", "string", candidate_sources_for_module(rows, "BM-02"), "yes", "high", "投标有效期需与招标要求一致。", "商务标编制人"),
        ],
        "03-证据选择与版本确认": [
            todo_row("todo-201", "evidence_selection", "qualification_package", "08-资格证明文件模块（附件7）", "card_list", candidate_sources_for_module(rows, "BM-08"), "yes", "high", "需确定附件7 最终挂载的资质、认证、信用、资信材料。", "商务标编制人"),
            todo_row("todo-202", "evidence_selection", "performance_package", "09-业绩情况表模块（附件7I）", "card_list", candidate_sources_for_module(rows, "BM-09"), "yes", "high", "需按招标条件筛选业绩资产池中的合同/通知书/运行证明。", "商务标编制人"),
            todo_row("todo-203", "evidence_selection", "certificate_validity_check", "08-资格证明文件模块（附件7）", "check", candidate_sources_for_module(rows, "BM-08"), "yes", "medium", "证书、截图、资信证明的有效时间需要单独核验。", "商务标编制人"),
            todo_row("todo-204", "evidence_selection", "final_version_check", "11-其他说明与承诺模块（附件9）", "check", candidate_sources_for_module(rows, "BM-11"), "yes", "medium", "项目定制响应件需要确认是否为终版/盖章版。", "商务标编制人"),
        ],
        "04-合规与页码确认": [
            todo_row("todo-301", "compliance_check", "deviation_response", "05-商务偏差表模块", "check", candidate_sources_for_module(rows, "BM-05"), "yes", "high", "商务偏差表必须与合同条款响应一致。", "商务标编制人"),
            todo_row("todo-302", "compliance_check", "decisive_item_response", "12-否决项与符合性响应模块", "check", candidate_sources_for_module(rows, "BM-12"), "yes", "high", "否决项不得漏答，且必须找到直接支撑证据。", "商务标编制人"),
            todo_row("todo-303", "page_index", "attachment_page_index", "08-资格证明文件模块（附件7）", "check", candidate_sources_for_module(rows, "BM-08"), "yes", "medium", "证书扫描件、回单、保函等附件在最终装订前要回填页码索引。", "商务标编制人"),
            todo_row("todo-304", "page_index", "image_quality_check", "03-证据卡片", "check", "03-证据卡片/图片类素材", "yes", "medium", "图片/扫描件需检查清晰度、方向和盖章完整性。", "商务标编制人"),
        ],
    }
    return groups


def build_todo_group_node(title: str, rows: list[dict[str, str]]) -> dict[str, Any]:
    lines = [
        f"# {title}",
        "",
        "| todo_id | todo_type | field_name | module_name | expected_value_type | current_value | suggested_value | candidate_sources | is_required | status | needs_human_confirm | blocking_level | reason | owner |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {todo_id} | {todo_type} | {field_name} | {module_name} | {expected_value_type} | {current_value} | {suggested_value} | {candidate_sources} | {is_required} | {status} | {needs_human_confirm} | {blocking_level} | {reason} | {owner} |".format(
                **{key: md_escape(value) for key, value in row.items()}
            )
        )
    return node(title, "\n".join(lines) + "\n", ["商务标", "待填写与待确认清单", title])


def build_todo_node(rows: list[dict[str, Any]], profiles: list[dict[str, Any]]) -> dict[str, Any]:
    groups = build_todo_groups(rows, profiles)
    total = sum(len(entries) for entries in groups.values())
    pending = sum(1 for entries in groups.values() for entry in entries if entry["status"] == "pending")
    lines = [
        "# 04-待填写与待确认清单",
        "",
        "本清单只标记运行期必须确认的变量、证据选择和合规动作；不在 Wiki 阶段代填事实。",
        "",
        f"- 待办总数：{total}",
        f"- 当前 pending：{pending}",
        f"- 阻塞级 high：{sum(1 for entries in groups.values() for entry in entries if entry['blocking_level'] == 'high')}",
    ]
    return node(
        "04-待填写与待确认清单",
        "\n".join(lines) + "\n",
        ["商务标", "待填写与待确认清单"],
        [build_todo_group_node(title, entries) for title, entries in groups.items()],
    )


def build_rules_groups() -> dict[str, list[dict[str, str]]]:
    return {
        "01-身份过滤规则": [
            {
                "rule_id": "rule-001",
                "rule_group": "identity_filter",
                "rule_name": "项目优先命中",
                "condition": "存在 project_id/project_code 命中的项目素材",
                "action": "优先使用项目素材；仅在项目素材缺失时回退客户素材/通用素材",
                "priority": "100",
                "enabled": "yes",
                "severity": "high",
                "human_readable_note": "商务标项目响应件优先级最高，避免误用历史客户稿。",
            },
            {
                "rule_id": "rule-002",
                "rule_group": "identity_filter",
                "rule_name": "客户限定读取",
                "condition": "素材 identity_scope=customer",
                "action": "必须校验 customer_id/customer_name 命中后才能读取",
                "priority": "90",
                "enabled": "yes",
                "severity": "high",
                "human_readable_note": "客户关系证明、框架协议不能跨客户复用。",
            },
        ],
        "02-证据优先级规则": [
            {
                "rule_id": "rule-101",
                "rule_group": "evidence_priority",
                "rule_name": "终版优先",
                "condition": "同类素材存在多个版本",
                "action": "优先选择 is_final_version=yes 的证据卡片；否则进入人工确认",
                "priority": "85",
                "enabled": "yes",
                "severity": "medium",
                "human_readable_note": "盖章版、定稿版优先，避免用过程稿生成正式投标件。",
            },
            {
                "rule_id": "rule-102",
                "rule_group": "evidence_priority",
                "rule_name": "有效期先行",
                "condition": "证书/资信/截图存在有效时间",
                "action": "优先选择 validity_status=valid 的卡片；pending_verify 必须人工复核",
                "priority": "88",
                "enabled": "yes",
                "severity": "high",
                "human_readable_note": "商务标证据经常败在有效期，不能只看标题。",
            },
        ],
        "03-模块使用方式规则": [
            {
                "rule_id": "rule-201",
                "rule_group": "module_usage",
                "rule_name": "填表类禁止整篇拼接",
                "condition": "usage_mode=fill_table",
                "action": "只允许抽取字段/表格数据回填，不允许整件正文拼接",
                "priority": "92",
                "enabled": "yes",
                "severity": "high",
                "human_readable_note": "报价表、规格表、偏差表都应该回填数据，不是粘一整份源文件。",
            },
            {
                "rule_id": "rule-202",
                "rule_group": "module_usage",
                "rule_name": "图片类直接挂载",
                "condition": "usage_mode=extract_image 或 evidence_type=scan_image",
                "action": "保留原件并按图片/扫描件挂载，不触发清洗稿引用",
                "priority": "80",
                "enabled": "yes",
                "severity": "medium",
                "human_readable_note": "证书图片、回单截图主要靠原件挂载，不应转写成文本后替代原件。",
            },
        ],
        "04-合规与否决项规则": [
            {
                "rule_id": "rule-301",
                "rule_group": "compliance",
                "rule_name": "否决项必须有直接证据",
                "condition": "模块属于否决项与符合性响应",
                "action": "映射表未命中时必须回退全文搜索，并将未命中项写入待确认清单",
                "priority": "99",
                "enabled": "yes",
                "severity": "high",
                "human_readable_note": "否决项不能靠推断，找不到证据就必须显式报缺口。",
            },
            {
                "rule_id": "rule-302",
                "rule_group": "compliance",
                "rule_name": "禁止编造金额与承诺",
                "condition": "缺少本项目报价、保证金、承诺原件",
                "action": "保持 pending，不得自动生成事实性内容",
                "priority": "100",
                "enabled": "yes",
                "severity": "high",
                "human_readable_note": "商务标最核心的是金额与承诺，缺失时宁可报缺口也不编造。",
            },
        ],
        "05-OCR与图片处理规则": [
            {
                "rule_id": "rule-401",
                "rule_group": "ocr_image",
                "rule_name": "图片不触发清洗",
                "condition": "上传文件扩展名属于图片",
                "action": "仅保留原件，证据卡片记录 extract_image 用法与人工核验要求",
                "priority": "85",
                "enabled": "yes",
                "severity": "medium",
                "human_readable_note": "这是商务标与技术标的重要差异：很多图片类证据只需要挂原件。",
            },
            {
                "rule_id": "rule-402",
                "rule_group": "ocr_image",
                "rule_name": "扫描件先验真再引用",
                "condition": "evidence_type=pdf_attachment 或 scan_image",
                "action": "引用前检查清晰度、方向、页边、签章和有效期",
                "priority": "82",
                "enabled": "yes",
                "severity": "medium",
                "human_readable_note": "扫描件常见问题不是找不到，而是可用性差。",
            },
        ],
        "06-页码索引回填规则": [
            {
                "rule_id": "rule-501",
                "rule_group": "page_index",
                "rule_name": "附件页码后补",
                "condition": "最终生成的投标文件已装订或导出 PDF",
                "action": "将证书、回单、保函、截图对应页码回填到清单与索引页",
                "priority": "70",
                "enabled": "yes",
                "severity": "low",
                "human_readable_note": "页码不是建库时就确定，而是在最终排版后回填。",
            },
            {
                "rule_id": "rule-502",
                "rule_group": "page_index",
                "rule_name": "图片页码人工复核",
                "condition": "附件中包含大量图片或扫描件",
                "action": "优先人工核对页码与目录对应关系，避免 OCR 误页",
                "priority": "68",
                "enabled": "yes",
                "severity": "low",
                "human_readable_note": "图片类材料页码稳定性较弱，建议最终人工复核。",
            },
        ],
    }


def build_rules_group_node(title: str, rows: list[dict[str, str]]) -> dict[str, Any]:
    lines = [
        f"# {title}",
        "",
        "| rule_id | rule_group | rule_name | condition | action | priority | enabled | severity | human_readable_note |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {rule_id} | {rule_group} | {rule_name} | {condition} | {action} | {priority} | {enabled} | {severity} | {human_readable_note} |".format(
                **{key: md_escape(value) for key, value in row.items()}
            )
        )
    return node(title, "\n".join(lines) + "\n", ["商务标", "使用规则", title])


def build_rules_node() -> dict[str, Any]:
    groups = build_rules_groups()
    lines = [
        "# 05-使用规则",
        "",
        "后续 Agent 使用商务标 Wiki 时，必须先看身份过滤，再看模板模块映射，最后决定挂整件、摘图、抽字段或填表。",
        "若映射表没有完全覆盖，允许按 fallback_scope 在当前身份可读范围内全文搜索，但不能突破身份边界，也不能编造事实。",
    ]
    return node(
        "05-使用规则",
        "\n".join(lines) + "\n",
        ["商务标", "使用规则"],
        [build_rules_group_node(title, entries) for title, entries in groups.items()],
    )


def build_business_wiki_blueprint(inventory: dict[str, Any], root_title: str = "商务标Wiki（自动生成）") -> dict[str, Any]:
    raw_items = [item for item in inventory.get("items") or [] if isinstance(item, dict)]
    profiles = [profile_material(item) for item in raw_items]
    profiles.sort(key=lambda entry: (entry["material_tier"], entry["bucket_name"], entry["group_name"], entry["title"]))
    mapping_rows = analyze_modules(profiles)
    summary = (
        f"已生成商务标 Wiki：素材 {len(profiles)} 条，结构为素材总表/模板模块映射表/证据卡片/待填写与待确认清单/使用规则。"
        if profiles
        else "已生成商务标 Wiki 待补料框架：当前无真实素材，保留素材总表/模板模块映射表/证据卡片/待填写与待确认清单/使用规则。"
    )
    return {
        "summary": summary,
        "rootTitle": root_title,
        "nodes": [
            build_inventory_node(profiles, inventory),
            build_mapping_node(mapping_rows),
            build_cards_node(profiles),
            build_todo_node(mapping_rows, profiles),
            build_rules_node(),
        ],
    }
