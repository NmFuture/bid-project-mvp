"""待插入素材备料单测：扫描占位符 → 按素材范围检索 → 写入 manifest.embedSources。

素材检索要联网查库，按「skill 只依据 manifest 工作」的既有约定放在后端；filler 只依据
这里给出的本地路径与 status 决定嵌入还是标黄。
fixture 为脱敏合成数据（通用领域词面，无真实项目数据）。
"""
from __future__ import annotations

import inspect
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

from app.services import technical_gap_ai_fill as ai_fill

EXCEL_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _write_docx(path: Path, paragraphs: list[str], cell_text: str = "") -> None:
    from docx import Document

    document = Document()
    for text in paragraphs:
        document.add_paragraph(text)
    if cell_text:
        table = document.add_table(rows=1, cols=1)
        table.rows[0].cells[0].text = cell_text
    document.save(str(path))


def _write_xlsx(path: Path, rows: list[list[Any]]) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    workbook.save(str(path))


def _write_pdf(path: Path, pages: int) -> None:
    import fitz

    document = fitz.open()
    try:
        for index in range(pages):
            document.new_page().insert_text((72, 72), f"page {index + 1}")
        document.save(str(path))
    finally:
        document.close()


def _payload_stub(payload: dict[str, Any]) -> Callable[[object], dict[str, Any]]:
    """替掉 _run_async：真实实现会 await 掉协程，mock 不 await，这里显式关闭免得留警告。"""

    def _stub(awaitable: object) -> dict[str, Any]:
        if hasattr(awaitable, "close"):
            awaitable.close()
        return payload

    return _stub


def _download_stub(source: Path) -> Callable[[str, str, Path], Path]:
    """替掉 minio_client.download_file：把本地 fixture 拷到目标路径，冒充素材原件。"""

    def _download(_bucket: str, _key: str, target_path: Path) -> Path:
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        return target

    return _download


class ScanEmbedPlaceholdersTests(unittest.TestCase):
    def test_scans_paragraph_embed_placeholders_and_dedupes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "待填写-方案.docx"
            _write_docx(
                path,
                [
                    "本项目安全等级为[安全等级，待填写]。",
                    "[设备清单，待插入]",
                    "【设备清单, 待插入】",
                    "详见[附件材料，待插入]后附。",
                ],
                cell_text="[表内素材，待插入]",
            )

            labels = ai_fill._scan_embed_placeholders(path)

        # 待填写不进来；同名占位符归一化后去重；表格单元格不备料（filler 一律标黄）
        self.assertEqual(labels, ["设备清单", "附件材料"])

    def test_document_without_embed_placeholders_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "待填写-方案.docx"
            _write_docx(path, ["本项目安全等级为[安全等级，待填写]。"])

            self.assertEqual(ai_fill._scan_embed_placeholders(path), [])


class MaterialSpecificityTests(unittest.TestCase):
    def test_more_specific_tier_wins(self) -> None:
        picked, ambiguous = ai_fill._pick_most_specific_material(
            [
                {"id": "RAW-1", "name": "设备清单.docx", "materialTier": "standard"},
                {"id": "RAW-2", "name": "设备清单.docx", "materialTier": "project"},
                {"id": "RAW-3", "name": "设备清单.docx", "materialTier": "customer"},
            ]
        )

        self.assertEqual(picked["id"], "RAW-2")
        self.assertFalse(ambiguous)

    def test_same_tier_collision_is_ambiguous(self) -> None:
        _picked, ambiguous = ai_fill._pick_most_specific_material(
            [
                {"id": "RAW-1", "name": "设备清单.docx", "materialTier": "project"},
                {"id": "RAW-2", "name": "设备清单.docx", "materialTier": "project"},
            ]
        )

        self.assertTrue(ambiguous)


class EmbedSourcesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = {"id": "PRJ-0001", "name": "示例项目", "bidType": "技术标"}

    def _run(self, tmp: Path, materials: list[dict], paragraphs: list[str]) -> list[dict]:
        blank = tmp / "待填写-方案.docx"
        _write_docx(blank, paragraphs)
        with (
            patch.object(ai_fill, "build_project_material_scope", return_value={"readableScopes": []}),
            patch.object(ai_fill, "project_turbine_model", return_value={}),
            patch.object(ai_fill, "_allowed_technical_material_index", return_value=materials),
        ):
            return ai_fill._embed_sources_for_fill(self.project, blank, tmp)

    def test_missing_material_is_reported_not_silently_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            sources = self._run(Path(raw), [], ["[设备清单，待插入]"])

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["status"], "not_found")
        self.assertIn("设备清单", sources[0]["statusMessage"])

    def test_same_tier_collision_is_marked_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            sources = self._run(
                Path(raw),
                [
                    {"id": "RAW-1", "name": "设备清单.docx", "materialTier": "project"},
                    {"id": "RAW-2", "name": "设备清单.docx", "materialTier": "project"},
                ],
                ["[设备清单，待插入]"],
            )

        self.assertEqual(sources[0]["status"], "ambiguous")
        self.assertEqual(sources[0]["candidateCount"], 2)

    def test_download_failure_degrades_to_manual_not_exception(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            blank = Path(raw) / "待填写-方案.docx"
            _write_docx(blank, ["[设备清单，待插入]"])
            with (
                patch.object(ai_fill, "build_project_material_scope", return_value={"readableScopes": []}),
                patch.object(ai_fill, "project_turbine_model", return_value={}),
                patch.object(
                    ai_fill,
                    "_allowed_technical_material_index",
                    return_value=[{"id": "RAW-1", "name": "设备清单.docx", "materialTier": "project"}],
                ),
                patch.object(ai_fill, "_run_async", side_effect=RuntimeError("minio down")),
            ):
                sources = ai_fill._embed_sources_for_fill(self.project, blank, Path(raw))

        # 一份素材取不到不能中断整份文件的填写
        self.assertEqual(sources[0]["status"], "download_failed")
        self.assertIn("minio down", sources[0]["statusMessage"])

    def test_ready_source_carries_local_path_for_the_skill(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            blank = tmp / "待填写-方案.docx"
            _write_docx(blank, ["[设备清单，待插入]"])
            payload = {"bucket": "materials", "key": "cleaned/设备清单.docx", "fileName": "设备清单.docx"}

            def _run_async_stub(awaitable: object) -> tuple[dict, str]:
                # 真实 _run_async 会 await 掉协程；mock 不 await，这里显式关闭免得留下未等待警告
                if hasattr(awaitable, "close"):
                    awaitable.close()
                return payload, "cleaned"

            with (
                patch.object(ai_fill, "build_project_material_scope", return_value={"readableScopes": []}),
                patch.object(ai_fill, "project_turbine_model", return_value={}),
                patch.object(
                    ai_fill,
                    "_allowed_technical_material_index",
                    return_value=[{"id": "RAW-1", "name": "设备清单.docx", "materialTier": "project"}],
                ),
                patch.object(ai_fill, "_run_async", side_effect=_run_async_stub),
                patch.object(ai_fill.minio_client, "download_file") as download,
            ):
                sources = ai_fill._embed_sources_for_fill(self.project, blank, tmp)

        self.assertEqual(sources[0]["status"], "ready")
        self.assertEqual(sources[0]["materialTier"], "project")
        self.assertTrue(sources[0]["docxPath"].endswith(".docx"))
        self.assertIn("embed_sources", sources[0]["docxPath"])
        download.assert_called_once()

    def test_no_embed_placeholder_skips_material_lookup_entirely(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            blank = tmp / "待填写-方案.docx"
            _write_docx(blank, ["本项目安全等级为[安全等级，待填写]。"])
            with patch.object(ai_fill, "_allowed_technical_material_index") as lookup:
                sources = ai_fill._embed_sources_for_fill(self.project, blank, tmp)

        self.assertEqual(sources, [])
        lookup.assert_not_called()


class EmbedLabelRangeTests(unittest.TestCase):
    """`文件-起点-终点` 拆分：文件名边界由素材索引决定，不靠语法猜。"""

    def setUp(self) -> None:
        self.project = {"id": "PRJ-0001", "name": "示例项目", "bidType": "技术标"}

    def _by_key(self, names: list[str]) -> dict[str, list[dict]]:
        index: dict[str, list[dict]] = {}
        for name in names:
            index.setdefault(ai_fill._embed_norm(Path(name).stem), []).append({"id": name, "name": name})
        return index

    def test_two_anchors_become_closed_range(self) -> None:
        matches, anchors = ai_fill._embed_split_label(
            "物流解决方案-项目运输方案-场内道路建议参数", self._by_key(["物流解决方案.docx"])
        )

        self.assertEqual(matches[0]["name"], "物流解决方案.docx")
        self.assertEqual(anchors, ["项目运输方案", "场内道路建议参数"])

    def test_single_anchor_is_start_equals_end(self) -> None:
        _matches, anchors = ai_fill._embed_split_label(
            "风资源评估报告-发电量结果", self._by_key(["风资源评估报告.docx"])
        )

        self.assertEqual(anchors, ["发电量结果"])

    def test_reserved_whole_file_token_means_no_range(self) -> None:
        matches, anchors = ai_fill._embed_split_label(
            "基础弯矩表-完整插入", self._by_key(["基础弯矩表.xlsx"])
        )

        self.assertTrue(matches)
        self.assertEqual(anchors, [])

    def test_hyphenated_material_name_is_not_cut_apart(self) -> None:
        # 型式认证素材名自带四个连字符，固定按第一个 `-` 拆会把文件名切碎
        name = "EW5.0-202-FD24C3018（南高齿）齿轮箱型式认证A-20240829.pdf"
        matches, anchors = ai_fill._embed_split_label(f"{Path(name).stem}-完整插入", self._by_key([name]))

        self.assertEqual(matches[0]["name"], name)
        self.assertEqual(anchors, [])

    def test_unmatched_concept_name_reports_not_found_not_format_error(self) -> None:
        # 清单写概念名、素材是带机型编号的全名：根因是素材名对不上，不是占位符格式错。
        # 报「格式错误」会把人引去改清单，但清单没错。
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            blank = tmp / "待填写-方案.docx"
            _write_docx(blank, ["[齿轮箱型式认证-完整插入，待插入]"])
            with (
                patch.object(ai_fill, "build_project_material_scope", return_value={"readableScopes": []}),
                patch.object(ai_fill, "project_turbine_model", return_value={}),
                patch.object(
                    ai_fill,
                    "_allowed_technical_material_index",
                    return_value=[{"id": "RAW-1", "name": "EW5.0-202-FD24C3018齿轮箱型式认证A.pdf", "materialTier": "project"}],
                ),
            ):
                sources = ai_fill._embed_sources_for_fill(self.project, blank, tmp)

        self.assertEqual(sources[0]["status"], "not_found")

    def test_extra_anchors_after_matched_material_are_a_format_error(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            blank = tmp / "待填写-方案.docx"
            _write_docx(blank, ["[物流解决方案-甲-乙-丙，待插入]"])
            with (
                patch.object(ai_fill, "build_project_material_scope", return_value={"readableScopes": []}),
                patch.object(ai_fill, "project_turbine_model", return_value={}),
                patch.object(
                    ai_fill,
                    "_allowed_technical_material_index",
                    return_value=[{"id": "RAW-3", "name": "物流解决方案.docx", "materialTier": "project"}],
                ),
            ):
                sources = ai_fill._embed_sources_for_fill(self.project, blank, tmp)

        # 前缀命中了素材、后面确实剩三段，这才是真正的格式错
        self.assertEqual(sources[0]["status"], "invalid_range")
        self.assertIn("3 个标题锚点", sources[0]["statusMessage"])

    def test_heading_range_is_handed_to_the_filler(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            blank = tmp / "待填写-方案.docx"
            _write_docx(blank, ["[物流解决方案-项目运输方案-场内道路建议参数，待插入]"])
            payload = {"bucket": "materials", "key": "cleaned/物流解决方案.docx", "fileName": "物流解决方案.docx"}

            def _run_async_stub(awaitable: object) -> tuple[dict, str]:
                if hasattr(awaitable, "close"):
                    awaitable.close()
                return payload, "cleaned"

            with (
                patch.object(ai_fill, "build_project_material_scope", return_value={"readableScopes": []}),
                patch.object(ai_fill, "project_turbine_model", return_value={}),
                patch.object(
                    ai_fill,
                    "_allowed_technical_material_index",
                    return_value=[{"id": "RAW-3", "name": "物流解决方案.docx", "materialTier": "project"}],
                ),
                patch.object(ai_fill, "_run_async", side_effect=_run_async_stub),
                patch.object(ai_fill.minio_client, "download_file"),
            ):
                sources = ai_fill._embed_sources_for_fill(self.project, blank, tmp)

        self.assertEqual(sources[0]["status"], "ready")
        self.assertEqual(sources[0]["headingRange"], {"start": "项目运输方案", "end": "场内道路建议参数"})


class EmbedConversionTests(unittest.TestCase):
    """非 docx 素材按需转 Word。真跑转换脚本，不 mock 转换本身——嵌进投标材料的是产物内容。"""

    def setUp(self) -> None:
        self.project = {"id": "PRJ-0001", "name": "示例项目", "bidType": "技术标"}

    def _run(
        self,
        work_dir: Path,
        source: Path,
        mime_type: str,
        *,
        cache_dir: Path | None = None,
        material_id: str = "RAW-7",
    ) -> list[dict]:
        work_dir.mkdir(parents=True, exist_ok=True)
        blank = work_dir / "待填写-方案.docx"
        _write_docx(blank, [f"[{source.stem}，待插入]"])
        material = {"id": material_id, "name": source.name, "materialTier": "project"}
        payload = {
            "bucket": "materials",
            "key": f"raw/{source.name}",
            "fileName": source.name,
            "mimeType": mime_type,
        }
        with (
            patch.object(ai_fill, "build_project_material_scope", return_value={"readableScopes": []}),
            patch.object(ai_fill, "project_turbine_model", return_value={}),
            patch.object(ai_fill, "_allowed_technical_material_index", return_value=[material]),
            patch.object(ai_fill, "_run_async", side_effect=_payload_stub(payload)),
            patch.object(ai_fill.minio_client, "download_file", side_effect=_download_stub(source)),
        ):
            return ai_fill._embed_sources_for_fill(self.project, blank, work_dir, cache_dir=cache_dir)

    def test_excel_material_is_converted_and_ready_to_embed(self) -> None:
        from docx import Document

        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            excel = tmp / "基础弯矩表.xlsx"
            _write_xlsx(excel, [["工况", "弯矩"], ["额定", -149696.921875], ["极限", -211003.5]])

            sources = self._run(tmp / "run", excel, EXCEL_MIME)
            docx_path = Path(sources[0]["docxPath"])
            tables = Document(str(docx_path)).tables

        self.assertEqual(sources[0]["status"], "ready")
        self.assertEqual(sources[0]["sourceKind"], "excel")
        # 表头 + 2 行数据全部落进 Word 表格，不是空壳；产物名不带 materialId，
        # 否则 PDF 分支会把 id 写成 Word 标题
        self.assertEqual(len(tables), 1)
        self.assertEqual(len(tables[0].rows), 3)
        self.assertEqual([cell.text for cell in tables[0].rows[0].cells], ["工况", "弯矩"])
        self.assertEqual(docx_path.name, "基础弯矩表.docx")

    def test_pdf_material_is_converted_page_by_page(self) -> None:
        from docx import Document

        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            pdf = tmp / "载荷安全性评估报告.pdf"
            _write_pdf(pdf, pages=3)

            sources = self._run(tmp / "run", pdf, "application/pdf")
            docx_path = Path(sources[0]["docxPath"])
            document = Document(str(docx_path))
            leftover = list(docx_path.parent.glob(".convert-*"))

        self.assertEqual(sources[0]["status"], "ready")
        self.assertEqual(sources[0]["sourceKind"], "pdf")
        # 每页一张图：盖章件要的是图片版，OCR 成文字反而丢公章
        self.assertEqual(len(document.inline_shapes), 3)
        # 中间页图随临时目录清掉，不在缓存里长期占地
        self.assertEqual(leftover, [])

    def test_same_material_is_converted_only_once_across_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            shared_cache = tmp / "_embed_converted_cache"
            excel = tmp / "变桨轴承场址校核报告.xlsx"
            _write_xlsx(excel, [["项", "值"], ["A", 1]])

            first = self._run(tmp / "gap-X2", excel, EXCEL_MIME, cache_dir=shared_cache)
            # 第二个专题引用同一素材：命中共享缓存就不该再碰转换脚本
            with patch.object(
                ai_fill, "_format_cleaner_script", side_effect=AssertionError("同一素材不应重复转换")
            ):
                second = self._run(tmp / "gap-X3", excel, EXCEL_MIME, cache_dir=shared_cache)

        self.assertEqual(second[0]["status"], "ready")
        self.assertEqual(second[0]["docxPath"], first[0]["docxPath"])

    def test_conversion_failure_is_reported_not_silently_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            excel = tmp / "价格表.xlsx"
            _write_xlsx(excel, [["项", "值"]])

            with patch.object(ai_fill, "_format_cleaner_script", side_effect=RuntimeError("openpyxl 打不开")):
                sources = self._run(tmp / "run", excel, EXCEL_MIME)

        # 一份素材转不了不能中断整份文件的填写，也不能悄悄少嵌一份
        self.assertEqual(sources[0]["status"], "convert_failed")
        self.assertIn("openpyxl 打不开", sources[0]["statusMessage"])
        self.assertNotIn("docxPath", sources[0])

    def test_pdf_render_zoom_stays_at_one_and_a_half(self) -> None:
        parameters = inspect.signature(
            ai_fill._format_cleaner_script("pdf_to_word.py").split_pdf_to_images
        ).parameters
        # 1.5x 约 108 dpi：投标看图纸和公章足够，比 2x 省约 30% 体积
        self.assertEqual(parameters["zoom"].default, 1.5)

    def test_convert_kind_falls_back_to_mime_when_suffix_missing(self) -> None:
        # 型式认证扫描件常以无扩展名上传，只能靠 mime 认
        self.assertEqual(ai_fill._embed_convert_kind("型式认证证书", "application/pdf"), "pdf")
        self.assertEqual(ai_fill._embed_convert_kind("参数清单", "application/vnd.ms-excel"), "excel")
        self.assertEqual(ai_fill._embed_convert_kind("说明", "text/plain"), "")


if __name__ == "__main__":
    unittest.main()
