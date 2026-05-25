from __future__ import annotations

from pathlib import PurePosixPath

from app.services.bid_type import BUSINESS_BID_TYPE, TECHNICAL_BID_TYPE


PLATFORM_WIKI_SECTION_TITLES = {
    "平台级Wiki说明",
    "章节骨架",
    "装配规则",
    "同义词映射",
    "通用卡片",
    "项目级Wiki模板",
}

MATERIAL_TIER_VALUES = {"standard", "customer", "project"}
MATERIAL_TIER_LABELS = {
    "standard": "通用素材",
    "customer": "客户素材",
    "project": "项目素材",
}
BUSINESS_MATERIAL_KIND_VALUES = {"fixed", "other"}
BUSINESS_MATERIAL_KIND_LABELS = {
    "fixed": "固定素材",
    "other": "其他",
}
CLEANABLE_MATERIAL_SUFFIXES = {".pdf", ".xlsx", ".xls", ".xlsm", ".docx", ".doc"}
ORIGINAL_ONLY_MATERIAL_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".ds_store"}
MATERIAL_LIBRARY_ALLOWED_SUFFIXES = CLEANABLE_MATERIAL_SUFFIXES | ORIGINAL_ONLY_MATERIAL_SUFFIXES | {".md"}
RAW_MATERIAL_ROOTS = (
    {"name": TECHNICAL_BID_TYPE, "tier": "standard", "bid_type": TECHNICAL_BID_TYPE, "sort_order": 1},
    {"name": BUSINESS_BID_TYPE, "tier": "standard", "bid_type": BUSINESS_BID_TYPE, "sort_order": 2},
)
RAW_MATERIAL_ROOT_TIERS = {str(item["name"]): str(item["tier"]) for item in RAW_MATERIAL_ROOTS}
TECHNICAL_TIER_FOLDERS = (
    {"name": "通用素材", "tier": "standard", "sort_order": 1, "customer_name": "平台标准"},
    {"name": "客户素材", "tier": "customer", "sort_order": 2},
    {"name": "项目素材", "tier": "project", "sort_order": 3},
)
BUSINESS_TIER_FOLDERS = TECHNICAL_TIER_FOLDERS
RAW_MATERIAL_PROTECTED_BASE_FOLDER_PATHS = {
    TECHNICAL_BID_TYPE,
    BUSINESS_BID_TYPE,
}
RAW_MATERIAL_DEFAULT_TIER_FOLDER_PATHS = {
    f"{root['name']}/{folder['name']}"
    for root in RAW_MATERIAL_ROOTS
    for folder in TECHNICAL_TIER_FOLDERS
}
BUSINESS_STANDARD_SUBFOLDERS = (
    {
        "name": "01-资质合规库",
        "tier": "standard",
        "sort_order": 1,
    },
    {
        "name": "02-企业能力库",
        "tier": "standard",
        "sort_order": 2,
    },
    {
        "name": "03-业绩资产池",
        "tier": "standard",
        "sort_order": 3,
    },
    {
        "name": "04-财务资料库",
        "tier": "standard",
        "sort_order": 4,
    },
    {
        "name": "05-专题证书库",
        "tier": "standard",
        "sort_order": 5,
        "children": (
            {"name": "01-机型认证证书", "tier": "standard", "sort_order": 1},
            {"name": "02-大部件型式认证证书", "tier": "standard", "sort_order": 2},
        ),
    },
    {
        "name": "06-通用模板底稿库",
        "tier": "standard",
        "sort_order": 6,
    },
)
BUSINESS_CUSTOMIZED_SUBFOLDERS = (
    {
        "name": "01-客户关系与专项证明",
        "tier": "customer",
        "sort_order": 1,
    },
    {
        "name": "02-商务响应文件",
        "tier": "customer",
        "sort_order": 2,
    },
    {
        "name": "03-模板底稿与过程文件",
        "tier": "customer",
        "sort_order": 3,
    },
)


def _business_standard_protected_folder_paths() -> set[str]:
    protected: set[str] = set()
    base_path = f"{BUSINESS_BID_TYPE}/通用素材"
    for spec in BUSINESS_STANDARD_SUBFOLDERS:
        folder_path = f"{base_path}/{spec['name']}"
        protected.add(folder_path)
        for child in spec.get("children") or ():
            protected.add(f"{folder_path}/{child['name']}")
    return protected


RAW_MATERIAL_PROTECTED_FOLDER_PATHS = (
    RAW_MATERIAL_PROTECTED_BASE_FOLDER_PATHS | _business_standard_protected_folder_paths()
)
BUSINESS_CUSTOMIZED_PROTECTED_FOLDER_NAMES = {str(spec["name"]) for spec in BUSINESS_CUSTOMIZED_SUBFOLDERS}


def material_suffix(name: str) -> str:
    if str(name or "").lower() == ".ds_store":
        return ".ds_store"
    return PurePosixPath(name).suffix.lower()


def ext_of(name: str) -> str:
    return material_suffix(name).lstrip(".") or "file"


def is_raw_material_protected_folder_path(folder_path: str) -> bool:
    normalized = str(folder_path or "").replace("\\", "/").strip("/")
    if normalized in RAW_MATERIAL_PROTECTED_FOLDER_PATHS:
        return True
    parts = [part for part in normalized.split("/") if part]
    return (
        len(parts) == 4
        and parts[0] == BUSINESS_BID_TYPE
        and parts[1] in {"客户素材", "项目素材"}
        and parts[3] in BUSINESS_CUSTOMIZED_PROTECTED_FOLDER_NAMES
    )


def business_customized_tier_from_path(folder_path: str) -> str:
    parts = [part for part in str(folder_path or "").replace("\\", "/").strip("/").split("/") if part]
    if len(parts) == 3 and parts[:2] == [BUSINESS_BID_TYPE, "客户素材"]:
        return "customer"
    if len(parts) == 3 and parts[:2] == [BUSINESS_BID_TYPE, "项目素材"]:
        return "project"
    return ""


def business_customized_child_tier_for_parent_path(parent_path: str) -> str:
    parts = [part for part in str(parent_path or "").replace("\\", "/").strip("/").split("/") if part]
    if len(parts) == 2 and parts == [BUSINESS_BID_TYPE, "客户素材"]:
        return "customer"
    if len(parts) == 2 and parts == [BUSINESS_BID_TYPE, "项目素材"]:
        return "project"
    return ""


def canonical_technical_material_path(path: str) -> str:
    parts = [part for part in str(path or "").replace("\\", "/").strip("/").split("/") if part]
    if not parts:
        return ""
    if parts[0] == TECHNICAL_BID_TYPE:
        return "/".join(parts)
    if len(parts) >= 2 and parts[0] in {"通用素材", "标准模板"} and parts[1] == TECHNICAL_BID_TYPE:
        return "/".join([TECHNICAL_BID_TYPE, "通用素材", *parts[2:]])
    if len(parts) >= 3 and parts[0] in {"客户素材", "客户定制"} and parts[2] == TECHNICAL_BID_TYPE:
        return "/".join([TECHNICAL_BID_TYPE, "客户素材", parts[1], *parts[3:]])
    if len(parts) >= 3 and parts[0] in {"项目素材", "项目定制"} and parts[2] == TECHNICAL_BID_TYPE:
        return "/".join([TECHNICAL_BID_TYPE, "项目素材", parts[1], *parts[3:]])
    return "/".join(parts)


def normalize_material_tier(value: str) -> str:
    text = str(value or "").strip().lower()
    if text in MATERIAL_TIER_VALUES:
        return text
    aliases = {
        "通用": "standard",
        "通用素材": "standard",
        "标准": "standard",
        "标准模板": "standard",
        "客户": "customer",
        "客户素材": "customer",
        "客户定制": "customer",
        "项目": "project",
        "项目素材": "project",
        "项目定制": "project",
    }
    return aliases.get(text, "")


def normalize_business_material_kind(value: str) -> str:
    text = str(value or "").strip().lower()
    if text in BUSINESS_MATERIAL_KIND_VALUES:
        return text
    aliases = {
        "固定": "fixed",
        "固定素材": "fixed",
        "直接挂载": "fixed",
        "原件挂载": "fixed",
        "其他": "other",
        "普通": "other",
        "非固定": "other",
    }
    return aliases.get(text, "")


def clean_status_for_new_file(file_name: str) -> tuple[str, str]:
    suffix = material_suffix(str(file_name or ""))
    if suffix == ".ds_store":
        return "original_only", "DS_Store 原件直接保留，不触发自动清洗。"
    if suffix in CLEANABLE_MATERIAL_SUFFIXES:
        return "pending", "等待清洗转换为 Word。"
    if suffix in ORIGINAL_ONLY_MATERIAL_SUFFIXES:
        return "original_only", "图片类原件直接保留，不触发自动清洗。"
    return "failed", "当前格式暂不支持自动清洗转换。"


def bid_type_sort_order(bid_type: str) -> int:
    return 1 if bid_type == TECHNICAL_BID_TYPE else 2
