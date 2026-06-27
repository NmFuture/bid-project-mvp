from __future__ import annotations

import json
from pathlib import Path

from app.services.mineru_nav_adapter import convert_mineru_output_to_document_nav


def test_convert_mineru_output_to_document_nav_reads_markdown_json_tables_and_images(tmp_path) -> None:
    output_dir = tmp_path / "mineru"
    output_dir.mkdir()
    (output_dir / "document.md").write_text(
        "\n".join(
            [
                "# 第六章 投标文件格式",
                "",
                "一、投标函",
                "",
                "| 条款 | 响应 |",
                "| --- | --- |",
                "| 商务偏差表 | 无偏差 |",
            ]
        ),
        encoding="utf-8",
    )
    (output_dir / "document.json").write_text(
        json.dumps(
            {
                "pages": [
                    {"pageNo": 1, "width": 595, "height": 842, "textDensity": 0.82},
                ],
                "blocks": [
                    {
                        "type": "title",
                        "text": "第六章 投标文件格式",
                        "pageNo": 1,
                        "bbox": [10, 20, 300, 40],
                    },
                    {
                        "type": "text",
                        "text": "一、投标函",
                        "pageNo": 1,
                        "bbox": [10, 60, 120, 80],
                    },
                ],
                "tables": [
                    {
                        "title": "商务偏差表",
                        "pageNo": 1,
                        "bbox": [20, 100, 500, 220],
                        "rows": [["条款", "响应"], ["商务偏差表", "无偏差"]],
                        "markdown": "| 条款 | 响应 |",
                    }
                ],
                "images": [
                    {"pageNo": 1, "path": "images/page-1.png", "bbox": [0, 0, 595, 842]},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    nav = convert_mineru_output_to_document_nav(
        document_id="DOC-1",
        source_path=tmp_path / "source.pdf",
        mineru_output_dir=output_dir,
    )

    assert nav["sourceEngine"] == "mineru"
    assert nav["quality"]["status"] == "completed"
    assert nav["quality"]["pageCount"] == 1
    assert nav["quality"]["tableCount"] == 1
    assert [block["type"] for block in nav["blocks"]][:3] == ["heading", "paragraph", "table"]
    assert any("第六章 投标文件格式" in block["text"] for block in nav["blocks"])
    assert nav["tables"][0]["title"] == "商务偏差表"
    assert nav["tables"][0]["rows"][1] == ["商务偏差表", "无偏差"]
    assert nav["images"][0]["sourcePath"].endswith("images/page-1.png")
    assert nav["evidence"]


def test_convert_mineru_output_to_document_nav_reads_nested_cli_outputs(tmp_path) -> None:
    output_dir = tmp_path / "mineru"
    nested_dir = output_dir / "source" / "auto"
    nested_dir.mkdir(parents=True)
    (nested_dir / "source.md").write_text("# 嵌套标题\n\n正文来自 MinerU\n", encoding="utf-8")
    (nested_dir / "source_middle.json").write_text(
        json.dumps({"pages": [{"pageNo": 1, "textDensity": 0.9}]}, ensure_ascii=False),
        encoding="utf-8",
    )

    nav = convert_mineru_output_to_document_nav(
        document_id="DOC-1",
        source_path=tmp_path / "source.pdf",
        mineru_output_dir=output_dir,
    )

    assert nav["sourceEngine"] == "mineru"
    assert nav["quality"]["pageCount"] == 1
    assert [block["text"] for block in nav["blocks"]] == ["嵌套标题", "正文来自 MinerU"]


def test_convert_mineru_output_to_document_nav_reads_content_list_pages_and_tables(tmp_path) -> None:
    output_dir = tmp_path / "mineru"
    nested_dir = output_dir / "source" / "auto"
    nested_dir.mkdir(parents=True)
    (nested_dir / "source_content_list.json").write_text(
        json.dumps(
            [
                {
                    "type": "text",
                    "text": "第一页标题",
                    "text_level": 1,
                    "bbox": [10, 20, 100, 40],
                    "page_idx": 0,
                },
                {
                    "type": "table",
                    "table_caption": ["采购范围"],
                    "table_body": "<table><tr><td>项目名称</td><td>容量</td></tr><tr><td>普格项目</td><td>260MW</td></tr></table>",
                    "bbox": [20, 80, 500, 200],
                    "page_idx": 8,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    nav = convert_mineru_output_to_document_nav(
        document_id="DOC-1",
        source_path=tmp_path / "source.pdf",
        mineru_output_dir=output_dir,
    )

    assert nav["quality"]["pageCount"] == 9
    assert len(nav["pages"]) == 9
    assert nav["blocks"][0]["type"] == "heading"
    assert nav["blocks"][0]["pageNo"] == 1
    assert nav["tables"][0]["pageNo"] == 9
    assert nav["tables"][0]["title"] == "采购范围"
    assert nav["tables"][0]["rows"] == [["项目名称", "容量"], ["普格项目", "260MW"]]
    assert nav["evidence"][0]["sourceEngine"] == "mineru"
