from __future__ import annotations

from dataclasses import dataclass


TECHNICAL_PARSE_SKILL_NAME = "bid-tender-structured-parser"
BUSINESS_PARSE_SKILL_NAME = "bid-business-tender-structured-parser"
TECHNICAL_SCHEMA_VERSION = "bid-tender-structured-v1"
BUSINESS_SCHEMA_VERSION = "bid-business-tender-structured-v1"
TECHNICAL_WORKSPACE_DIRNAME = "technical-workspace"
BUSINESS_WORKSPACE_DIRNAME = "business-workspace"


@dataclass(frozen=True)
class ParseProfile:
    key: str
    bid_type: str
    skill_name: str
    schema_version: str
    workspace_dirname: str
    targets: tuple[str, ...]


TECHNICAL_PARSE_PROFILE = ParseProfile(
    key="technical",
    bid_type="技术标",
    skill_name=TECHNICAL_PARSE_SKILL_NAME,
    schema_version=TECHNICAL_SCHEMA_VERSION,
    workspace_dirname=TECHNICAL_WORKSPACE_DIRNAME,
    targets=(
        "评分细则",
        "项目基础信息",
        "风机核心参数",
        "性能保证指标",
        "环境适应性要求",
        "专题方案要求",
        "附表和供货范围",
        "考核条款",
        "投标相关日期",
    ),
)


BUSINESS_PARSE_PROFILE = ParseProfile(
    key="business",
    bid_type="商务标",
    skill_name=BUSINESS_PARSE_SKILL_NAME,
    schema_version=BUSINESS_SCHEMA_VERSION,
    workspace_dirname=BUSINESS_WORKSPACE_DIRNAME,
    targets=(
        "商务评分细则",
        "项目基础信息",
        "商务响应要求",
        "资格与业绩支撑要求",
        "承诺事项要求",
        "商务附表与空表",
        "投标相关日期",
    ),
)


def normalize_bid_type(bid_type: str) -> str:
    value = str(bid_type or "").strip()
    return "商务标" if "商务" in value else "技术标"


def resolve_parse_profile(bid_type: str) -> ParseProfile:
    return BUSINESS_PARSE_PROFILE if normalize_bid_type(bid_type) == "商务标" else TECHNICAL_PARSE_PROFILE
