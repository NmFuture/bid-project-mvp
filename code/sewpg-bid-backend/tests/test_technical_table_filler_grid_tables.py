"""网格型（曲线表）与清单行型（全空记录行）附表的目标抽取与填写单测。

覆盖：
1. 网格型：合并表头（机型行 + 列表头行）、行键预填（风速区间）、功率数据列
   逐格出字段、图片占位列标记 imagePlaceholder、行键全空时退化为「第N行」。
2. 清单行型：只有表头 + 全空记录行（备品备件清单同构），序号/备注列不进目标。
3. 端到端：prepare 简报带 cellKind；apply 按计划逐格写回、单位换算
   （MW→kW 只填数值）、图片占位列与未覆盖格统一降级 [待人工补充]。
4. 回归：参数表与已预填品牌表行为不变（0 字段路径不受影响）。
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from docx import Document

_SRC = (
    Path(__file__).resolve().parents[1]
    / "opencode"
    / "skills"
    / "bid-tech-table-filler"
    / "scripts"
    / "run_from_manifest.py"
)
_SPEC = importlib.util.spec_from_file_location("tech_table_filler_grid_under_test", _SRC)
filler = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules["tech_table_filler_grid_under_test"] = filler
_SPEC.loader.exec_module(filler)


def _build_curve_docx(path: Path, heading: str, data_rows: list[list[str]]) -> Path:
    """D.1 同构曲线表：合并机型标题行 + 列表头行（对比图两列合并）+ 数据行。"""
    doc = Document()
    doc.add_paragraph(heading)
    table = doc.add_table(rows=2 + len(data_rows), cols=6)
    table.cell(0, 0).merge(table.cell(0, 5))
    table.cell(0, 0).text = "机型：投标机型1"
    headers = ["风速区间（m/s）", "区间平均风速（m/s）", "标准空气密度下功率（kW）", "风电场空气密度下功率（kW）", "功率曲线对比图", ""]
    for ci, value in enumerate(headers):
        table.rows[1].cells[ci].text = value
    for ri, row in enumerate(data_rows, start=2):
        for ci, value in enumerate(row):
            table.rows[ri].cells[ci].text = value
        table.cell(ri, 4).merge(table.cell(ri, 5))
    doc.save(str(path))
    return path


def _build_blank_list_docx(path: Path, heading: str, headers: list[str], row_count: int) -> Path:
    """B.2 同构清单行型表：表头 + 全空记录行。"""
    doc = Document()
    doc.add_paragraph(heading)
    table = doc.add_table(rows=1 + row_count, cols=len(headers))
    for ci, value in enumerate(headers):
        table.rows[0].cells[ci].text = value
    doc.save(str(path))
    return path


def _build_text_docx(path: Path, paragraphs: list[str]) -> Path:
    doc = Document()
    for paragraph in paragraphs:
        doc.add_paragraph(paragraph)
    doc.save(str(path))
    return path


def _build_d5_docx(path: Path, data_row_count: int = 4) -> Path:
    """D.5 同构曲线表变体：风速列全空、图片占位列**表头为空**、占位文字只在数据行；
    尾部带签名/注记行；文件内第二表属于附表D.6（测试表归属剔除）。"""
    doc = Document()
    doc.add_paragraph("附表D.5 保证推力系数曲线（间隔0.5m/s）")
    table = doc.add_table(rows=2 + data_row_count + 1, cols=4)
    table.cell(0, 0).merge(table.cell(0, 3))
    table.cell(0, 0).text = "机型：投标机型1"
    table.rows[1].cells[0].text = "风速m/s"
    table.rows[1].cells[1].text = "风电场空气密度推力系数"
    table.cell(1, 1).merge(table.cell(1, 2))
    # 第 4 列表头为空
    for ri in range(2, 2 + data_row_count):
        table.cell(ri, 1).merge(table.cell(ri, 2))
    # 真实 D.5 的图片占位列纵向合并成一个通栏大格，占位文字只有一份
    table.cell(2, 3).merge(table.cell(2 + data_row_count - 1, 3)).text = "推力系数曲线"
    footer = 2 + data_row_count
    table.cell(footer, 0).merge(table.cell(footer, 1))
    table.cell(footer, 0).text = "投标人授权代表签名"
    table.rows[footer].cells[3].text = "风电场空气密度为kg/m3"
    # 第二表：附表D.6 的内容，不应混进 D.5 的目标
    doc.add_paragraph("附表D.6 保证功率曲线（动态）下功率桨距角曲线")
    table2 = doc.add_table(rows=4, cols=4)
    table2.cell(0, 0).merge(table2.cell(0, 3))
    table2.cell(0, 0).text = "机型：投标机型1"
    for ci, value in enumerate(["风速m/s", "功率kW", "桨距角°", "功率-桨距角曲线图"]):
        table2.rows[1].cells[ci].text = value
    for ri, speed in ((2, "1"), (3, "1.5")):
        table2.rows[ri].cells[0].text = speed
        table2.rows[ri].cells[3].text = "功率-桨距角曲线"
    doc.save(str(path))
    return path


# 5 个风速区间，功率两列空、图片列占位（行键已预填）
_CURVE_ROWS = [
    ["0.00-0.25", "0", "", "", "功率曲线对比图", ""],
    ["0.25-0.75", "0.5", "", "", "功率曲线对比图", ""],
    ["0.75-1.25", "1.0", "", "", "功率曲线对比图", ""],
    ["1.25-1.75", "1.5", "", "", "功率曲线对比图", ""],
    ["1.75-2.25", "2.0", "", "", "功率曲线对比图", ""],
]

# D.2 同构：风速列也全空，行键退化为行号
_CURVE_EMPTY_KEY_ROWS = [["", "", "", "", "推力系数曲线", ""] for _ in range(4)]

_B2_HEADERS = ["序号", "名称", "型号和规格", "单位", "数量", "备注", "更换周期", "国内替代产品型号"]

_MATERIAL_PARAGRAPHS = [
    "功率曲线数据",
    "0.00-0.25 区间标准空气密度下功率 0 kW，风电场空气密度下功率 0 kW。",
    "0.25-0.75 区间标准空气密度下功率 0.125 MW。",
    "备品备件：齿轮箱滤芯，型号 GL-LX-01。",
]


class GridTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.curve = _build_curve_docx(self.base / "curve.docx", "附表D.1 标准及风电场空气密度功率曲线", _CURVE_ROWS)
        self.blank_list = _build_blank_list_docx(self.base / "b2.docx", "附表B.2 质量保证期备品备件、消耗品清单", _B2_HEADERS, 3)
        self.material = _build_text_docx(self.base / "material.docx", _MATERIAL_PARAGRAPHS)
        self.output = self.base / "out" / "filled.docx"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_manifest(self, *, blank: Path, title: str) -> Path:
        manifest = {
            "blankSource": {"docxPath": str(blank), "title": title, "id": "APPX-TEST"},
            "outputFile": str(self.output),
            "referenceMaterials": [{"id": "RAW-1", "name": "素材.docx", "path": str(self.material)}],
        }
        path = self.base / "manifest.json"
        path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        return path

    def _write_plan(self, fills: list[dict]) -> None:
        plan = {"schemaVersion": "bid-tech-table-fill-plan-v1", "fills": fills}
        (self.base / "fill_plan.json").write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

    def _fill(self, target_field_id: str, field: str, value: str, excerpt: str, **extra) -> dict:
        fill = {
            "targetFieldId": target_field_id,
            "field": field,
            "action": "fill",
            "value": value,
            "unit": "",
            "confidence": 0.9,
            "evidence": {"sourceRoute": "referenceMaterial", "sourcePath": str(self.material), "excerpt": excerpt},
            "reason": "测试取值",
        }
        fill.update(extra)
        return fill

    def _detect_fields(self, blank: Path, title: str) -> list[dict]:
        spec = filler.detect_appendix_spec(blank.resolve(), {"blankSource": {"title": title, "id": "APPX-TEST"}})
        return filler.extract_target_fields(spec)


class DetectMatrixLayoutTests(GridTestBase):
    def test_curve_table_produces_cell_fields(self) -> None:
        fields = self._detect_fields(self.curve, "附表D.1 标准及风电场空气密度功率曲线")
        matrix = [f for f in fields if f.get("cellKind") == "matrix"]
        images = [f for f in fields if f.get("cellKind") == "image"]
        # 5 行 × 2 个功率列 + 5 行 × 1 个图片占位列（合并单元格只认一次）
        self.assertEqual(len(matrix), 10)
        self.assertEqual(len(images), 5)
        first = matrix[0]
        self.assertEqual(first["field"], "0.00-0.25 标准空气密度下功率（kW）")
        self.assertEqual(first["unit"], "kw")  # 列头内嵌单位成为该格单位口径
        self.assertEqual((first["tableIndex"], first["rowIndex"], first["valueCol"]), (0, 2, 2))
        self.assertEqual(first["listRowLabel"], "0.00-0.25")
        self.assertEqual(first["listColumnLabel"], "标准空气密度下功率（kW）")
        self.assertTrue(images[0]["imagePlaceholder"])
        self.assertEqual(images[0]["valueCol"], 4)
        # 预填列（风速区间/平均风速）不是填写目标
        self.assertFalse(any(f["valueCol"] in {0, 1} for f in fields))

    def test_curve_table_with_empty_keys_falls_back_to_row_number(self) -> None:
        path = _build_curve_docx(self.base / "curve2.docx", "附表D.2 标准及风电场空气密度推力系数曲线", _CURVE_EMPTY_KEY_ROWS)
        fields = self._detect_fields(path, "附表D.2 标准及风电场空气密度推力系数曲线")
        matrix = [f for f in fields if f.get("cellKind") == "matrix"]
        images = [f for f in fields if f.get("cellKind") == "image"]
        # 4 行 × 4 个数据列（风速区间/平均风速 + 两个功率列均空）+ 4 个图片占位格
        self.assertEqual(len(matrix), 16)
        self.assertEqual(len(images), 4)
        self.assertEqual(matrix[0]["listRowLabel"], "第1行")
        self.assertTrue(any(f["listColumnLabel"] == "风速区间（m/s）" for f in matrix))


class DetectBlankListLayoutTests(GridTestBase):
    def test_blank_record_rows_produce_cell_fields(self) -> None:
        fields = self._detect_fields(self.blank_list, "附表B.2 质量保证期备品备件、消耗品清单")
        # 3 行 × 6 列（序号/备注不进目标，单位/数量/更换周期是记录内容）
        self.assertEqual(len(fields), 18)
        self.assertTrue(all(f.get("cellKind") == "blankList" for f in fields))
        row1 = [f for f in fields if f["rowIndex"] == 1]
        self.assertEqual({f["listColumnLabel"] for f in row1}, {"名称", "型号和规格", "单位", "数量", "更换周期", "国内替代产品型号"})
        self.assertTrue(all(f["listRowLabel"] == "第1行" for f in row1))

    def test_prefilled_table_still_zero_fields(self) -> None:
        # 品牌表同构：数据行已整行预填，不是清单行型，保持 0 字段
        rows = [["1", "齿轮箱", "上海电气", "GK-01", "台", "1", "", "5年"] for _ in range(3)]
        doc = Document()
        doc.add_paragraph("附表B.1.2 机型配置品牌表1")
        table = doc.add_table(rows=4, cols=8)
        for ci, value in enumerate(_B2_HEADERS):
            table.rows[0].cells[ci].text = value
        for ri, row in enumerate(rows, start=1):
            for ci, value in enumerate(row):
                table.rows[ri].cells[ci].text = value
        path = self.base / "brand.docx"
        doc.save(str(path))
        fields = self._detect_fields(path, "附表B.1.2 机型配置品牌表1")
        self.assertEqual(fields, [])


class ApplyGridCellTests(GridTestBase):
    def test_prepare_brief_marks_cell_kind(self) -> None:
        manifest_path = self._write_manifest(blank=self.curve, title="附表D.1 标准及风电场空气密度功率曲线")
        payload = filler.run_prepare(manifest_path)
        self.assertEqual(payload["targetFieldCount"], 15)
        brief = json.loads((self.base / "fill_brief.json").read_text(encoding="utf-8"))
        kinds = {f.get("cellKind") for f in brief["targetFields"]}
        self.assertEqual(kinds, {"matrix", "image"})
        image_field = next(f for f in brief["targetFields"] if f["cellKind"] == "image")
        self.assertEqual(image_field["columnLabel"], "功率曲线对比图")

    def test_apply_fills_cells_and_forces_image_manual(self) -> None:
        manifest_path = self._write_manifest(blank=self.curve, title="附表D.1 标准及风电场空气密度功率曲线")
        filler.run_prepare(manifest_path)
        brief = json.loads((self.base / "fill_brief.json").read_text(encoding="utf-8"))
        by_field = {f["field"]: f for f in brief["targetFields"]}
        fills = [
            self._fill(
                by_field["0.00-0.25 标准空气密度下功率（kW）"]["targetFieldId"],
                "0.00-0.25 标准空气密度下功率（kW）",
                "0",
                "标准空气密度下功率 0 kW",
            ),
            # 单位换算：来源 MW → 模板列 kW，只填数值
            self._fill(
                by_field["0.25-0.75 标准空气密度下功率（kW）"]["targetFieldId"],
                "0.25-0.75 标准空气密度下功率（kW）",
                "0.125",
                "标准空气密度下功率 0.125 MW",
                unit="MW",
            ),
            # 图片占位列即使给值也被强制降级
            self._fill(
                by_field["0.00-0.25 功率曲线对比图"]["targetFieldId"],
                "0.00-0.25 功率曲线对比图",
                "曲线图见素材",
                "功率曲线数据",
            ),
        ]
        self._write_plan(fills)
        result = filler.run_apply(manifest_path)
        decisions = {d["targetFieldId"]: d for d in result["mapping"]["decisions"]}

        table = Document(str(self.output)).tables[0]
        self.assertEqual(table.rows[2].cells[2].text.strip(), "0")
        self.assertEqual(table.rows[3].cells[2].text.strip(), "125")
        image_id = by_field["0.00-0.25 功率曲线对比图"]["targetFieldId"]
        self.assertEqual(decisions[image_id]["action"], "manual")
        self.assertIn("图片占位列", decisions[image_id]["reason"])
        self.assertEqual(table.rows[2].cells[4].text.strip(), "[待人工补充：0.00-0.25 功率曲线对比图]")
        # 未覆盖的功率格按待人工处理
        uncovered_id = by_field["0.75-1.25 标准空气密度下功率（kW）"]["targetFieldId"]
        self.assertEqual(decisions[uncovered_id]["action"], "manual")
        self.assertEqual(
            table.rows[4].cells[2].text.strip(),
            "[待人工补充：0.75-1.25 标准空气密度下功率（kW）]",
        )
        # 证据留痕结构与字段-值型一致
        evidence = [e for e in result["evidenceRefs"] if e.get("type") == "selected_fact"]
        self.assertEqual(len(evidence), 2)
        self.assertEqual(result["fillReport"]["fillMode"], "llm-plan")

    def test_apply_blank_list_record_row(self) -> None:
        manifest_path = self._write_manifest(blank=self.blank_list, title="附表B.2 质量保证期备品备件、消耗品清单")
        filler.run_prepare(manifest_path)
        brief = json.loads((self.base / "fill_brief.json").read_text(encoding="utf-8"))
        by_field = {f["field"]: f for f in brief["targetFields"]}
        fills = [
            self._fill(
                by_field["第1行 名称"]["targetFieldId"],
                "第1行 名称",
                "齿轮箱滤芯",
                "齿轮箱滤芯",
            ),
            self._fill(
                by_field["第1行 型号和规格"]["targetFieldId"],
                "第1行 型号和规格",
                "GL-LX-01",
                "GL-LX-01",
            ),
        ]
        self._write_plan(fills)
        result = filler.run_apply(manifest_path)
        table = Document(str(self.output)).tables[0]
        self.assertEqual(table.rows[1].cells[1].text.strip(), "齿轮箱滤芯")
        self.assertEqual(table.rows[1].cells[2].text.strip(), "GL-LX-01")
        # 序号/备注列不是目标，保持模板原样（空）
        self.assertEqual(table.rows[1].cells[0].text.strip(), "")
        self.assertEqual(table.rows[1].cells[5].text.strip(), "")
        # 其余未覆盖格降级待人工
        manual = [d for d in result["mapping"]["decisions"] if d["action"] == "manual"]
        self.assertEqual(len(manual), 16)
        self.assertEqual(table.rows[2].cells[1].text.strip(), "[待人工补充：第2行 名称]")


class DetectD5VariantTests(GridTestBase):
    """D.5 变体：风速列全空 + 图片占位列无表头（占位文字只在数据行重复）。"""

    def test_empty_key_empty_image_header_detected(self) -> None:
        path = _build_d5_docx(self.base / "d5.docx")
        fields = self._detect_fields(path, "附表D.5 保证推力系数曲线（间隔0.5m/s）")
        matrix = [f for f in fields if f.get("cellKind") == "matrix"]
        images = [f for f in fields if f.get("cellKind") == "image"]
        # 4 个数据行 × 2 列（风速 + 推力系数，合并延续列去重）+ 1 个图片占位字段
        self.assertEqual(len(matrix), 8)
        self.assertEqual(len(images), 1)
        self.assertEqual({f["listColumnLabel"] for f in matrix}, {"风速m/s", "风电场空气密度推力系数"})
        self.assertEqual(matrix[0]["listRowLabel"], "第1行")
        # 图片占位列标签取占优占位文字
        self.assertEqual(images[0]["listColumnLabel"], "推力系数曲线")
        self.assertTrue(images[0]["imagePlaceholder"])
        # 表1（附表D.6）不混入
        self.assertFalse(any(f["tableIndex"] == 1 for f in fields))

    def test_d5_apply_image_manual_and_footer_untouched(self) -> None:
        path = _build_d5_docx(self.base / "d5.docx")
        material = _build_text_docx(
            self.base / "d5_material.docx",
            ["推力系数数据：风速 1 m/s 时推力系数 0.85。"],
        )
        self.material = material
        manifest_path = self._write_manifest(blank=path, title="附表D.5 保证推力系数曲线（间隔0.5m/s）")
        filler.run_prepare(manifest_path)
        brief = json.loads((self.base / "fill_brief.json").read_text(encoding="utf-8"))
        by_field = {f["field"]: f for f in brief["targetFields"]}
        fills = [
            self._fill(by_field["第1行 风速m/s"]["targetFieldId"], "第1行 风速m/s", "1", "风速 1 m/s"),
            self._fill(by_field["第1行 风电场空气密度推力系数"]["targetFieldId"], "第1行 风电场空气密度推力系数", "0.85", "推力系数 0.85"),
        ]
        self._write_plan(fills)
        result = filler.run_apply(manifest_path)
        table = Document(str(self.output)).tables[0]
        self.assertEqual(table.rows[2].cells[0].text.strip(), "1")
        self.assertEqual(table.rows[2].cells[1].text.strip(), "0.85")
        # 图片占位列强制降级，占位文字被待人工标记替换
        self.assertEqual(table.rows[2].cells[3].text.strip(), "[待人工补充：第1行 推力系数曲线]")
        decisions = {d["targetFieldId"]: d for d in result["mapping"]["decisions"]}
        image_id = by_field["第1行 推力系数曲线"]["targetFieldId"]
        self.assertEqual(decisions[image_id]["action"], "manual")
        # 签名/注记行不是目标，保持原样
        self.assertEqual(table.rows[6].cells[0].text.strip(), "投标人授权代表签名")
        self.assertEqual(table.rows[6].cells[3].text.strip(), "风电场空气密度为kg/m3")


class ParamTableRegressionTests(GridTestBase):
    def test_param_table_detection_unchanged(self) -> None:
        rows = [
            ["编号", "项目", "主要项目", "技术参数与规格", "计量单位", "备注"],
            ["1", "机型总体参数", "投标机型", "", "", ""],
            ["2", "机型总体参数", "单机容量", "", "MW", ""],
        ]
        doc = Document()
        doc.add_paragraph("附表C.1 机型总体参数与规格")
        table = doc.add_table(rows=len(rows), cols=len(rows[0]))
        for ri, row in enumerate(rows):
            for ci, value in enumerate(row):
                table.rows[ri].cells[ci].text = value
        path = self.base / "param.docx"
        doc.save(str(path))
        fields = self._detect_fields(path, "附表C.1 机型总体参数与规格")
        self.assertEqual([f["field"] for f in fields], ["投标机型", "单机容量"])
        self.assertFalse(any(f.get("cellKind") for f in fields))


if __name__ == "__main__":
    unittest.main()
