from __future__ import annotations

from app.services.document_parse_quality import evaluate_document_nav_quality


def test_evaluate_document_nav_quality_flags_low_text_density_pages_for_ocr() -> None:
    report = evaluate_document_nav_quality(
        {
            "pages": [
                {"pageNo": 1, "textDensity": 0.02},
                {"pageNo": 2, "textDensity": 0.75},
            ],
            "blocks": [],
            "tables": [],
            "quality": {"status": "completed"},
        }
    )

    assert report["status"] == "needs_review"
    assert report["ocrPages"] == [1]
    assert report["reviewRequired"] is True
    assert any("低文本密度" in warning for warning in report["warnings"])


def test_evaluate_document_nav_quality_requires_review_when_table_keywords_have_no_tables() -> None:
    report = evaluate_document_nav_quality(
        {
            "pages": [{"pageNo": 1, "textDensity": 0.8}],
            "blocks": [{"text": "本章包含商务偏差表，请投标人填写。", "pageNo": 1}],
            "tables": [],
            "quality": {"status": "completed"},
        }
    )

    assert report["status"] == "needs_review"
    assert report["reviewRequired"] is True
    assert any("商务偏差表" in warning for warning in report["warnings"])


def test_evaluate_document_nav_quality_marks_mineru_failure_as_fallback() -> None:
    report = evaluate_document_nav_quality(
        {
            "pages": [],
            "blocks": [],
            "tables": [],
            "quality": {"status": "failed", "fallbackUsed": True, "warnings": ["mineru missing"]},
        }
    )

    assert report["status"] == "fallback"
    assert report["fallbackUsed"] is True
    assert "mineru missing" in report["warnings"]
