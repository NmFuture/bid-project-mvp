from app.services.material_certificate_time import (
    _is_retryable_stale_not_found_meta,
    _should_accept_text_without_ocr,
    dedupe_certificate_rows,
    extract_certificate_time_fields,
)


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


def test_extract_certificate_time_fields_falls_back_to_ordered_dates() -> None:
    result = extract_certificate_time_fields("签章页 2025.04.10 证书正文 2027.04.09")

    assert result["issueDate"] == "2025-04-10"
    assert result["expiryDate"] == "2027-04-09"
    assert result["status"] == "extracted"


def test_extract_certificate_time_fields_uses_last_date_for_validity_range() -> None:
    result = extract_certificate_time_fields("发证日期：2025-04-10\n有效期：2025-04-10 至 2027-04-09")

    assert result["issueDate"] == "2025-04-10"
    assert result["expiryDate"] == "2027-04-09"


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
