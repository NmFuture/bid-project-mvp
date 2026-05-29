from __future__ import annotations

import re


FORMAT_REGION_TOKENS = (
    "投标文件格式",
    "响应文件格式",
    "商务文件格式",
    "商务投标文件格式",
    "附件格式",
)

MAJOR_SECTION_RE = re.compile(r"^第[一二三四五六七八九十百千0-9]+章\s*")

APPENDIX_TITLE_RE = re.compile(
    r"^(?:(?:特殊)?附件\s*[0-9一二三四五六七八九十]+[A-Z]?|[0-9一二三四五六七八九十]+[、.．])\s*",
    re.IGNORECASE,
)

FORMAT_CODE_RE = re.compile(r"[（(]\s*(?:[0-9]+[A-Z]?|[A-Z]|[A-Z][0-9]+)\s*[）)]", re.IGNORECASE)

SUB_TABLE_CODE_RE = re.compile(
    r"^(?:表\s*\d+\s*[A-Z]?(?:-\d+)?|[0-9]+[A-Z]-\d+\s*表?)",
    re.IGNORECASE,
)

LETTER_PREFIX_CODE_RE = re.compile(r"^[A-Z](?:-\d+)?(?=\s|\(|（|[\u4e00-\u9fff])", re.IGNORECASE)

BUSINESS_TOPIC_TOKENS = (
    "投标函",
    "法定代表人",
    "单位负责人",
    "身份证明",
    "授权",
    "廉洁",
    "承诺",
    "投标价格",
    "开标价格",
    "价格表",
    "分项报价",
    "商务偏差",
    "合同条款偏差",
    "货物规格",
    "供货范围",
    "分包商",
    "外购件",
    "投标保证金",
    "保函",
    "履约保证",
    "资格证明",
    "业绩",
    "财务状况",
    "资信",
    "保密",
    "投标人需要说明",
)

LINE_ITEM_SUFFIXES = ("：", ":", "；", ";", "。")


def clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\u3000", " ")).strip()


def compact_text(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "").replace("\u3000", ""))


def is_major_section_heading(text: str) -> bool:
    normalized = clean_text(text)
    return bool(MAJOR_SECTION_RE.match(normalized)) and len(normalized) <= 40


def is_format_region_heading(text: str) -> bool:
    normalized = compact_text(text)
    if not normalized:
        return False
    return any(token in normalized for token in FORMAT_REGION_TOKENS) and len(normalized) <= 60


def has_business_topic(text: str) -> bool:
    normalized = compact_text(text)
    return any(token in normalized for token in BUSINESS_TOPIC_TOKENS)


def looks_like_list_item_or_field(text: str) -> bool:
    normalized = clean_text(text)
    if not normalized:
        return False
    if normalized.endswith(LINE_ITEM_SUFFIXES) and not ("格式" in normalized or "附件" in normalized):
        return True
    if len(compact_text(normalized)) <= 24 and normalized.endswith(("：", ":")):
        return True
    return False


def looks_like_body_sentence(text: str) -> bool:
    normalized = clean_text(text)
    compact = compact_text(normalized)
    if not compact:
        return False
    if len(compact) > 50:
        return True
    return any(mark in normalized for mark in ("。", "；", ";")) and not (
        APPENDIX_TITLE_RE.match(normalized) or FORMAT_CODE_RE.search(compact)
    )


def title_strength(text: str, block: dict) -> tuple[int, list[str]]:
    normalized = clean_text(text)
    compact = compact_text(normalized)
    signals: list[str] = []
    score = 0
    if not compact:
        return 0, []
    if is_format_region_heading(normalized):
        return 0, []
    if bool(APPENDIX_TITLE_RE.match(normalized)):
        score += 35
        signals.append("appendix_prefix")
    if "格式" in compact or "模板" in compact or "样式" in compact:
        score += 25
        signals.append("template_word")
    if FORMAT_CODE_RE.search(compact):
        score += 25
        signals.append("format_code")
    if SUB_TABLE_CODE_RE.search(normalized):
        score += 24
        signals.append("sub_table_code")
    if LETTER_PREFIX_CODE_RE.search(normalized):
        score += 22
        signals.append("letter_prefix_code")
    if bool(block.get("isLikelyHeading")):
        score += 18
        signals.append("heading_style")
    if bool(block.get("isCentered")):
        score += 10
        signals.append("centered")
    if bool(block.get("isPageFirstNonEmpty")):
        score += 18
        signals.append("page_first_line")
    if has_business_topic(compact):
        score += 15
        signals.append("business_topic")
        if bool(block.get("isPageFirstNonEmpty") or block.get("hasPageBreakBefore") or block.get("isLikelyHeading")):
            score += 12
            signals.append("structured_business_topic")
    if len(compact) <= 36:
        score += 8
        signals.append("short_line")
    position_in_page = block.get("positionInPageSegment")
    if isinstance(position_in_page, int) and position_in_page <= 5 and (
        "appendix_prefix" in signals
        or "sub_table_code" in signals
        or "letter_prefix_code" in signals
    ):
        score += 18
        signals.append("near_page_start")
    if looks_like_body_sentence(normalized):
        score -= 45
        signals.append("body_sentence_penalty")
    if looks_like_list_item_or_field(normalized) and not FORMAT_CODE_RE.search(compact):
        score -= 30
        signals.append("field_like_penalty")
    if len(compact) > 60:
        score -= 40
        signals.append("long_line_penalty")
    return score, signals
