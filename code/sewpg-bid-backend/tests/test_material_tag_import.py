from __future__ import annotations

import asyncio
import io
import unittest

import openpyxl

from app.services.material_tag_import import (
    build_preview,
    parse_tag_excel,
    same_name_file_ids,
    _merge_preview,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


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


class RecognitionRobustnessTests(unittest.TestCase):
    """识别完善：全角折叠、占位符过滤、属性列同义识别、标签值清洗。"""

    def test_fullwidth_dot_matches_halfwidth_model(self) -> None:
        # Excel 用全角点 EW6．25-220，库里是半角 EW6.25-220 —— 应精确命中
        excel = _make_excel(
            [["标准文件", "EW6.25-220", "机型参数表", None, None,
              "EW6．25-220机型参数", "EW6.25-220", "机型参数表", None]]
        )
        rows = parse_tag_excel(excel)
        files = [_file("RAW-0100", "EW6.25-220机型参数.docx", "技术标/标准文件/EW6.25-220")]
        preview = build_preview(rows, files)
        self.assertEqual(preview["unmatched"], [])
        self.assertEqual(preview["matched"][0]["fileId"], "RAW-0100")

    def test_fullwidth_parens_match_halfwidth(self) -> None:
        excel = _make_excel(
            [["标准文件", "EW6.25-220", "部件", None, None, "变桨系统（一）", "部件", None, None]]
        )
        rows = parse_tag_excel(excel)
        files = [_file("RAW-0101", "变桨系统(一).pdf", "技术标/标准文件/EW6.25-220/部件")]
        preview = build_preview(rows, files)
        self.assertEqual(preview["matched"][0]["fileId"], "RAW-0101")

    def test_skips_extra_placeholder_rows(self) -> None:
        excel = _make_excel(
            [
                ["标准文件", "EW6.25-220", "专题", None, None, "待补充-X", "专题", None, None],
                ["标准文件", "EW6.25-220", "专题", None, None, "无", "专题", None, None],
                ["标准文件", "EW6.25-220", "专题", None, None, "/", "专题", None, None],
                ["标准文件", "EW6.25-220", "专题", None, None, "电网友好性专题", "专题", None, None],
            ]
        )
        rows = parse_tag_excel(excel)
        self.assertEqual([r.file_name for r in rows], ["电网友好性专题"])

    def test_recognizes_alias_tag_headers(self) -> None:
        workbook = openpyxl.Workbook()
        ws = workbook.active
        ws.append(["一级", "二级", "文件名称", "标签1", "分类", "关键词"])
        ws.append(["标准文件", "EW6.25-220", "机舱", "部件", "EW6.25-220", "机舱"])
        buffer = io.BytesIO()
        workbook.save(buffer)
        rows = parse_tag_excel(buffer.getvalue())
        self.assertEqual(rows[0].file_name, "机舱")
        self.assertEqual(rows[0].tags, ["部件", "EW6.25-220", "机舱"])

    def test_cleans_numbered_and_split_tag_values(self) -> None:
        # 单元格内含序号前缀与顿号分隔，应拆分并去前缀
        excel = _make_excel(
            [["标准文件", "EW6.25-220", "部件", None, None, "机舱",
              "1. 部件、变桨系统", "（2）EW6.25-220", "-"]]
        )
        rows = parse_tag_excel(excel)
        self.assertEqual(rows[0].tags, ["部件", "变桨系统", "EW6.25-220"])


class OverwriteModeTests(unittest.TestCase):
    """覆盖模式:Excel 总表为标签唯一真相,有标签整条替换、留空保留原标签。"""

    def test_overwrite_replaces_existing_tags(self) -> None:
        rows = parse_tag_excel(
            _make_excel(
                [["标准文件", "EW6.25-220", "部件", None, None, "机舱", "新标签A", "新标签B", None]]
            )
        )
        files = [_file("RAW-0002", "机舱.pdf", "技术标/通用素材/部件", tags=["旧标签1", "旧标签2"])]
        preview = build_preview(rows, files, mode="overwrite")
        matched = preview["matched"][0]
        # 原标签被整条替换为 Excel 标签
        self.assertEqual(matched["existingTags"], ["旧标签1", "旧标签2"])
        self.assertEqual(matched["incomingTags"], ["新标签A", "新标签B"])
        self.assertEqual(matched["mergedTags"], ["新标签A", "新标签B"])
        self.assertEqual(matched["removedTags"], ["旧标签1", "旧标签2"])

    def test_overwrite_keeps_existing_when_excel_tags_empty(self) -> None:
        # 防误删保险:incoming 为空时,覆盖模式保留原标签(整条不动)。
        # 注:parse_tag_excel 会直接跳过无标签的行(material_tag_import.py:229),
        # 所以这种情况在真实 Excel 流程里不会发生;此处直接对 _merge_preview 验证该保险分支。
        merge = _merge_preview(["旧标签1", "旧标签2"], [], mode="overwrite")
        self.assertEqual(merge["mergedTags"], ["旧标签1", "旧标签2"])
        self.assertEqual(merge["removedTags"], [])

    def test_merge_mode_still_unions(self) -> None:
        # 合并模式(默认)行为不变:原标签 ∪ 新标签
        rows = parse_tag_excel(
            _make_excel(
                [["标准文件", "EW6.25-220", "部件", None, None, "机舱", "新标签A", None, None]]
            )
        )
        files = [_file("RAW-0002", "机舱.pdf", "技术标/通用素材/部件", tags=["旧标签1"])]
        preview = build_preview(rows, files, mode="merge")
        self.assertEqual(preview["matched"][0]["mergedTags"], ["旧标签1", "新标签A"])


class CrossModelReuseTests(unittest.TestCase):
    """R01-B06-02：同名文件跨机型批量应用。

    preview 对多处同名匹配的行给出 matches 计数；commit 支持
    applyToAllMatches 把该行标签写入目标子树内所有同名文件。
    """

    def test_matched_entry_carries_matches_count_when_disambiguated(self) -> None:
        rows = parse_tag_excel(
            _make_excel(
                [["标准文件", "EW6.25-220", "部件", None, None, "概述", "EW6.25-220", "部件", None]]
            )
        )
        files = [
            _file("RAW-0010", "概述.docx", "技术标/标准文件/EW6.25-220/部件"),
            _file("RAW-0011", "概述.docx", "技术标/标准文件/EW3.0-155/部件"),
        ]
        preview = build_preview(rows, files)
        self.assertEqual(preview["matched"][0]["fileId"], "RAW-0010")
        self.assertEqual(preview["matched"][0]["matches"], 2)

    def test_single_match_carries_matches_count_one(self) -> None:
        rows = parse_tag_excel(
            _make_excel(
                [["标准文件", "EW6.25-220", "部件", None, None, "机舱", "部件", None, None]]
            )
        )
        files = [_file("RAW-0002", "机舱.pdf", "技术标/通用素材/部件")]
        preview = build_preview(rows, files)
        self.assertEqual(preview["matched"][0]["matches"], 1)

    def test_ambiguous_entry_carries_matches_count(self) -> None:
        rows = parse_tag_excel(
            _make_excel(
                [["标准文件", "EW6.25-220", "认证证书", None, None, "概述", "认证证书", None, None]]
            )
        )
        files = [
            _file("RAW-0010", "概述.docx", "技术标/通用素材/部件"),
            _file("RAW-0011", "概述.docx", "技术标/通用素材/专题"),
            _file("RAW-0012", "概述.docx", "技术标/通用素材/其他"),
        ]
        preview = build_preview(rows, files)
        self.assertEqual(len(preview["ambiguous"]), 1)
        self.assertEqual(preview["ambiguous"][0]["matches"], 3)

    def test_same_name_file_ids_matches_by_stem_and_fullwidth(self) -> None:
        files = [
            _file("RAW-0010", "概述.docx", "技术标/标准文件/EW6.25-220/部件"),
            _file("RAW-0011", "概述.pdf", "技术标/标准文件/EW3.0-155/部件"),
            _file("RAW-0012", "其他.docx", "技术标/标准文件/EW3.0-155/部件"),
        ]
        self.assertEqual(
            same_name_file_ids(files, "概述.xlsx"),
            ["RAW-0010", "RAW-0011"],
        )
        self.assertEqual(same_name_file_ids(files, ""), [])
        self.assertEqual(same_name_file_ids(files, "不存在"), [])


class CommitApplyToAllTests(unittest.TestCase):
    """commit：applyToAllMatches 批量应用 + 精确 fileId 行为不变。"""

    def setUp(self) -> None:
        from app.services.technical_material_store import TechnicalMaterialStore

        self.store = TechnicalMaterialStore()
        self.files = [
            _file("RAW-0001", "概述.docx", "技术标/标准文件/EW6.25-220/部件", tags=["旧A"]),
            _file("RAW-0002", "概述.docx", "技术标/标准文件/EW3.0-155/部件", tags=["旧B"]),
            _file("RAW-0003", "别的文件.pdf", "技术标/标准文件/EW6.25-220/专题"),
        ]
        self.writes: dict[str, list[str]] = {}
        self.subtree_calls = 0

        async def fake_subtree(target_path: str):
            self.subtree_calls += 1
            return self.files

        async def fake_set_index_tags(target_id, tags, *, merge=False):
            known = {f["id"]: f for f in self.files}
            if target_id not in known:
                raise LookupError(f"未在索引中找到节点：{target_id}")
            self.writes[target_id] = list(tags)
            return {"id": target_id, "name": known[target_id]["name"], "tags": list(tags)}

        self.store._raw_subtree_files = fake_subtree
        self.store.set_index_tags = fake_set_index_tags

    def test_apply_to_all_matches_writes_every_same_name_file(self) -> None:
        result = _run(
            self.store.raw_tag_import_commit(
                items=[{"fileName": "概述", "tags": ["跨机型标签"], "applyToAllMatches": True}],
                target_path="技术标",
            )
        )
        self.assertEqual(set(self.writes), {"RAW-0001", "RAW-0002"})
        self.assertEqual(self.writes["RAW-0001"], ["跨机型标签"])
        self.assertEqual(self.writes["RAW-0002"], ["跨机型标签"])
        self.assertEqual(len(result["succeeded"]), 2)
        self.assertEqual(result["failed"], [])
        self.assertIn("成功 2 个", result["message"])

    def test_exact_file_id_behavior_unchanged(self) -> None:
        result = _run(
            self.store.raw_tag_import_commit(
                items=[{"fileId": "RAW-0003", "tags": ["精确标签"]}]
            )
        )
        self.assertEqual(self.writes, {"RAW-0003": ["精确标签"]})
        self.assertEqual(len(result["succeeded"]), 1)
        self.assertEqual(self.subtree_calls, 0, "精确 fileId 导入不应触发子树扫描")

    def test_apply_to_all_without_same_name_file_fails_row(self) -> None:
        result = _run(
            self.store.raw_tag_import_commit(
                items=[{"fileName": "不存在的文件", "tags": ["x"], "applyToAllMatches": True}],
                target_path="技术标",
            )
        )
        self.assertEqual(self.writes, {})
        self.assertEqual(result["succeeded"], [])
        self.assertEqual(len(result["failed"]), 1)
        self.assertIn("未找到同名文件", result["failed"][0]["message"])

    def test_missing_file_id_still_fails(self) -> None:
        result = _run(self.store.raw_tag_import_commit(items=[{"tags": ["x"]}]))
        self.assertEqual(len(result["failed"]), 1)
        self.assertIn("缺少文件 ID", result["failed"][0]["message"])
        self.assertEqual(self.subtree_calls, 0)


if __name__ == "__main__":
    unittest.main()
