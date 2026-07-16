from __future__ import annotations

from typing import Any


TABLE_KEYWORDS = ("商务偏差表", "投标报价表", "报价表", "开标一览表", "资格审查")
LOW_TEXT_DENSITY_THRESHOLD = 0.05


def evaluate_document_nav_quality(document_nav: dict[str, Any]) -> dict[str, Any]:
    quality = document_nav.get("quality") if isinstance(document_nav.get("quality"), dict) else {}
    warnings: list[str] = [str(item) for item in quality.get("warnings") or []]
    fallback_used = bool(quality.get("fallbackUsed"))
    if str(quality.get("status") or "").lower() == "failed":
        return {
            "status": "fallback" if fallback_used else "failed",
            "ocrPages": [],
            "fallbackUsed": fallback_used,
            "reviewRequired": not fallback_used,
            "warnings": warnings,
        }

    pages = document_nav.get("pages") if isinstance(document_nav.get("pages"), list) else []
    ocr_pages: list[int] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_no = int(page.get("pageNo") or 0)
        density = float(page.get("textDensity") or 0)
        if page_no and density <= LOW_TEXT_DENSITY_THRESHOLD:
            ocr_pages.append(page_no)
    if ocr_pages:
        warnings.append(f"低文本密度页面需要 OCR 兜底：{', '.join(str(page) for page in ocr_pages)}")

    tables = document_nav.get("tables") if isinstance(document_nav.get("tables"), list) else []
    blocks = document_nav.get("blocks") if isinstance(document_nav.get("blocks"), list) else []
    combined_text = "\n".join(str(block.get("text") or "") for block in blocks if isinstance(block, dict))
    if not tables:
        for keyword in TABLE_KEYWORDS:
            if keyword in combined_text:
                warnings.append(f"检测到“{keyword}”关键词但 Docling 未输出表格，需要人工复核。")
                break

    review_required = bool(ocr_pages) or any("人工复核" in warning for warning in warnings)
    return {
        "status": "needs_review" if review_required else "completed",
        "ocrPages": ocr_pages,
        "fallbackUsed": False,
        "reviewRequired": review_required,
        "warnings": warnings,
    }
