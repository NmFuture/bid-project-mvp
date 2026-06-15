"""
章节后处理器

在进入 assembler 前，对已生成章节做一层配置驱动的收口：
- 统一替换投标日期、投标保证金金额等高频占位符
- 对“供应链协同”“技术来源说明”这类高价值章节做安全兜底
"""

import re
from typing import Any, Dict, Iterable, List

from .config import ProjectConfig
from .parser import ParsedBidDoc


def apply_section_overrides(
    sections: Dict[str, str],
    config: ProjectConfig,
    parsed: ParsedBidDoc,
) -> Dict[str, str]:
    updated = {key: value for key, value in (sections or {}).items()}

    bid_date = config.get_bid_date_text()
    bid_bond_amount = config.get_bid_bond_amount_text()
    global_replacements = _build_global_replacements(config)

    for section_name, content in list(updated.items()):
        if not content:
            continue
        updated[section_name] = _replace_all(content, global_replacements)

    supply_chain_content = updated.get("供应链协同", "")
    if _should_override_supply_chain(supply_chain_content):
        updated["供应链协同"] = _build_supply_chain_section(config, parsed)

    supply_guarantee_content = updated.get("供货保障专题", "")
    if _should_override_supply_guarantee(supply_guarantee_content):
        updated["供货保障专题"] = _build_supply_guarantee_section(config, parsed)

    tech_source_content = updated.get("技术来源说明", "")
    if _should_override_tech_source(tech_source_content):
        updated["技术来源说明"] = _build_tech_source_section(config, parsed)

    if bid_date:
        updated.setdefault("封面", "")
        updated["封面"] = _replace_all(updated["封面"], global_replacements)

    if bid_bond_amount and "投标保证金" in updated:
        updated["投标保证金"] = _replace_all(updated["投标保证金"], global_replacements)

    return updated


def _build_global_replacements(config: ProjectConfig) -> Dict[str, str]:
    replacements: Dict[str, str] = {}

    bid_date = config.get_bid_date_text()
    if bid_date:
        replacements["[待填写：投标日期]"] = bid_date
        replacements["[投标日期]"] = bid_date
        replacements["{{投标日期}}"] = bid_date

    three_years_ago = config.get_three_years_ago_date_text()
    if three_years_ago:
        replacements["[三年前日期]"] = three_years_ago

    bid_bond_amount = config.get_bid_bond_amount_text()
    if bid_bond_amount:
        replacements["[待填写：投标保证金金额]"] = bid_bond_amount

    return replacements


def _replace_all(text: str, replacements: Dict[str, str]) -> str:
    result = text or ""
    for src, dst in replacements.items():
        if src and dst:
            result = result.replace(src, dst)
    return result


def _should_override_supply_chain(content: str) -> bool:
    text = (content or "").strip()
    if not text:
        return True
    return _contains_placeholder_signal(
        text,
        extra_tokens=(
            "[待填写：年份]",
            "[待填写：期限]",
            "[待填写：容量]",
            "[待填写：电量]",
            "[待填写：总量]",
            "[待填写：比例]",
            "[待填写：项目名称]",
            "[待填写：数量]",
            "[待填写：电网公司名称]",
            "[待填写：电力用户]",
        ),
    )


def _should_override_supply_guarantee(content: str) -> bool:
    text = (content or "").strip()
    if not text:
        return True
    return _contains_placeholder_signal(text)


def _should_override_tech_source(content: str) -> bool:
    text = (content or "").strip()
    if not text:
        return True
    return _contains_placeholder_signal(text, extra_tokens=("待补充",))


def _contains_placeholder_signal(content: str, extra_tokens: Iterable[str] = ()) -> bool:
    text = (content or "").strip()
    if not text:
        return True

    compact = re.sub(r"\s+", "", text)
    tokens = (
        "[待填写",
        "待补充",
        "根据评分标准展开",
        "确保完整响应",
        "请根据贵公司实际情况填写",
        "详细内容",
        "{{附件:",
        "{{招标模板:",
        *extra_tokens,
    )
    return any(token in text or token in compact for token in tokens)


def _clean_records(records: Any, fields: Iterable[str]) -> List[Dict[str, str]]:
    cleaned: List[Dict[str, str]] = []
    for item in records or []:
        if not isinstance(item, dict):
            continue
        row = {field: str(item.get(field, "") or "").strip() for field in fields}
        if any(row.values()):
            cleaned.append(row)
    return cleaned


def _project_name(config: ProjectConfig, parsed: ParsedBidDoc) -> str:
    return config.compose_project_name(
        parsed.project.name or config.project_name,
        parsed.project.sub_projects,
    )


def _build_supply_chain_section(
    config: ProjectConfig,
    parsed: ParsedBidDoc,
) -> str:
    company = config.bidder.name or "投标人"
    project_name = _project_name(config, parsed)
    capacity_mw = getattr(parsed.project, "capacity_mw", 0) or 0
    collab = config.get_supply_chain_collaboration()

    strategic_agreements = _clean_records(
        collab.get("strategic_agreements"),
        ("partner", "agreement_type", "signed_at", "scope", "validity"),
    )
    cooperation_projects = _clean_records(
        collab.get("cooperation_projects"),
        ("category", "count", "capacity_mw", "representative_project", "mode"),
    )
    power_sale_agreements = _clean_records(
        collab.get("power_sale_agreements"),
        ("counterparty", "agreement_type", "capacity_mw", "annual_power_generation", "term"),
    )

    annual_generation = str(collab.get("annual_generation_10k_kwh", "") or "").strip()
    coverage_ratio = str(collab.get("power_sale_coverage_ratio", "") or "").strip()
    green_trade = str(collab.get("green_power_trade_volume_10k_kwh", "") or "").strip()

    lines = [
        "6.1 概述",
        "",
        f"{company}高度重视与招标人及系统内单位的供应链协同工作，已围绕市场协同、设备交付、现场服务、项目执行和资源统筹建立常态化联动机制。",
        f"针对{project_name}，我司将依托整机制造、关键部件统筹、基地排产、物流协调和现场服务网络，形成覆盖投标、供货、安装调试及质保期服务的全过程协同保障体系。",
        "",
        "6.2 与系统内单位协同基础",
        "",
        "6.2.1 协同机制说明",
        "",
        f"我司已建立面向重点客户和系统内单位的专项对接机制，通过商务、技术、采购、制造、物流和服务多专业协同，持续提升重大项目的履约效率和资源保障能力。",
        "在项目执行过程中，我司将通过周计划滚动、关键物料预警、生产排产联动、驻场服务响应和高层协调机制，确保项目交付节点受控、风险闭环和问题快速处置。",
        "",
    ]

    if strategic_agreements:
        lines.extend([
            "6.2.2 战略协议签署情况",
            "",
            "签约系统内单位 | 协议类型 | 签署时间 | 合作范围 | 有效期",
        ])
        for row in strategic_agreements:
            lines.append(
                f"{row['partner']} | {row['agreement_type']} | {row['signed_at']} | "
                f"{row['scope']} | {row['validity']}"
            )
        lines.extend([
            "",
            "上述合作文件为本项目执行中的资源协调、供货组织和服务协同提供了稳定基础。",
            "",
        ])
    else:
        lines.extend([
            "6.2.2 战略合作文件说明",
            "",
            "我司已建立系统内单位合作信息归口管理机制，相关战略合作文件、历史合作成果和执行证明可按照招标文件要求结合项目实际统一补充提供。",
            "",
        ])

    lines.extend([
        "6.3 新能源项目合作情况",
        "",
        "6.3.1 合作模式",
        "",
        "我司与新能源项目业主的合作模式覆盖设备供应、项目开发配合、工程总承包协同和全生命周期运维支持等多个环节，可根据项目边界条件灵活匹配资源方案。",
        "",
    ])

    if cooperation_projects:
        lines.extend([
            "6.3.2 已合作项目概况",
            "",
            "合作类型 | 项目数量 | 总容量（MW） | 代表性项目 | 合作模式",
        ])
        for row in cooperation_projects:
            lines.append(
                f"{row['category']} | {row['count']} | {row['capacity_mw']} | "
                f"{row['representative_project']} | {row['mode']}"
            )
        lines.append("")
    else:
        lines.extend([
            "6.3.2 合作项目说明",
            "",
            "我司已在风电项目设备供货、项目开发协同和建设履约支持等方面积累成熟经验，相关业绩和合作项目情况可结合商务业绩、客户证明材料及专项附件同步说明。",
            "",
        ])

    capacity_text = f"{capacity_mw:g}MW" if capacity_mw else "本次招标规模"
    lines.extend([
        "6.3.3 本次项目协同安排",
        "",
        f"围绕{capacity_text}项目执行需求，我司将优先统筹主机排产、关键物料到货、塔筒及叶片运输窗口、现场吊装配合和售后服务资源，确保关键里程碑与项目建设节奏匹配。",
        "",
        "6.4 购售电及产业链协同情况",
        "",
        "6.4.1 协同能力说明",
        "",
        "我司具备新能源项目开发、设备制造、项目建设配合和运营服务协同能力，可根据项目实际情况对接电力交易、绿电交易及相关产业链资源，支持项目全生命周期价值提升。",
        "",
    ])

    if power_sale_agreements:
        lines.extend([
            "6.4.2 已签署购售电协议情况",
            "",
            "签约方 | 协议类型 | 签约容量（MW） | 年发电量（万kWh） | 协议期限",
        ])
        for row in power_sale_agreements:
            lines.append(
                f"{row['counterparty']} | {row['agreement_type']} | {row['capacity_mw']} | "
                f"{row['annual_power_generation']} | {row['term']}"
            )
        lines.append("")
    else:
        lines.extend([
            "6.4.2 购售电协同说明",
            "",
            "在购售电和绿电交易方面，我司将根据项目所在地政策、电网条件和业主需求，配合开展交易策略研究、资源协调和履约支持，相关协议与交易数据以实际签署文件和运营记录为准。",
            "",
        ])

    if annual_generation or coverage_ratio or green_trade:
        summary_parts = []
        if annual_generation:
            summary_parts.append(f"现有项目年均发电量约{annual_generation}万kWh")
        if coverage_ratio:
            summary_parts.append(f"已签署协议覆盖比例约{coverage_ratio}%")
        if green_trade:
            summary_parts.append(f"绿电交易电量约{green_trade}万kWh")
        lines.extend([
            "6.4.3 运营协同指标",
            "",
            "，".join(summary_parts) + "。",
            "",
        ])

    lines.extend([
        "6.5 本项目供应链协同保障措施",
        "",
        "6.5.1 组织架构保障",
        "",
        "我司将成立项目专项协同工作组，由商务、计划、采购、制造、物流、质量和服务团队组成，形成项目经理负责、专业接口人联动、关键事项升级协调的组织保障机制。",
        "",
        "6.5.2 计划与交付保障",
        "",
        "我司将实行滚动排产和节点穿透管理，对关键部件、核心工序、物流发运和现场服务实行周度跟踪，确保各项交付任务按计划推进。",
        "",
        "6.5.3 风险预警与应急保障",
        "",
        "针对原材料波动、供应商交期、物流窗口、现场并行施工等风险，我司将建立预警清单和应急预案，做到风险提前识别、快速响应、闭环整改。",
        "",
        "6.5.4 服务协同保障",
        "",
        "在设备制造、发运、安装调试及质保期服务阶段，我司将配置专业工程师和区域服务资源，确保现场问题快速处理、技术支持及时到位和服务质量持续受控。",
        "",
        "6.6 结语",
        "",
        f"{company}将充分发挥制造体系、供应链统筹和项目执行协同优势，全力保障{project_name}高质量履约，并持续深化与招标人及系统内单位的合作关系。",
    ])

    return "\n".join(lines)


def _build_supply_guarantee_section(
    config: ProjectConfig,
    parsed: ParsedBidDoc,
) -> str:
    company = config.bidder.name or "投标人"
    project_name = _project_name(config, parsed)
    capacity_mw = getattr(parsed.project, "capacity_mw", 0) or 0
    turbine_count = getattr(parsed.project, "turbine_count", 0) or 0

    if capacity_mw and turbine_count:
        scale_text = f"本项目招标规模约{capacity_mw:g}MW，共{turbine_count}台机组"
    elif capacity_mw:
        scale_text = f"本项目招标规模约{capacity_mw:g}MW"
    elif turbine_count:
        scale_text = f"本项目机组数量约{turbine_count}台"
    else:
        scale_text = "本项目招标规模明确、节点要求清晰"

    return "\n".join([
        f"{company}针对{project_name}已建立专项供货保障方案，围绕商务中标、生产准备、关键部件组织、整机制造、物流发运、现场交付及售后服务等环节形成全过程保障链条。",
        f"{scale_text}。我司将依托现有制造体系、计划体系和供应链协同机制，确保设备按合同约定完成交付并满足项目建设进度要求。",
        "",
        "### 与业主及同类项目合作基础",
        "",
        f"{company}长期服务新能源项目建设，具备大型风电项目批量供货、跨区域资源协调和多专业接口协同经验，可针对{project_name}建立从商务澄清到交付验收的全过程沟通机制。",
        "",
        "### 组织机构保障",
        "",
        "项目中标后将立即成立专项履约工作组，由商务、计划、采购、制造、质量、物流、现场服务等专业人员组成，实行项目经理负责制和关键节点升级协调机制。",
        "",
        "### 计划管理体系保障",
        "",
        "围绕合同签订、技术联络、生产排产、关键物料到货、总装调试、出厂验收、发运交付等关键节点建立主计划和周滚动计划，形成里程碑到工序的穿透式管理。",
        "",
        "### 供应链能力保障",
        "",
        "针对主机、叶片、塔筒、电气系统和关键外购件建立供应资源池和预警机制，对关键物料实行前置锁定、动态跟踪和异常升级处置，确保核心部件供给稳定。",
        "",
        "### 主机生产基地产能保障",
        "",
        f"{company}将结合项目排产窗口统筹现有制造基地资源，优先保障本项目产能配置、关键工装安排和总装节拍，确保生产能力与项目交付节奏匹配。",
        "",
        "### 大项目管理模式保障",
        "",
        "对于批量机组项目，实行总部统筹、基地联动、区域服务协同的管理模式，针对关键风险设置专项清单和应急预案，确保生产、运输、吊装配合及现场服务无缝衔接。",
        "",
        "### 关键零部件分包商与交付节点",
        "",
        "我司将对关键分包商和核心供应商实行准入、质量、交期、履约能力的全过程管理，重点管控叶片、塔筒、电气及控制系统等交付节点，并通过周例会机制持续跟踪闭环。",
        "",
        "### 结语",
        "",
        f"{company}有能力为{project_name}提供稳定、可控、可追踪的供货保障服务，并以项目交付结果为导向，全面满足招标文件对制造能力、组织保障和履约效率的要求。",
    ])


def _build_tech_source_section(
    config: ProjectConfig,
    parsed: ParsedBidDoc,
) -> str:
    custom_description = config.get_tech_source_description()
    if custom_description:
        return _strip_redundant_title(custom_description, "技术来源说明")

    company = config.bidder.name or "投标人"
    project_name = _project_name(config, parsed)
    return "\n".join([
        f"{company}针对{project_name}拟投设备，技术来源以现有成熟产品平台、工程化应用经验及合法取得的配套技术为基础，可满足本项目设备供货、安装调试、性能考核和售后服务要求。",
        "",
        "1. 整机总体方案、控制策略、运行逻辑及项目适配设计由投标人统筹完成，并结合项目边界条件开展针对性配置。",
        "2. 关键部件和配套系统优先采用成熟、稳定、可追溯的技术方案，相关供应链和质量控制要求已纳入投标人现有管理体系。",
        "3. 若项目实施中涉及第三方配套部件、软件或通用技术模块，均以合法采购、合法授权或合规合作方式取得，不影响本项目合同履行和售后服务责任承担。",
        "4. 投标人具备持续技术优化、问题闭环整改和批量项目工程化实施能力，可在合同执行阶段按照招标人要求提供技术联络、资料交付和现场支持服务。",
    ])


def _strip_redundant_title(content: str, section_name: str) -> str:
    lines = (content or "").splitlines()
    first_idx = next((idx for idx, line in enumerate(lines) if line.strip()), None)
    if first_idx is None:
        return content

    first_line = lines[first_idx].strip()
    if _normalize_heading(first_line) != _normalize_heading(section_name):
        return content

    del lines[first_idx]
    while first_idx < len(lines) and not lines[first_idx].strip():
        del lines[first_idx]
    return "\n".join(lines)


def _normalize_heading(text: str) -> str:
    stripped = (text or "").strip().lstrip("#").strip()
    stripped = re.sub(
        r"^\s*(?:"
        r"\d+(?:\.\d+)*\s+|"
        r"[一二三四五六七八九十百千万]+[、.．]\s*|"
        r"第[一二三四五六七八九十百千万\d]+[章节篇部分卷]\s*"
        r")",
        "",
        stripped,
    )
    return re.sub(r"[\s:：\\-_/()（）【】\[\]{}<>]+", "", stripped).lower()
