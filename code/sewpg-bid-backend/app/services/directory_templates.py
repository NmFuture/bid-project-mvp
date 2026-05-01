from __future__ import annotations

import copy
from typing import Any

from app.services.identity import build_project_identity, normalize_identity_text, normalize_bid_type


TECH_GENERAL_PROFILE: dict[str, Any] = {
    "id": "tech-general",
    "name": "技术标通用目录模板",
    "bidType": "技术标",
    "description": "通用技术标正文主骨架，供 S2 目录生成与 S3 审核兜底对照。",
    "source": "doc/15-技术标与商务标需求整理.md + 当前技术标模板抽取口径",
    "chapters": [
        {
            "num": "1",
            "title": "标前概述",
            "h2s": [
                {"num": "1.1", "title": "投标关键数据一览表"},
                {"num": "1.2", "title": "投标方案优势说明"},
                {"num": "1.3", "title": "投标机型业绩情况"},
                {"num": "1.4", "title": "投标人能力简介"},
                {"num": "1.5", "title": "供货保障能力"},
            ],
        },
        {
            "num": "2",
            "title": "技术标准",
            "h2s": [
                {"num": "2.1", "title": "技术标准和规范响应"},
                {"num": "2.2", "title": "技术偏差说明"},
            ],
        },
        {
            "num": "3",
            "title": "风资源评估与机位排布方案",
            "h2s": [
                {"num": "3.1", "title": "总体方案概览"},
                {"num": "3.2", "title": "项目概况"},
                {"num": "3.3", "title": "风资源分析"},
                {"num": "3.4", "title": "机组选型"},
                {"num": "3.5", "title": "风机适应性分析"},
                {"num": "3.6", "title": "方案及发电量结果"},
                {"num": "3.7", "title": "不确定性分析"},
            ],
        },
        {
            "num": "4",
            "title": "项目技术承诺函",
            "h2s": [
                {"num": "4.1", "title": "发电小时数承诺函"},
                {"num": "4.2", "title": "投标机组可利用率承诺"},
                {"num": "4.3", "title": "投标机组功率曲线保证率承诺"},
                {"num": "4.4", "title": "投标机组主要部件更换率承诺"},
                {"num": "4.5", "title": "投标机组无故障时间承诺"},
            ],
        },
        {
            "num": "5",
            "title": "专题方案要求",
            "h2s": [
                {"num": "5.1", "title": "投标总体方案概述"},
                {"num": "5.2", "title": "供货范围概述"},
                {"num": "5.3", "title": "投标方案技术先进性综述"},
                {"num": "5.4", "title": "项目投标设备综合技术参数与性能指标"},
                {"num": "5.5", "title": "项目风资源评估与机组选型排布及发电量计算"},
                {"num": "5.6", "title": "投标机型样机认证与测试专题"},
                {"num": "5.7", "title": "投标机型项目场址设计安全性专题"},
                {"num": "5.8", "title": "项目风机各子系统专题"},
                {"num": "5.9", "title": "项目风机环境适应性专题"},
                {"num": "5.10", "title": "投标项目塔筒专题"},
                {"num": "5.11", "title": "项目设备制造与全过程质量保障体系专题"},
                {"num": "5.12", "title": "项目投标设备交货进度"},
                {"num": "5.13", "title": "项目投标设备运输与现场存储方案"},
                {"num": "5.14", "title": "项目投标设备安装与调试方案"},
                {"num": "5.15", "title": "项目技术支持及服务专题"},
                {"num": "5.16", "title": "设备运行和维护专题"},
            ],
        },
        {
            "num": "6",
            "title": "产品交付、考核及验收",
            "h2s": [
                {"num": "6.1", "title": "技术资料和交付进度"},
                {"num": "6.2", "title": "试验、检验和监造"},
                {"num": "6.3", "title": "设备安装、调试与试运行"},
                {"num": "6.4", "title": "考核指标"},
                {"num": "6.5", "title": "项目验收"},
            ],
        },
    ],
}


TECH_HUANENG_PROFILE: dict[str, Any] = {
    "id": "tech-huaneng",
    "name": "华能类大客户技术标目录模板",
    "bidType": "技术标",
    "description": "华能类项目常见评分索引、战略合作、自主可控、专题响应结构。",
    "source": "code/测试文档/投标文件-模板.docx 目录抽取 + 华能类需求整理",
    "match": {"customerIds": ["CUST-HUANENG"], "customerKeywords": ["华能", "中国华能", "华能集团"]},
    "chapters": [
        {
            "num": "1",
            "title": "标前概述",
            "h2s": [
                {"num": "1.1", "title": "技术评分标准索引表"},
                {"num": "1.2", "title": "与华能集团签署的战略合作协议"},
                {"num": "1.3", "title": "与华能集团新能源项目合作"},
                {"num": "1.4", "title": "风电机组自主可控推广应用的承诺"},
                {"num": "1.5", "title": "我司与华能集团合作自主可控技术的研发与应用"},
            ],
        },
        {
            "num": "5",
            "title": "专题方案要求",
            "h2s": [
                {"num": "5.17", "title": "碳排放强度（tCO2e/万元营业收入）"},
                {"num": "5.18", "title": "数字化智慧风场专题"},
                {"num": "5.19", "title": "上海电气风电试验检测能力专题"},
            ],
        },
    ],
}


def list_directory_template_profiles() -> list[dict[str, Any]]:
    return copy.deepcopy([TECH_GENERAL_PROFILE, TECH_HUANENG_PROFILE])


def select_directory_template_profiles(project: dict[str, Any]) -> list[dict[str, Any]]:
    bid_type = normalize_bid_type(project.get("bidType"), "技术标")
    if bid_type != "技术标":
        return []

    selected = [TECH_GENERAL_PROFILE]
    identity = project.get("identity") if isinstance(project.get("identity"), dict) else build_project_identity(project)
    if _matches_huaneng(project, identity):
        selected.append(TECH_HUANENG_PROFILE)
    return copy.deepcopy(selected)


def _matches_huaneng(project: dict[str, Any], identity: dict[str, Any]) -> bool:
    if str(identity.get("customerId") or "") == "CUST-HUANENG":
        return True

    values = [
        project.get("customerName"),
        project.get("owner"),
        identity.get("customerCanonicalName"),
        identity.get("customerName"),
        identity.get("owner"),
        *(identity.get("customerAliases") or []),
    ]
    keys = [normalize_identity_text(value) for value in values if value]
    return any("华能" in key or "中国华能" in key for key in keys)
