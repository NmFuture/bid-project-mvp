from __future__ import annotations

import io
import unittest

import openpyxl

from app.services.material_tag_import import (
    build_preview,
    parse_tag_excel,
)


def _make_excel(rows: list[list]) -> bytes:
    """构造一个最小 Excel（含表头），返回字节流。"""

    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "EW6.25-220"
    header = ["一级", "二级", "三级", None, None, "文件名称", "属性1", "属性2", "属性3"]
    worksheet.append(header)
    for row in rows:
        worksheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _file(file_id: str, name: str, folder_path: str, tags: list[str] | None = None) -> dict:
    return {"id": file_id, "name": name, "folderPath": folder_path, "tags": tags or []}


class ParseTagExcelTests(unittest.TestCase):
    def test_parses_file_name_and_attribute_tags(self) -> None:
        data = _make_excel(
            [
                ["标准文件", "EW6.25-220", "部件", None, None, "变桨系统", "EW6.25-220", "部件", "变桨系统"],
            ]
        )
        rows = parse_tag_excel(data)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].file_name, "变桨系统")
        self.assertEqual(rows[0].tags, ["EW6.25-220", "部件", "变桨系统"])
        self.assertEqual(rows[0].level_path, ["标准文件", "EW6.25-220", "部件"])

    def test_skips_empty_and_placeholder_rows(self) -> None:
        data = _make_excel(
            [
                [None, None, None, None, None, "", "EW6.25-220", "专题", None],
                ["标准文件", "EW6.25-220", "专题", None, None, "待填写-设备运行和维护专题", "EW6.25-220", "专题", None],
                ["标准文件", "EW6.25-220", "专题", None, None, "电网友好性专题", "EW6.25-220", "专题", None],
            ]
        )
        rows = parse_tag_excel(data)
        self.assertEqual([row.file_name for row in rows], ["电网友好性专题"])

    def test_dedupes_attribute_tags(self) -> None:
        data = _make_excel(
            [
                ["标准文件", "EW6.25-220", "专题", None, None, "概述", "专题", "专题", "概述"],
            ]
        )
        rows = parse_tag_excel(data)
        self.assertEqual(rows[0].tags, ["专题", "概述"])

    def test_dotted_model_name_not_treated_as_extension(self) -> None:
        # 文件名里含机型号小数点（EW6.25-220），不能被当成扩展名截断
        data = _make_excel(
            [
                ["标准文件", "EW6.25-220", "机型参数表", None, None, "EW6.25-220机型参数", "EW6.25-220", "机型参数表", None],
            ]
        )
        rows = parse_tag_excel(data)
        self.assertEqual(rows[0].file_name, "EW6.25-220机型参数")


class BuildPreviewTests(unittest.TestCase):
    def test_exact_match_by_stem_ignores_extension(self) -> None:
        rows = parse_tag_excel(
            _make_excel(
                [["标准文件", "EW6.25-220", "部件", None, None, "变桨系统", "EW6.25-220", "部件", "变桨系统"]]
            )
        )
        files = [_file("RAW-0001", "变桨系统.docx", "技术标/通用素材/部件")]
        preview = build_preview(rows, files)
        self.assertEqual(len(preview["matched"]), 1)
        matched = preview["matched"][0]
        self.assertEqual(matched["fileId"], "RAW-0001")
        self.assertEqual(matched["mergedTags"], ["EW6.25-220", "部件", "变桨系统"])
        self.assertEqual(preview["stats"]["matched"], 1)

    def test_match_when_name_contains_dotted_model_number(self) -> None:
        # 回归：含 EW6.25-220 这类小数点的文件名必须能精确匹配
        rows = parse_tag_excel(
            _make_excel(
                [["标准文件", "EW6.25-220", "认证证书", None, None,
                  "EW6.25-220上海电气低压穿越评估20241125（上海电气）CEPRI24WT1108R01",
                  "EW6.25-220", "认证证书", None]]
            )
        )
        files = [
            _file(
                "RAW-0100",
                "EW6.25-220上海电气低压穿越评估20241125（上海电气）CEPRI24WT1108R01.pdf",
                "技术标/标准文件/EW6.25-220/认证证书",
            )
        ]
        preview = build_preview(rows, files)
        self.assertEqual(len(preview["matched"]), 1)
        self.assertEqual(preview["matched"][0]["fileId"], "RAW-0100")
        self.assertEqual(preview["unmatched"], [])

    def test_append_dedup_with_existing_tags(self) -> None:
        rows = parse_tag_excel(
            _make_excel(
                [["标准文件", "EW6.25-220", "部件", None, None, "机舱", "EW6.25-220", "部件", "机舱"]]
            )
        )
        files = [_file("RAW-0002", "机舱.pdf", "技术标/通用素材/部件", tags=["EW6.25-220", "旧标签"])]
        preview = build_preview(rows, files)
        matched = preview["matched"][0]
        # 原有的 EW6.25-220 不重复，旧标签保留，新标签追加
        self.assertEqual(matched["existingTags"], ["EW6.25-220", "旧标签"])
        self.assertEqual(matched["mergedTags"], ["EW6.25-220", "旧标签", "部件", "机舱"])
        self.assertEqual(matched["addedTags"], ["部件", "机舱"])

    def test_unmatched_when_no_file(self) -> None:
        rows = parse_tag_excel(
            _make_excel(
                [["标准文件", "EW6.25-220", "部件", None, None, "不存在的文件", "EW6.25-220", "部件", "x"]]
            )
        )
        preview = build_preview(rows, [_file("RAW-0003", "别的文件.docx", "技术标/通用素材")])
        self.assertEqual(preview["matched"], [])
        self.assertEqual(len(preview["unmatched"]), 1)
        self.assertEqual(preview["unmatched"][0]["fileName"], "不存在的文件")

    def test_ambiguous_resolved_by_level_path(self) -> None:
        rows = parse_tag_excel(
            _make_excel(
                [["标准文件", "EW6.25-220", "部件", None, None, "概述", "EW6.25-220", "部件", "概述"]]
            )
        )
        files = [
            _file("RAW-0010", "概述.docx", "技术标/通用素材/部件"),
            _file("RAW-0011", "概述.docx", "技术标/通用素材/专题"),
        ]
        preview = build_preview(rows, files)
        # level_path 末级「部件」唯一命中 RAW-0010
        self.assertEqual(preview["ambiguous"], [])
        self.assertEqual(preview["matched"][0]["fileId"], "RAW-0010")

    def test_ambiguous_when_level_path_cannot_disambiguate(self) -> None:
        rows = parse_tag_excel(
            _make_excel(
                [["标准文件", "EW6.25-220", "认证证书", None, None, "概述", "EW6.25-220", "认证证书", None]]
            )
        )
        files = [
            _file("RAW-0010", "概述.docx", "技术标/通用素材/部件"),
            _file("RAW-0011", "概述.docx", "技术标/通用素材/专题"),
        ]
        preview = build_preview(rows, files)
        self.assertEqual(preview["matched"], [])
        self.assertEqual(len(preview["ambiguous"]), 1)
        candidate_ids = {c["fileId"] for c in preview["ambiguous"][0]["candidates"]}
        self.assertEqual(candidate_ids, {"RAW-0010", "RAW-0011"})


if __name__ == "__main__":
    unittest.main()
