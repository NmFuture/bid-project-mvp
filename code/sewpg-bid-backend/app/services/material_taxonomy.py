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
BUSINESS_MATERIAL_KIND_VALUES = {"fixed", "ai_fill", "other"}
BUSINESS_MATERIAL_KIND_LABELS = {
    "fixed": "固定素材",
    "ai_fill": "AI填写",
    "other": "其他",
}
CLEANABLE_MATERIAL_SUFFIXES = {".docx"}
ORIGINAL_ONLY_MATERIAL_SUFFIXES = {
    ".pdf",
    ".xlsx",
    ".xls",
    ".xlsm",
    ".doc",
    ".md",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
}
MATERIAL_LIBRARY_ALLOWED_SUFFIXES = CLEANABLE_MATERIAL_SUFFIXES | ORIGINAL_ONLY_MATERIAL_SUFFIXES
# 快捷方式类文件没有实质内容，上传时直接过滤不入库
SHORTCUT_MATERIAL_SUFFIXES = {".lnk", ".url", ".webloc", ".desktop"}
RAW_MATERIAL_ROOTS = (
    {"name": TECHNICAL_BID_TYPE, "tier": "standard", "bid_type": TECHNICAL_BID_TYPE, "sort_order": 1},
    {"name": BUSINESS_BID_TYPE, "tier": "standard", "bid_type": BUSINESS_BID_TYPE, "sort_order": 2},
)
RAW_MATERIAL_ROOT_TIERS = {str(item["name"]): str(item["tier"]) for item in RAW_MATERIAL_ROOTS}
TECHNICAL_TIER_FOLDERS = (
    {"name": "标准文件", "tier": "standard", "sort_order": 1, "customer_name": "平台标准"},
    {"name": "客户定制", "tier": "customer", "sort_order": 2},
    {"name": "项目定制", "tier": "project", "sort_order": 3},
)
BUSINESS_TIER_FOLDERS = (
    {"name": "通用素材", "tier": "standard", "sort_order": 1, "customer_name": "平台标准"},
    {"name": "客户素材", "tier": "customer", "sort_order": 2},
    {"name": "项目素材", "tier": "project", "sort_order": 3},
)
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
        "name": "资格审查与基础证明",
        "tier": "standard",
        "sort_order": 10,
        "material_category": "qualification_evidence",
    },
    {
        "name": "财务信用与合规声明",
        "tier": "standard",
        "sort_order": 20,
        "material_category": "financial_credit_compliance",
    },
    {
        "name": "制造商与供应链材料",
        "tier": "standard",
        "sort_order": 30,
        "material_category": "manufacturer_supply_chain",
    },
    {
        "name": "机型认证与测试报告",
        "tier": "standard",
        "sort_order": 40,
        "material_category": "product_grid_certificate",
    },
    {
        "name": "企业能力与供货业绩",
        "tier": "standard",
        "sort_order": 50,
        "material_category": "enterprise_capability",
    },
    {
        "name": "表单模板与过程稿",
        "tier": "standard",
        "sort_order": 60,
        "material_category": "template_draft",
    },
)
BUSINESS_CUSTOMIZED_SUBFOLDERS = (
    {
        "name": "客户准入与专项证明",
        "tier": "customer",
        "sort_order": 10,
        "material_category": "customer_relationship_proof",
    },
    {
        "name": "客户专用响应口径",
        "tier": "customer",
        "sort_order": 20,
        "material_category": "customer_response",
    },
    {
        "name": "客户模板与历史文件",
        "tier": "customer",
        "sort_order": 30,
        "material_category": "customer_template_process",
    },
)

BUSINESS_PROJECT_SUBFOLDERS = (
    {
        "name": "招标要求与专项证明",
        "tier": "project",
        "sort_order": 10,
        "material_category": "project_requirement_proof",
    },
    {
        "name": "资格审查与商务响应成册",
        "tier": "project",
        "sort_order": 20,
        "material_category": "project_response",
    },
    {
        "name": "项目过程稿与澄清文件",
        "tier": "project",
        "sort_order": 30,
        "material_category": "project_template_process",
    },
)

BUSINESS_MATERIAL_CATEGORY_VALUES = {
    "qualification_evidence",
    "financial_credit_compliance",
    "manufacturer_supply_chain",
    "product_grid_certificate",
    "enterprise_capability",
    "template_draft",
    "customer_relationship_proof",
    "customer_response",
    "customer_template_process",
    "project_requirement_proof",
    "project_response",
    "project_template_process",
}
BUSINESS_MATERIAL_CATEGORY_LABELS = {
    "qualification_evidence": "资格审查与基础证明",
    "financial_credit_compliance": "财务信用与合规声明",
    "manufacturer_supply_chain": "制造商与供应链材料",
    "product_grid_certificate": "机型认证与测试报告",
    "enterprise_capability": "企业能力与供货业绩",
    "template_draft": "表单模板与过程稿",
    "customer_relationship_proof": "客户准入与专项证明",
    "customer_response": "客户专用响应口径",
    "customer_template_process": "客户模板与历史文件",
    "project_requirement_proof": "招标要求与专项证明",
    "project_response": "资格审查与商务响应成册",
    "project_template_process": "项目过程稿与澄清文件",
}
BUSINESS_MATERIAL_CATEGORY_SORT_ORDERS = {
    "qualification_evidence": 10,
    "financial_credit_compliance": 20,
    "manufacturer_supply_chain": 30,
    "product_grid_certificate": 40,
    "enterprise_capability": 50,
    "template_draft": 60,
    "customer_relationship_proof": 10,
    "customer_response": 20,
    "customer_template_process": 30,
    "project_requirement_proof": 10,
    "project_response": 20,
    "project_template_process": 30,
}
BUSINESS_OLD_CATEGORY_SEGMENT_ALIASES = {
    "01-资质合规库": "qualification_evidence",
    "资质合规库": "qualification_evidence",
    "资格审查文件": "qualification_evidence",
    "资格审查与基础证明": "qualification_evidence",
    "主体资质与基础证照": "qualification_evidence",
    "体系认证证书": "qualification_evidence",
    "质量管理体系": "qualification_evidence",
    "环境管理体系": "qualification_evidence",
    "职业健康安全管理体系": "qualification_evidence",
    "信用与失信查询截图": "financial_credit_compliance",
    "国家企业信用信息公示系统": "financial_credit_compliance",
    "信用中国": "financial_credit_compliance",
    "资格审查表与承诺": "template_draft",
    "资格审查表": "template_draft",
    "制造商与供应链材料": "manufacturer_supply_chain",
    "重点部件制造商主体资料": "manufacturer_supply_chain",
    "生产许可与鉴定材料": "manufacturer_supply_chain",
    "质量保证体系证明": "manufacturer_supply_chain",
    "供货协议与供应承诺": "manufacturer_supply_chain",
    "机型认证与测试报告": "product_grid_certificate",
    "02-企业能力库": "enterprise_capability",
    "企业能力库": "enterprise_capability",
    "企业能力与综合实力": "enterprise_capability",
    "企业能力与供货业绩": "enterprise_capability",
    "04-财务资料库": "financial_credit_compliance",
    "财务资料库": "financial_credit_compliance",
    "财务信用与合规声明": "financial_credit_compliance",
    "05-专题证书库": "product_grid_certificate",
    "专题证书库": "product_grid_certificate",
    "01-机型认证证书": "product_grid_certificate",
    "机型认证证书": "product_grid_certificate",
    "02-大部件型式认证证书": "product_grid_certificate",
    "大部件型式认证证书": "product_grid_certificate",
    "06-通用模板底稿库": "template_draft",
    "通用模板底稿库": "template_draft",
    "通用表单与模板": "template_draft",
    "表单模板与过程稿": "template_draft",
    "01-客户关系与专项证明": "customer_relationship_proof",
    "客户关系与专项证明": "customer_relationship_proof",
    "客户准入与专项证明": "customer_relationship_proof",
    "02-商务响应文件": "customer_response",
    "商务响应文件": "customer_response",
    "客户专用商务响应文件": "customer_response",
    "客户专用响应口径": "customer_response",
    "03-模板底稿与过程文件": "customer_template_process",
    "模板底稿与过程文件": "customer_template_process",
    "客户模板底稿与过程文件": "customer_template_process",
    "客户模板与过程稿": "customer_template_process",
    "客户模板与历史文件": "customer_template_process",
    "项目专项证明与客户要求": "project_requirement_proof",
    "招标要求与专项证明": "project_requirement_proof",
    "项目商务响应文件": "project_response",
    "资格审查与商务响应成册": "project_response",
    "项目模板底稿与过程文件": "project_template_process",
    "项目模板与过程稿": "project_template_process",
    "项目过程稿与澄清文件": "project_template_process",
}

BUSINESS_MATERIAL_SUBCATEGORY_ALIASES = {
    "主体资质与基础证照": "bidder_identity",
    "营业执照": "bidder_identity",
    "开户": "bidder_identity",
    "股东关联与资格声明": "shareholder_relation",
    "资格声明": "shareholder_relation",
    "股东名单": "shareholder_relation",
    "管理关系": "shareholder_relation",
    "财务资信与审计报告": "financial_audit",
    "财务": "financial_audit",
    "审计": "financial_audit",
    "资产负债表": "financial_audit",
    "损益表": "financial_audit",
    "现金流量表": "financial_audit",
    "银行资信": "financial_audit",
    "信用合规与诉讼查询": "credit_compliance",
    "信用与失信查询截图": "credit_compliance",
    "信用中国": "credit_compliance",
    "国家企业信用信息公示系统": "credit_compliance",
    "失信被执行": "credit_compliance",
    "严重违法失信": "credit_compliance",
    "诉讼": "credit_compliance",
    "管理体系与资质认证": "management_system",
    "体系认证证书": "management_system",
    "质量管理体系": "management_system",
    "环境管理体系": "management_system",
    "职业健康安全管理体系": "management_system",
    "重点部件制造商主体资料": "manufacturer_identity",
    "制造商营业执照": "manufacturer_identity",
    "制造商资格声明": "manufacturer_identity",
    "生产许可与鉴定材料": "production_license",
    "生产许可证": "production_license",
    "鉴定材料": "production_license",
    "质量保证体系证明": "quality_assurance",
    "供货协议与供应承诺": "supply_commitment",
    "供货协议": "supply_commitment",
    "合作意向": "supply_commitment",
    "供应承诺": "supply_commitment",
    "机型设计与型式认证": "model_design_type",
    "机型认证": "model_design_type",
    "设计认证": "model_design_type",
    "型式认证": "model_design_type",
    "大部件型式认证": "component_type_certificate",
    "大部件型式认证证书": "component_type_certificate",
    "部件": "component_type_certificate",
    "电能质量与低高电压穿越": "power_quality_lvrt_hvrt",
    "电能质量": "power_quality_lvrt_hvrt",
    "低电压穿越": "power_quality_lvrt_hvrt",
    "高电压穿越": "power_quality_lvrt_hvrt",
    "穿越测试": "power_quality_lvrt_hvrt",
    "240小时试运行证明": "trial_operation_240h",
    "240小时": "trial_operation_240h",
    "试运行": "trial_operation_240h",
    "企业基本情况与组织人员": "organization_staff",
    "公司介绍": "company_profile",
    "组织机构": "organization_staff",
    "人员状况": "organization_staff",
    "制造设备与服务能力": "equipment_service",
    "制造基地": "equipment_service",
    "服务能力": "equipment_service",
    "主要自有机械": "equipment_service",
    "奖项专利与综合荣誉": "awards_patents",
    "专利": "awards_patents",
    "获奖": "awards_patents",
    "类似供货业绩": "similar_supply_overview",
    "供货业绩": "similar_supply_overview",
    "资格审查表单": "qualification_form",
    "声明承诺函模板": "statement_commitment_template",
    "承诺函": "statement_commitment_template",
    "商务响应通用模板": "business_response_template",
    "投标函": "business_response_template",
    "授权书": "business_response_template",
    "报价表": "business_response_template",
    "偏差表": "business_response_template",
    "过程底稿": "process_draft",
}

BUSINESS_LEGACY_STANDARD_PROTECTED_FOLDER_PATHS = {
    f"{BUSINESS_BID_TYPE}/通用素材/{name}"
    for name in (
        "资格审查文件",
        "资格审查文件/主体资质与基础证照",
        "资格审查文件/体系认证证书",
        "资格审查文件/财务信用与合规声明",
        "资格审查文件/信用与失信查询截图",
        "资格审查文件/资格审查表与承诺",
        "主体资质与基础证照",
        "财务信用与合规声明",
        "企业能力与综合实力",
        "专题证书库",
        "专题证书库/机型认证证书",
        "专题证书库/大部件型式认证证书",
        "通用模板底稿库",
    )
}
BUSINESS_LEGACY_CUSTOMER_PROTECTED_FOLDER_NAMES = {
    "客户关系与专项证明",
    "客户专用商务响应文件",
    "客户模板底稿与过程文件",
    "客户模板与过程稿",
}
BUSINESS_LEGACY_PROJECT_PROTECTED_FOLDER_NAMES = {
    "项目专项证明与客户要求",
    "项目商务响应文件",
    "项目模板底稿与过程文件",
    "项目模板与过程稿",
}


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
    RAW_MATERIAL_PROTECTED_BASE_FOLDER_PATHS
    | {f"{BUSINESS_BID_TYPE}/{folder['name']}" for folder in BUSINESS_TIER_FOLDERS}
    | _business_standard_protected_folder_paths()
    | BUSINESS_LEGACY_STANDARD_PROTECTED_FOLDER_PATHS
)
BUSINESS_CUSTOMER_PROTECTED_FOLDER_NAMES = {
    str(spec["name"])
    for spec in BUSINESS_CUSTOMIZED_SUBFOLDERS
} | BUSINESS_LEGACY_CUSTOMER_PROTECTED_FOLDER_NAMES
BUSINESS_PROJECT_PROTECTED_FOLDER_NAMES = {
    str(spec["name"])
    for spec in BUSINESS_PROJECT_SUBFOLDERS
} | BUSINESS_LEGACY_PROJECT_PROTECTED_FOLDER_NAMES
BUSINESS_CUSTOMIZED_PROTECTED_FOLDER_NAMES = {
    str(spec["name"])
    for specs in (BUSINESS_CUSTOMIZED_SUBFOLDERS, BUSINESS_PROJECT_SUBFOLDERS)
    for spec in specs
}


def material_suffix(name: str) -> str:
    return PurePosixPath(name).suffix.lower()


def ext_of(name: str) -> str:
    return material_suffix(name).lstrip(".") or "file"


def is_raw_material_protected_folder_path(folder_path: str) -> bool:
    normalized = str(folder_path or "").replace("\\", "/").strip("/")
    if normalized in RAW_MATERIAL_PROTECTED_FOLDER_PATHS:
        return True
    parts = [part for part in normalized.split("/") if part]
    if len(parts) == 3 and parts[0] == BUSINESS_BID_TYPE and parts[1] in {"客户素材", "项目素材"}:
        return True
    if len(parts) != 4 or parts[0] != BUSINESS_BID_TYPE:
        return False
    if parts[1] == "客户素材":
        return parts[3] in BUSINESS_CUSTOMER_PROTECTED_FOLDER_NAMES
    if parts[1] == "项目素材":
        return parts[3] in BUSINESS_PROJECT_PROTECTED_FOLDER_NAMES
    return False


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
        # 旧档位根名（客户素材/项目素材）归一到当前口径（客户定制/项目定制）
        legacy_tier_names = {"客户素材": "客户定制", "项目素材": "项目定制"}
        if len(parts) >= 2 and parts[1] in legacy_tier_names:
            return "/".join([TECHNICAL_BID_TYPE, legacy_tier_names[parts[1]], *parts[2:]])
        return "/".join(parts)
    if len(parts) >= 2 and parts[0] in {"通用素材", "标准文件", "标准模板"} and parts[1] == TECHNICAL_BID_TYPE:
        return "/".join([TECHNICAL_BID_TYPE, "标准文件", *parts[2:]])
    if len(parts) >= 3 and parts[0] in {"客户素材", "客户定制"} and parts[2] == TECHNICAL_BID_TYPE:
        return "/".join([TECHNICAL_BID_TYPE, "客户定制", parts[1], *parts[3:]])
    if len(parts) >= 3 and parts[0] in {"项目素材", "项目定制"} and parts[2] == TECHNICAL_BID_TYPE:
        return "/".join([TECHNICAL_BID_TYPE, "项目定制", parts[1], *parts[3:]])
    return "/".join(parts)


def normalize_material_tier(value: str) -> str:
    text = str(value or "").strip().lower()
    if text in MATERIAL_TIER_VALUES:
        return text
    aliases = {
        "通用": "standard",
        "通用素材": "standard",
        "标准": "standard",
        "标准文件": "standard",
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
        "ai填写": "ai_fill",
        "ai填充": "ai_fill",
        "ai_fill": "ai_fill",
        "待填写": "ai_fill",
        "可填写": "ai_fill",
        "填写模板": "ai_fill",
        "AI填写": "ai_fill",
        "AI 填写": "ai_fill",
        "其他": "other",
        "普通": "other",
        "非固定": "other",
    }
    return aliases.get(text, "")


def normalize_business_material_category(value: str) -> str:
    text = str(value or "").strip()
    if text in BUSINESS_MATERIAL_CATEGORY_VALUES:
        return text
    return BUSINESS_OLD_CATEGORY_SEGMENT_ALIASES.get(text, "")


def normalize_business_material_subcategory(value: str) -> str:
    text = str(value or "").strip()
    return BUSINESS_MATERIAL_SUBCATEGORY_ALIASES.get(text, "")


def infer_business_material_subcategory(folder_path: str = "", file_name: str = "") -> str:
    file_text = str(file_name or "")
    path_parts = [part for part in str(folder_path or "").replace("\\", "/").strip("/").split("/") if part]
    for token, subcategory in BUSINESS_MATERIAL_SUBCATEGORY_ALIASES.items():
        if token and token in file_text:
            return subcategory
    for part in reversed(path_parts):
        subcategory = normalize_business_material_subcategory(part)
        if subcategory:
            return subcategory
    return ""


def infer_business_material_category(folder_path: str = "", file_name: str = "", material_tier: str = "") -> str:
    path_parts = [part for part in str(folder_path or "").replace("\\", "/").strip("/").split("/") if part]
    tier = normalize_material_tier(material_tier)
    for part in reversed(path_parts):
        category = normalize_business_material_category(part)
        if category:
            if tier == "project" and category == "customer_relationship_proof":
                return "project_requirement_proof"
            if tier == "project" and category == "customer_response":
                return "project_response"
            if tier == "project" and category == "customer_template_process":
                return "project_template_process"
            return category

    text = f"{folder_path}/{file_name}"
    if tier == "customer":
        if any(token in text for token in ("关系", "专项证明", "授权", "评价", "框架协议", "战略协议")):
            return "customer_relationship_proof"
        if any(token in text for token in ("模板", "底稿", "过程")):
            return "customer_template_process"
        return "customer_response"
    if tier == "project":
        if any(token in text for token in ("客户要求", "专项证明", "补充说明", "关系", "授权")):
            return "project_requirement_proof"
        if any(token in text for token in ("模板", "底稿", "过程")):
            return "project_template_process"
        return "project_response"
    if any(token in text for token in ("模板", "底稿", "空白", "投标函", "授权书", "报价表", "偏差表", "承诺函", "资格审查表")):
        return "template_draft"
    if any(token in text for token in ("制造商", "重点部件", "供应商", "供货协议", "合作意向", "供应承诺", "质量保证体系")):
        return "manufacturer_supply_chain"
    if any(token in text for token in ("机型认证", "设计认证", "型式认证", "大部件", "电能质量", "低电压穿越", "高电压穿越", "穿越测试", "240小时", "试运行")):
        return "product_grid_certificate"
    if any(token in text for token in ("公司介绍", "制造", "基地", "服务能力", "质量", "专利", "奖项", "装机", "产能")):
        return "enterprise_capability"
    if any(token in text for token in ("财务", "审计", "报表", "银行", "纳税", "信用", "无违法", "无行贿", "无重大", "信用中国", "国家企业信用信息公示系统", "严重违法失信", "失信被执行", "黑名单", "网站截图", "查询截图")):
        return "financial_credit_compliance"
    if any(token in text for token in ("营业执照", "生产许可证", "安全生产", "资质", "体系认证", "ISO9001", "ISO14001", "ISO45001", "开户", "资格声明", "投标人资格", "股东")):
        return "qualification_evidence"
    return ""


def clean_status_for_new_file(file_name: str) -> tuple[str, str]:
    suffix = material_suffix(str(file_name or ""))
    if suffix in CLEANABLE_MATERIAL_SUFFIXES:
        return "pending", "等待清洗规范化 Word。"
    return "original_only", "非 Word 素材保留原件，不触发自动清洗。"


def bid_type_sort_order(bid_type: str) -> int:
    return 1 if bid_type == TECHNICAL_BID_TYPE else 2
