import pytest

from app.services.material_certificate_time import (
    _is_retryable_stale_not_found_meta,
    _ensure_manual_date_order,
    _merge_ai_certificate_result,
    _parse_ai_certificate_reply,
    _should_accept_text_without_ocr,
    DATE_ORDER_WARNING,
    dedupe_certificate_rows,
    extract_certificate_time_fields,
)
from app.services.peripheral import PeripheralError


def test_extract_certificate_time_fields_from_labeled_certificate_text() -> None:
    text = """
    风能产品符合证明
    证书编号：CQC250304413272200
    发证日期：2025 年 04 月 10 日
    有效期至：2027 年 04 月 09 日
    """

    result = extract_certificate_time_fields(text)

    assert result["status"] == "extracted"
    assert result["issueDate"] == "2025-04-10"
    assert result["expiryDate"] == "2027-04-09"
    assert result["confidence"] >= 90
    assert "发证日期" in result["evidence"]["issueDate"]
    assert "有效期至" in result["evidence"]["expiryDate"]


def test_extract_certificate_time_fields_without_expiry_label_keeps_expiry_empty() -> None:
    result = extract_certificate_time_fields("签章页 2025.04.10 证书正文 2027.04.09")

    assert result["issueDate"] == "2025-04-10"
    assert result["expiryDate"] == ""
    assert result["status"] == "extracted"


def test_extract_certificate_time_fields_uses_last_date_for_validity_range() -> None:
    result = extract_certificate_time_fields("发证日期：2025-04-10\n有效期：2025-04-10 至 2027-04-09")

    assert result["issueDate"] == "2025-04-10"
    assert result["expiryDate"] == "2027-04-09"


def test_extract_certificate_time_fields_year_month_expiry_uses_month_end() -> None:
    result = extract_certificate_time_fields("发证日期：2025年4月10日\n有效期至：2027年4月")

    assert result["issueDate"] == "2025-04-10"
    assert result["expiryDate"] == "2027-04-30"
    assert result["status"] == "extracted"
    assert "按月末推定" in result["evidence"]["expiryDate"]


def test_extract_certificate_time_fields_derives_expiry_from_duration() -> None:
    result = extract_certificate_time_fields("发证日期：2025年4月10日\n有效期：三年")

    assert result["issueDate"] == "2025-04-10"
    assert result["expiryDate"] == "2028-04-09"
    assert "推算" in result["evidence"]["expiryDate"]


def test_extract_certificate_time_fields_marks_long_term_certificate() -> None:
    result = extract_certificate_time_fields("发证日期：2025年4月10日\n本证书长期有效")

    assert result["issueDate"] == "2025-04-10"
    assert result["expiryDate"] == ""
    assert result["longTerm"] is True
    assert result["status"] == "extracted"


def test_extract_certificate_time_fields_unlabeled_dates_only_fill_issue() -> None:
    result = extract_certificate_time_fields("签章页 2027.04.09 证书正文 2025.04.10")

    assert result["issueDate"] == "2025-04-10"
    assert result["expiryDate"] == ""
    assert result["warnings"] == []


def test_extract_certificate_time_fields_issue_only_certificate() -> None:
    result = extract_certificate_time_fields("检验报告\n签发日期：2025年4月10日\n报告编号 2024-001")

    assert result["issueDate"] == "2025-04-10"
    assert result["expiryDate"] == ""
    assert result["longTerm"] is False
    assert result["status"] == "extracted"


def test_extract_certificate_time_fields_warns_on_labeled_order_conflict() -> None:
    result = extract_certificate_time_fields("发证日期：2027年4月10日\n有效期至：2025年4月9日")

    assert result["warnings"] == [DATE_ORDER_WARNING]
    assert result["confidence"] <= 40


def test_extract_certificate_time_fields_rejects_impossible_calendar_date() -> None:
    result = extract_certificate_time_fields("发证日期：2025年2月30日\n有效期至：2027年4月9日")

    assert result["issueDate"] != "2025-02-30"
    assert result["expiryDate"] == "2027-04-09"


def test_extract_certificate_time_fields_range_on_following_line() -> None:
    result = extract_certificate_time_fields("有效期\n自2024年1月1日至2027年12月31日止")

    assert result["expiryDate"] == "2027-12-31"


def test_ensure_manual_date_order_rejects_issue_after_expiry() -> None:
    _ensure_manual_date_order("2025-04-10", "2027-04-09")
    _ensure_manual_date_order("", "2027-04-09")
    with pytest.raises(PeripheralError):
        _ensure_manual_date_order("2027-04-10", "2025-04-09")


def test_parse_ai_certificate_reply_validates_json_and_order() -> None:
    assert _parse_ai_certificate_reply(
        '这里是结果 {"issueDate": "2025-04-10", "expiryDate": "2027-04-09", "longTerm": false, "reason": "标签命中"}'
    ) == {"issueDate": "2025-04-10", "expiryDate": "2027-04-09", "longTerm": False, "reason": "标签命中"}
    assert _parse_ai_certificate_reply('{"issueDate": "2027-04-10", "expiryDate": "2025-04-09"}') == {}
    assert _parse_ai_certificate_reply("完全不是 JSON") == {}
    assert _parse_ai_certificate_reply('{"issueDate": "", "expiryDate": "", "longTerm": false}') == {}


def test_merge_ai_certificate_result_fills_missing_expiry() -> None:
    rule_meta = {
        "issueDate": "2025-04-10",
        "expiryDate": "",
        "longTerm": False,
        "warnings": [],
        "confidence": 45,
        "evidence": {"issueDate": "发证日期：2025年4月10日", "expiryDate": ""},
        "dates": ["2025-04-10"],
        "status": "extracted",
    }
    merged = _merge_ai_certificate_result(
        rule_meta,
        {"issueDate": "2025-04-10", "expiryDate": "2027-04-09", "longTerm": False, "reason": "原文有效期至"},
    )

    assert merged["expiryDate"] == "2027-04-09"
    assert merged["status"] == "extracted"
    assert merged["confidence"] >= 70
    assert merged["aiAssisted"] is True
    assert merged["evidence"]["aiReason"] == "原文有效期至"


def test_merge_ai_certificate_result_keeps_rule_result_when_ai_adds_nothing() -> None:
    rule_meta = {
        "issueDate": "2025-04-10",
        "expiryDate": "2027-04-09",
        "longTerm": False,
        "warnings": [],
        "confidence": 100,
        "evidence": {},
        "dates": [],
        "status": "extracted",
    }
    assert _merge_ai_certificate_result(rule_meta, {"issueDate": "2025-04-10", "expiryDate": "", "longTerm": False}) is rule_meta


def test_pdf_text_without_dates_falls_through_to_ocr() -> None:
    assert not _should_accept_text_without_ocr(suffix=".pdf", text="产品认证证书 CQC24030446050")
    assert _should_accept_text_without_ocr(
        suffix=".pdf",
        text="发证日期：2024 年 10 月 16 日\n有效期至：2029 年 09 月 19 日",
    )


def test_stale_pdf_text_not_found_meta_is_retryable() -> None:
    assert _is_retryable_stale_not_found_meta({
        "status": "not_found",
        "source": "pdf_text",
        "issueDate": "",
        "expiryDate": "",
        "dates": [],
    })
    assert not _is_retryable_stale_not_found_meta({
        "status": "not_found",
        "source": "ocr",
        "issueDate": "",
        "expiryDate": "",
        "dates": [],
    })


def test_dedupe_certificate_rows_uses_folder_path_and_name_as_unique_key() -> None:
    rows = [
        {
            "fileId": "RAW-0001",
            "name": "型式认证.pdf",
            "folderPath": "技术标/标准文件/EW6.25-220/认证证书",
            "issueDate": "",
            "expiryDate": "",
            "status": "failed",
            "updatedAt": "2026-01-01T00:00:00Z",
        },
        {
            "fileId": "RAW-0002",
            "name": "型式认证.pdf",
            "folderPath": "技术标/标准文件/EW6.25-220/认证证书",
            "issueDate": "2025-01-01",
            "expiryDate": "2029-12-31",
            "status": "extracted",
            "updatedAt": "2026-01-02T00:00:00Z",
        },
        {
            "fileId": "RAW-0003",
            "name": "型式认证.pdf",
            "folderPath": "技术标/标准文件/EW5.0-220/认证证书",
            "issueDate": "2025-01-01",
            "expiryDate": "2029-12-31",
            "status": "extracted",
            "updatedAt": "2026-01-02T00:00:00Z",
        },
    ]

    result = dedupe_certificate_rows(rows)

    assert len(result) == 2
    primary = next(item for item in result if item["folderPath"].endswith("EW6.25-220/认证证书"))
    assert primary["fileId"] == "RAW-0002"
    assert primary["duplicateCount"] == 2
    assert primary["duplicateFileIds"] == ["RAW-0001"]
