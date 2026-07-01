from __future__ import annotations

import json

from app.services.document_nav import build_document_nav


def test_build_document_nav_serializes_pages_tables_quality_and_evidence() -> None:
    nav = build_document_nav(
        document_id="DOC-1",
        source_path="C:/tmp/business.pdf",
        source_engine="docling",
        pages=[{"pageNo": 1, "width": 595, "height": 842, "textDensity": 0.8}],
        blocks=[
            {
                "pageNo": 1,
                "type": "heading",
                "text": "第六章 投标文件格式",
                "bbox": [10, 20, 300, 40],
            }
        ],
        tables=[
            {
                "pageNo": 1,
                "title": "商务偏差表",
                "rows": [["条款号", "偏差说明"], ["1", "无"]],
                "bbox": [20, 80, 500, 220],
            }
        ],
        images=[{"pageNo": 1, "path": "images/page-1.png", "bbox": [0, 0, 595, 842]}],
        quality={"engine": "docling", "status": "completed", "warnings": []},
    )

    json.dumps(nav, ensure_ascii=False)

    assert nav["schemaVersion"] == "business-document-nav-v1"
    assert nav["sourceEngine"] == "docling"
    assert nav["documents"][0]["id"] == "DOC-1"
    assert nav["pages"][0]["pageNo"] == 1
    assert nav["blocks"][0]["evidenceId"] == "DOC-1:P0001:B000001"
    assert nav["tables"][0]["evidenceId"] == "DOC-1:P0001:T000001"
    assert nav["images"][0]["evidenceId"] == "DOC-1:P0001:I000001"
    assert {item["id"] for item in nav["evidence"]} == {
        "DOC-1:P0001:B000001",
        "DOC-1:P0001:T000001",
        "DOC-1:P0001:I000001",
    }
    assert nav["evidence"][0]["sourceText"] == "第六章 投标文件格式"
    assert nav["quality"]["status"] == "completed"
