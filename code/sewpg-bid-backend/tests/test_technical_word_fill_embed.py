"""正文「待插入」类型单测：占位符文字命中素材名 → 整份 Word 嵌入。

待填写与待插入同构，共用一套精确定位，差别只在查表对象与执行动作：待填写拿占位符
文字查事实表字段取一个值，待插入拿占位符文字查 manifest.embedSources 取一份素材整个
嵌进去。后缀是类型的权威标记，因此混合文件天然支持。
fixture 为脱敏合成数据（通用领域词面，无真实项目数据）。
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

_SRC = (
    Path(__file__).resolve().parents[1]
    / "opencode"
    / "skills"
    / "bid-tech-word-placeholder-filler"
    / "scripts"
    / "run_from_manifest.py"
)
_SPEC = importlib.util.spec_from_file_location("tech_word_filler_embed_under_test", _SRC)
filler = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules["tech_word_filler_embed_under_test"] = filler
_SPEC.loader.exec_module(filler)


class PlaceholderKindTests(unittest.TestCase):
    def test_embed_suffix_is_recognized_as_embed_kind(self) -> None:
        found = filler.find_placeholders("[设备清单，待插入]")

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["kind"], "embed")
        self.assertEqual(found[0]["label"], "设备清单")

    def test_fill_suffixes_stay_fill_kind(self) -> None:
        for text in ("[安全等级，待填写]", "【安全等级, 待补充】", "[安全等级，待确认]"):
            found = filler.find_placeholders(text)
            self.assertEqual(len(found), 1, text)
            self.assertEqual(found[0]["kind"], "fill", text)
            self.assertEqual(found[0]["label"], "安全等级", text)

    def test_prefix_form_without_captured_suffix_stays_fill_kind(self) -> None:
        # `[待填写：字段名]` 捕不到后缀组，仍须按 fill 识别，不能被新分型漏掉
        found = filler.find_placeholders("[待填写：安全等级]")

        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["kind"], "fill")
        self.assertEqual(found[0]["label"], "安全等级")

    def test_plain_bracket_text_is_not_a_placeholder(self) -> None:
        self.assertEqual(filler.find_placeholders("参见[附录三]的说明"), [])

    def test_embed_placeholder_key_matches_spec_style_key(self) -> None:
        # 归一化后与素材名可比：全半角括号、分隔符差异不影响命中
        self.assertEqual(filler.placeholder_key("[设备清单，待插入]"), filler.norm("设备清单"))

    def test_standalone_embed_requires_placeholder_to_own_the_paragraph(self) -> None:
        text = "[设备清单，待插入]"
        self.assertTrue(filler.standalone_embed(text, filler.find_placeholders(text)))

        mixed = "详见[设备清单，待插入]后附材料。"
        self.assertFalse(filler.standalone_embed(mixed, filler.find_placeholders(mixed)))

        fill_only = "[安全等级，待填写]"
        self.assertFalse(filler.standalone_embed(fill_only, filler.find_placeholders(fill_only)))


def _write_embed_source(path: Path, heading: str) -> None:
    from docx import Document

    document = Document()
    document.add_paragraph(heading)
    table = document.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = "部件"
    table.rows[0].cells[1].text = "数量"
    table.rows[1].cells[0].text = "机架"
    table.rows[1].cells[1].text = "12"
    document.save(str(path))


def _write_blank_source(path: Path) -> None:
    from docx import Document

    document = Document()
    document.add_paragraph("一、总体方案")
    document.add_paragraph("本项目安全等级为[安全等级，待填写]。")
    document.add_paragraph("[设备清单，待插入]")
    document.add_paragraph("[价格表，待插入]")
    document.add_paragraph("详见[附件材料，待插入]后附。")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "清单"
    table.rows[0].cells[1].text = "[表内素材，待插入]"
    document.save(str(path))


def _write_range_source(path: Path) -> None:
    """复刻 物流解决方案.docx 的真实结构：并列 H1 各带子节，末章后跟表格。

    二/三/四 是并列一级标题，不是父子——按区间取「二~四」必须带上中间的三。
    """
    from docx import Document

    document = Document()
    for title, level in (
        ("一、数字化运输管理", 1),
        ("1.1 平台简介", 2),
        ("二、项目运输方案", 1),
        ("2.1 大件运输", 2),
        ("2.2 车辆配置", 2),
        ("三、临时设施布置", 1),
        ("四、场内道路建议参数", 1),
        ("4.1 路基宽度", 2),
    ):
        document.add_heading(title, level=level)
        document.add_paragraph(f"{title} 正文")
    table = document.add_table(rows=1, cols=1)
    table.rows[0].cells[0].text = "末章表格"
    document.save(str(path))


def _write_substring_trap_source(path: Path) -> None:
    """复刻 风资源评估报告.docx 的子串陷阱：H2「方案及发电量结果」下挂 H3「发电量结果」。"""
    from docx import Document

    document = Document()
    for title, level in (
        ("方案及发电量结果", 2),
        ("机位方案", 3),
        ("发电量结果", 3),
        ("不确定性分析", 2),
    ):
        document.add_heading(title, level=level)
        document.add_paragraph(f"{title} 正文")
    document.save(str(path))


def _headings(document) -> list[tuple[int, str]]:
    return [
        (filler.heading_level(paragraph), paragraph.text)
        for paragraph in document.paragraphs
        if filler.heading_level(paragraph) is not None
    ]


class HeadingRangeSliceTests(unittest.TestCase):
    """按闭区间截取：起点节 + 中间所有章 + 终点节完整，含头含尾。"""

    def test_closed_range_keeps_start_middle_and_end_sections(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "物流解决方案.docx"
            _write_range_source(source)

            sliced = filler.slice_heading_range(source, "项目运输方案", "场内道路建议参数")
            headings = _headings(sliced)
            texts = [paragraph.text for paragraph in sliced.paragraphs]
            table_count = len(sliced.tables)

        # 起点节含全部子节、中间章整章带上、终点节到文档尾（含表格）
        self.assertEqual(
            headings,
            [
                (1, "二、项目运输方案"),
                (2, "2.1 大件运输"),
                (2, "2.2 车辆配置"),
                (1, "三、临时设施布置"),
                (1, "四、场内道路建议参数"),
                (2, "4.1 路基宽度"),
            ],
        )
        # 起点之前的整章不能带进来
        self.assertNotIn("一、数字化运输管理", texts)
        self.assertNotIn("1.1 平台简介", texts)
        self.assertEqual(table_count, 1)

    def test_single_anchor_stops_at_next_same_or_higher_heading(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "物流解决方案.docx"
            _write_range_source(source)

            # 单标题 = 起点等于终点，只取该节
            sliced = filler.slice_heading_range(source, "项目运输方案", "项目运输方案")
            headings = _headings(sliced)

        self.assertEqual(
            headings,
            [(1, "二、项目运输方案"), (2, "2.1 大件运输"), (2, "2.2 车辆配置")],
        )

    def test_exact_match_wins_over_substring(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "风资源评估报告.docx"
            _write_substring_trap_source(source)

            sliced = filler.slice_heading_range(source, "发电量结果", "发电量结果")
            headings = _headings(sliced)

        # H2「方案及发电量结果」的子串也命中，直接用子串会插错整个上级章节
        self.assertEqual(headings, [(3, "发电量结果")])

    def test_substring_fallback_applies_only_when_exact_misses(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "风资源评估报告.docx"
            _write_substring_trap_source(source)

            sliced = filler.slice_heading_range(source, "方案及发电量", "方案及发电量")
            headings = _headings(sliced)

        self.assertEqual(
            headings,
            [(2, "方案及发电量结果"), (3, "机位方案"), (3, "发电量结果")],
        )

    def test_numbering_prefix_is_ignored_when_matching_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "物流解决方案.docx"
            _write_range_source(source)

            # 素材标题带「二、」「2.1 」编号，占位符只写概念名
            sliced = filler.slice_heading_range(source, "大件运输", "车辆配置")
            headings = _headings(sliced)

        self.assertEqual(headings, [(2, "2.1 大件运输"), (2, "2.2 车辆配置")])

    def test_missing_anchor_raises_with_reason(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "物流解决方案.docx"
            _write_range_source(source)

            with self.assertRaises(ValueError) as caught:
                filler.slice_heading_range(source, "不存在的章节", "场内道路建议参数")

        self.assertIn("找不到", str(caught.exception))

    def test_reversed_range_raises(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "物流解决方案.docx"
            _write_range_source(source)

            with self.assertRaises(ValueError) as caught:
                filler.slice_heading_range(source, "场内道路建议参数", "项目运输方案")

        self.assertIn("之前", str(caught.exception))


class HeadingRangeEmbedRunTests(unittest.TestCase):
    """区间截取跑通整条 fill_docx 链路，重点盯 Heading 样式有没有活下来。"""

    def _run(self, tmp: Path, heading_range: dict | None, *, anchor: str = "项目运输方案") -> dict:
        from docx import Document

        blank = tmp / "待填写-总体方案.docx"
        document = Document()
        document.add_paragraph("一、总体方案")
        document.add_paragraph("本项目安全等级为[安全等级，待填写]。")
        document.add_paragraph("[物流解决方案，待插入]")
        document.save(str(blank))

        source = tmp / "物流解决方案.docx"
        _write_range_source(source)

        entry = {
            "placeholder": "物流解决方案",
            "materialId": "RAW-0007",
            "name": "物流解决方案.docx",
            "materialTier": "project",
            "status": "ready",
            "docxPath": str(source),
        }
        if heading_range:
            entry["headingRange"] = heading_range
        manifest = {
            "schemaVersion": "bid-tech-word-placeholder-fill-v1",
            "title": "总体方案",
            "blankSource": {"docxPath": str(blank), "title": "待填写-总体方案.docx"},
            "outputFile": str(tmp / "out.docx"),
            # 清单第 2/3 列（待填写文件 / 原占位符位置）是 spec_index 的启用条件，缺了整份直接失败
            "projectFactTable": {
                "status": "confirmed",
                "fields": [
                    {
                        "label": "安全等级",
                        "value": "一级",
                        "placeholder": "[安全等级，待填写]",
                        "targetFile": "待填写-总体方案.docx",
                    }
                ],
            },
            "embedSources": [entry],
        }
        manifest_path = tmp / "word_fill_input.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        return filler.run_from_manifest(manifest_path)

    def test_range_embed_preserves_heading_styles_in_output(self) -> None:
        from docx import Document

        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            result = self._run(tmp, {"start": "项目运输方案", "end": "场内道路建议参数"})
            output = Document(str(tmp / "out.docx"))
            headings = _headings(output)

        decision = [item for item in result["filledFieldDetails"] if item["action"] == "embed"][0]
        self.assertEqual(decision["evidence"]["headingRange"], "项目运输方案~场内道路建议参数")
        self.assertIn("已嵌入素材片段", decision["value"])
        # 样式一旦降级成 Normal，assembler 的 strip_prefix / inject_prefix_to_headings
        # 会整段跳过（两者开头都是 `if lvl is None: continue`），最终稿里永远不会被编号
        self.assertEqual(
            headings,
            [
                (1, "二、项目运输方案"),
                (2, "2.1 大件运输"),
                (2, "2.2 车辆配置"),
                (1, "三、临时设施布置"),
                (1, "四、场内道路建议参数"),
                (2, "4.1 路基宽度"),
            ],
        )

    def test_whole_file_embed_is_unchanged_without_heading_range(self) -> None:
        from docx import Document

        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            result = self._run(tmp, None)
            output = Document(str(tmp / "out.docx"))
            headings = _headings(output)

        decision = [item for item in result["filledFieldDetails"] if item["action"] == "embed"][0]
        self.assertIn("已嵌入整份素材", decision["value"])
        self.assertEqual(decision["evidence"]["headingRange"], "")
        # 整份插入必须仍然是整份：第一章不能被截掉
        self.assertEqual(headings[0], (1, "一、数字化运输管理"))
        self.assertEqual(len(headings), 8)

    def test_bad_anchor_degrades_to_manual_with_reason(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            result = self._run(tmp, {"start": "不存在的章节", "end": "不存在的章节"})

        detail = [item for item in result["fillReport"]["embedDetails"] if item["label"] == "物流解决方案"][0]
        # 素材本身是 ready 的，照抄 status 会让报告看不出真实原因
        self.assertEqual(detail["action"], "manual_embed")
        self.assertEqual(detail["status"], "range_failed")
        self.assertIn("找不到", detail["message"])


class EmbedRunTests(unittest.TestCase):
    def _run(self, tmp: Path) -> dict:
        blank = tmp / "待填写-总体方案.docx"
        embed_source = tmp / "设备清单.docx"
        _write_blank_source(blank)
        _write_embed_source(embed_source, "设备清单明细")
        manifest = {
            "schemaVersion": "bid-tech-word-placeholder-fill-v1",
            "title": "总体方案",
            "blankSource": {"docxPath": str(blank), "title": "待填写-总体方案.docx"},
            "outputFile": str(tmp / "out.docx"),
            "projectFactTable": {
                "status": "confirmed",
                "fields": [
                    {
                        "label": "安全等级",
                        "value": "一级",
                        "placeholder": "[安全等级，待填写]",
                        "targetFile": "待填写-总体方案.docx",
                    }
                ],
            },
            "embedSources": [
                {
                    "placeholder": "设备清单",
                    "materialId": "RAW-0001",
                    "name": "设备清单.docx",
                    "materialTier": "project",
                    "status": "ready",
                    "docxPath": str(embed_source),
                },
                {
                    "placeholder": "价格表",
                    "materialId": "RAW-0002",
                    "name": "价格表.xlsx",
                    "materialTier": "project",
                    "status": "convert_failed",
                    "statusMessage": "素材「价格表.xlsx」转 Word 失败：openpyxl 打不开该文件。",
                },
            ],
        }
        manifest_path = tmp / "word_fill_input.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        return filler.run_from_manifest(manifest_path)

    def test_embed_counts_are_separate_from_filled_values(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            report = self._run(Path(raw))["fillReport"]

        # 整份嵌入不混进「填了几个值」，否则审核界面看不出哪些是整份文档
        self.assertEqual(report["filledPlaceholderCount"], 1)
        self.assertEqual(report["embeddedCount"], 1)
        self.assertEqual(report["manualEmbedCount"], 3)
        self.assertEqual(report["unfilledPlaceholderCount"], 3)
        self.assertEqual(report["manualEmbedMarker"], "[待人工插入：素材名]")

    def test_ready_source_is_inserted_and_placeholder_paragraph_removed(self) -> None:
        from docx import Document

        with tempfile.TemporaryDirectory() as raw:
            result = self._run(Path(raw))
            document = Document(result["outputFile"])
            texts = [paragraph.text for paragraph in document.paragraphs]
            tables = len(document.tables)

        self.assertIn("设备清单明细", texts)
        self.assertNotIn("[设备清单，待插入]", texts)
        self.assertIn("本项目安全等级为一级。", texts)
        # 空白模板自带 1 张表 + 素材带进来的 1 张
        self.assertEqual(tables, 2)

    def test_unsupported_ambiguous_and_mixed_placeholders_fall_back_to_manual(self) -> None:
        from docx import Document

        with tempfile.TemporaryDirectory() as raw:
            result = self._run(Path(raw))
            document = Document(result["outputFile"])
            texts = [paragraph.text for paragraph in document.paragraphs]
            cell_text = document.tables[-1].rows[0].cells[1].text

        self.assertIn("[待人工插入：价格表]", texts)
        self.assertIn("详见[待人工插入：附件材料]后附。", texts)
        self.assertEqual(cell_text, "[待人工插入：表内素材]")

    def test_manual_embed_reason_is_reported_not_swallowed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            report = self._run(Path(raw))["fillReport"]

        by_label = {item["label"]: item for item in report["embedDetails"]}
        self.assertEqual(by_label["设备清单"]["action"], "embed")
        self.assertIn("转 Word 失败", by_label["价格表"]["message"])
        self.assertEqual(by_label["附件材料"]["status"], "not_standalone")
        self.assertEqual(by_label["表内素材"]["status"], "not_standalone")

    def test_missing_embed_source_is_marked_manual_with_reason(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            blank = tmp / "待填写-总体方案.docx"
            _write_blank_source(blank)
            manifest_path = tmp / "word_fill_input.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "bid-tech-word-placeholder-fill-v1",
                        "blankSource": {"docxPath": str(blank), "title": "待填写-总体方案.docx"},
                        "outputFile": str(tmp / "out.docx"),
                        "projectFactTable": {
                            "status": "confirmed",
                            "fields": [
                                {
                                    "label": "安全等级",
                                    "value": "一级",
                                    "placeholder": "[安全等级，待填写]",
                                    "targetFile": "待填写-总体方案.docx",
                                }
                            ],
                        },
                        "embedSources": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            report = filler.run_from_manifest(manifest_path)["fillReport"]

        self.assertEqual(report["embeddedCount"], 0)
        self.assertEqual(report["manualEmbedCount"], 4)
        by_label = {item["label"]: item for item in report["embedDetails"]}
        self.assertEqual(by_label["设备清单"]["status"], "not_found")


if __name__ == "__main__":
    unittest.main()
