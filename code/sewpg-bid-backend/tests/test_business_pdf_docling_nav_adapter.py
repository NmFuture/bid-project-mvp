from __future__ import annotations

import json

from app.services.docling_nav_adapter import convert_docling_output_to_document_nav


def test_convert_docling_output_to_document_nav_reads_pages_texts_tables_and_pictures(tmp_path) -> None:
    output_dir = tmp_path / "docling"
    output_dir.mkdir()
    (output_dir / "docling.md").write_text(
        "# 第六章 投标文件格式\n\n一、投标函\n\n| 条款 | 响应 |\n| --- | --- |\n| 商务偏差表 | 无偏差 |\n",
        encoding="utf-8",
    )
    (output_dir / "docling_document.json").write_text(
        json.dumps(
            {
                "pages": {
                    "1": {"size": {"width": 595, "height": 842}},
                    "2": {"size": {"width": 595, "height": 842}},
                },
                "texts": [
                    {
                        "label": "section_header",
                        "text": "第六章 投标文件格式",
                        "prov": [{"page_no": 1, "bbox": {"l": 10, "t": 20, "r": 300, "b": 40}}],
                    },
                    {
                        "label": "text",
                        "text": "一、投标函",
                        "prov": [{"page_no": 1, "bbox": {"l": 10, "t": 60, "r": 120, "b": 80}}],
                    },
                ],
                "tables": [
                    {
                        "caption_text": "商务偏差表",
                        "prov": [{"page_no": 2, "bbox": {"l": 20, "t": 100, "r": 500, "b": 220}}],
                        "data": {
                            "table_cells": [
                                {
                                    "start_row_offset_idx": 0,
                                    "end_row_offset_idx": 1,
                                    "start_col_offset_idx": 0,
                                    "end_col_offset_idx": 1,
                                    "text": "条款",
                                },
                                {
                                    "start_row_offset_idx": 0,
                                    "end_row_offset_idx": 1,
                                    "start_col_offset_idx": 1,
                                    "end_col_offset_idx": 2,
                                    "text": "响应",
                                },
                                {
                                    "start_row_offset_idx": 1,
                                    "end_row_offset_idx": 2,
                                    "start_col_offset_idx": 0,
                                    "end_col_offset_idx": 1,
                                    "text": "商务偏差表",
                                },
                                {
                                    "start_row_offset_idx": 1,
                                    "end_row_offset_idx": 2,
                                    "start_col_offset_idx": 1,
                                    "end_col_offset_idx": 2,
                                    "text": "无偏差",
                                },
                            ]
                        },
                    }
                ],
                "pictures": [
                    {
                        "caption_text": "图1 风电场低电压穿越要求",
                        "image": {"uri": "pictures/page-2-chart.png"},
                        "prov": [{"page_no": 2, "bbox": {"l": 30, "t": 240, "r": 520, "b": 420}}],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    nav = convert_docling_output_to_document_nav(
        document_id="DOC-1",
        source_path=tmp_path / "source.pdf",
        docling_output_dir=output_dir,
    )

    assert nav["sourceEngine"] == "docling"
    assert nav["quality"]["engine"] == "docling"
    assert nav["quality"]["status"] == "completed"
    assert nav["quality"]["pageCount"] == 2
    assert nav["quality"]["tableCount"] == 1
    assert [block["type"] for block in nav["blocks"]] == ["heading", "paragraph", "table"]
    assert nav["blocks"][0]["text"] == "第六章 投标文件格式"
    assert nav["blocks"][0]["bbox"] == [10, 20, 300, 40]
    assert nav["tables"][0]["title"] == "商务偏差表"
    assert nav["tables"][0]["rows"] == [["条款", "响应"], ["商务偏差表", "无偏差"]]
    assert nav["images"][0]["pageNo"] == 2
    assert nav["images"][0]["sourcePath"].endswith("pictures/page-2-chart.png")
    assert nav["images"][0]["caption"] == "图1 风电场低电压穿越要求"
    assert nav["images"][0]["bbox"] == [30, 240, 520, 420]
    assert {item["sourceEngine"] for item in nav["evidence"]} == {"docling"}


def test_convert_docling_output_to_document_nav_keeps_picture_without_exported_image_uri(tmp_path) -> None:
    output_dir = tmp_path / "docling"
    output_dir.mkdir()
    (output_dir / "docling_document.json").write_text(
        json.dumps(
            {
                "pages": {"1": {"size": {"width": 595, "height": 842}}},
                "texts": [],
                "tables": [],
                "pictures": [
                    {
                        "self_ref": "#/pictures/0",
                        "label": "picture",
                        "prov": [
                            {
                                "page_no": 1,
                                "bbox": {
                                    "l": 69.5,
                                    "t": 758.7,
                                    "r": 257.4,
                                    "b": 725.9,
                                    "coord_origin": "BOTTOMLEFT",
                                },
                            }
                        ],
                        "captions": [{"text": "投标文件封面标识"}],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    nav = convert_docling_output_to_document_nav(
        document_id="DOC-1",
        source_path=tmp_path / "source.pdf",
        docling_output_dir=output_dir,
    )

    assert len(nav["images"]) == 1
    assert nav["images"][0]["pageNo"] == 1
    assert nav["images"][0]["sourcePath"] == ""
    assert nav["images"][0]["caption"] == "投标文件封面标识"
    assert nav["images"][0]["bbox"] == [69.5, 758.7, 257.4, 725.9]
    assert nav["images"][0]["evidenceId"] == "DOC-1:P0001:I000001"
    assert nav["evidence"][0]["kind"] == "image"


def test_convert_docling_output_to_document_nav_keeps_tables_in_page_reading_order(tmp_path) -> None:
    output_dir = tmp_path / "docling"
    output_dir.mkdir()
    (output_dir / "docling_document.json").write_text(
        json.dumps(
            {
                "pages": {"1": {"size": {"width": 600, "height": 800}}},
                "texts": [
                    {
                        "label": "section_header",
                        "text": "Commercial deviation table",
                        "prov": [{"page_no": 1, "bbox": {"l": 80, "t": 760, "r": 300, "b": 740}}],
                    },
                    {
                        "label": "text",
                        "text": "Fill all commercial deviations here.",
                        "prov": [{"page_no": 1, "bbox": {"l": 80, "t": 520, "r": 500, "b": 500}}],
                    },
                    {
                        "label": "section_header",
                        "text": "Next template",
                        "prov": [{"page_no": 1, "bbox": {"l": 80, "t": 450, "r": 260, "b": 430}}],
                    },
                ],
                "tables": [
                    {
                        "prov": [{"page_no": 1, "bbox": {"l": 80, "t": 730, "r": 520, "b": 560}}],
                        "data": {
                            "table_cells": [
                                {
                                    "start_row_offset_idx": 0,
                                    "end_row_offset_idx": 1,
                                    "start_col_offset_idx": 0,
                                    "end_col_offset_idx": 1,
                                    "text": "Clause",
                                },
                                {
                                    "start_row_offset_idx": 0,
                                    "end_row_offset_idx": 1,
                                    "start_col_offset_idx": 1,
                                    "end_col_offset_idx": 2,
                                    "text": "Response",
                                },
                                {
                                    "start_row_offset_idx": 1,
                                    "end_row_offset_idx": 2,
                                    "start_col_offset_idx": 0,
                                    "end_col_offset_idx": 1,
                                    "text": "1",
                                },
                                {
                                    "start_row_offset_idx": 1,
                                    "end_row_offset_idx": 2,
                                    "start_col_offset_idx": 1,
                                    "end_col_offset_idx": 2,
                                    "text": "No deviation",
                                },
                            ]
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    nav = convert_docling_output_to_document_nav(
        document_id="DOC-1",
        source_path=tmp_path / "source.pdf",
        docling_output_dir=output_dir,
    )

    assert [block["type"] for block in nav["blocks"]] == ["heading", "table", "paragraph", "heading"]
    assert [block["text"] for block in nav["blocks"]] == [
        "Commercial deviation table",
        "表格",
        "Fill all commercial deviations here.",
        "Next template",
    ]
    assert nav["blocks"][1]["tableId"] == nav["tables"][0]["id"]
    assert nav["tables"][0]["rows"] == [["Clause", "Response"], ["1", "No deviation"]]


def test_convert_docling_output_to_document_nav_defaults_single_text_page_to_bottom_left_order(tmp_path) -> None:
    output_dir = tmp_path / "docling"
    output_dir.mkdir()
    (output_dir / "docling_document.json").write_text(
        json.dumps(
            {
                "pages": {"1": {"size": {"width": 600, "height": 800}}},
                "texts": [
                    {
                        "label": "section_header",
                        "text": "Commercial template",
                        "prov": [{"page_no": 1, "bbox": {"l": 80, "t": 760, "r": 300, "b": 740}}],
                    }
                ],
                "tables": [
                    {
                        "prov": [{"page_no": 1, "bbox": {"l": 80, "t": 730, "r": 520, "b": 560}}],
                        "data": {
                            "table_cells": [
                                {
                                    "start_row_offset_idx": 0,
                                    "end_row_offset_idx": 1,
                                    "start_col_offset_idx": 0,
                                    "end_col_offset_idx": 1,
                                    "text": "Clause",
                                }
                            ]
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    nav = convert_docling_output_to_document_nav(
        document_id="DOC-1",
        source_path=tmp_path / "source.pdf",
        docling_output_dir=output_dir,
    )

    assert [block["type"] for block in nav["blocks"]] == ["heading", "table"]
