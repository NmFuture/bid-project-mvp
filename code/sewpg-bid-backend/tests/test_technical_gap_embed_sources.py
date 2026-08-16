"""待插入素材备料单测：扫描占位符 → 查规则表 → 按素材范围检索 → 写入 manifest.embedSources。

范围由文档定、细节由规则表定：扫 Word 决定本次处理哪些占位符，插哪份素材、插整份还是
插其中一节由规则表「待插入」sheet 说了算，不再拿占位符文字去素材库猜文件名。
素材检索要联网查库，按「skill 只依据 manifest 工作」的既有约定放在后端；filler 只依据
这里给出的本地路径与 status 决定嵌入还是标黄。
fixture 为脱敏合成数据（通用领域词面，无真实项目数据）。
"""
from __future__ import annotations

import inspect
import shutil
import tempfile
import unittest
from contextlib import ExitStack
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


def _rule(
    placeholder: str,
    material: str,
    *,
    target: str = "待填写-方案",
    start: str = "",
    end: str = "",
) -> dict[str, Any]:
    """一条「待插入」规则行，与 import_embed_rules 的产出同构。"""
    return {
        "seq": 1,
        "folder": "标准文件",
        "targetFile": target,
        "placeholder": placeholder,
        "material": material,
        "headingStart": start,
        "headingEnd": end or start,
    }


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

    def _run(
        self,
        tmp: Path,
        materials: list[dict],
        paragraphs: list[str],
        rules: list[dict] | None = None,
        extra_patches: tuple = (),
        **kwargs: Any,
    ) -> list[dict]:
        blank = tmp / "待填写-方案.docx"
        _write_docx(blank, paragraphs)
        if rules is None:
            rules = [_rule("[设备清单，待插入]", "设备清单")]
        with ExitStack() as stack:
            for context in (
                patch.object(ai_fill, "load_embed_rules", return_value=rules),
                patch.object(ai_fill, "build_project_material_scope", return_value={"readableScopes": []}),
                patch.object(ai_fill, "project_turbine_model", return_value={}),
                patch.object(ai_fill, "_allowed_technical_material_index", return_value=materials),
                *extra_patches,
            ):
                stack.enter_context(context)
            return ai_fill._embed_sources_for_fill(self.project, blank, tmp, **kwargs)

    def test_placeholder_without_rule_is_reported_not_guessed(self) -> None:
        """规则表没这一行就明说，不再拿占位符文字去素材库猜文件名。"""
        with tempfile.TemporaryDirectory() as raw:
            sources = self._run(
                Path(raw),
                [{"id": "RAW-1", "name": "设备清单.docx", "materialTier": "project"}],
                ["[设备清单，待插入]"],
                rules=[],
            )

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["status"], "no_rule")
        self.assertIn("设备清单", sources[0]["statusMessage"])

    def test_missing_material_is_reported_not_silently_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            sources = self._run(Path(raw), [], ["[设备清单，待插入]"])

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["status"], "not_found")
        self.assertIn("设备清单", sources[0]["statusMessage"])

    def test_same_tier_collision_is_marked_ambiguous(self) -> None:
        """关键词包含匹配命中同层多份不同素材：分不出来就交人工，不挑一个蒙混过去。"""
        with tempfile.TemporaryDirectory() as raw:
            sources = self._run(
                Path(raw),
                [
                    {"id": "RAW-1", "name": "叶片场址校核报告.pdf", "materialTier": "project"},
                    {"id": "RAW-2", "name": "齿轮箱场址校核报告.pdf", "materialTier": "project"},
                ],
                ["[场址校核报告，待插入]"],
                rules=[_rule("[场址校核报告，待插入]", "场址校核报告")],
            )

        self.assertEqual(sources[0]["status"], "ambiguous")
        self.assertEqual(sources[0]["candidateCount"], 2)

    def test_exact_name_wins_over_containing_names(self) -> None:
        """精确同名的素材在场时不退包含匹配，否则会被更长的名字抢走。"""
        with tempfile.TemporaryDirectory() as raw:
            sources = self._run(
                Path(raw),
                [
                    {"id": "RAW-1", "name": "设备清单.docx", "materialTier": "project"},
                    {"id": "RAW-2", "name": "设备清单附录.docx", "materialTier": "project"},
                ],
                ["[设备清单，待插入]"],
                extra_patches=(patch.object(ai_fill, "_run_async", side_effect=RuntimeError("stop here")),),
            )

        self.assertEqual(sources[0]["name"], "设备清单.docx")

    def test_keyword_falls_back_to_containing_match(self) -> None:
        """规则表是全局一份只能写概念名，素材真名常带项目特定后缀。"""
        with tempfile.TemporaryDirectory() as raw:
            sources = self._run(
                Path(raw),
                [{"id": "RAW-1", "name": "本项目主机供货制造基地_锡盟基地.docx", "materialTier": "project"}],
                ["[本项目主机供货制造基地-完整插入，待插入]"],
                rules=[_rule("[本项目主机供货制造基地-完整插入，待插入]", "本项目主机供货制造基地")],
                extra_patches=(patch.object(ai_fill, "_run_async", side_effect=RuntimeError("stop here")),),
            )

        self.assertEqual(sources[0]["name"], "本项目主机供货制造基地_锡盟基地.docx")

    def test_component_cert_is_held_for_brand_selection(self) -> None:
        """部件认证按部件分目录，取哪份要看本项目投的品牌，不能靠名字匹配定。"""
        with tempfile.TemporaryDirectory() as raw:
            sources = self._run(
                Path(raw),
                [
                    {
                        "id": "RAW-1",
                        "name": "EW10.0-220上置-CGC2024（甲厂）齿轮箱型式认证A.pdf",
                        "materialTier": "standard",
                        "folderPath": "技术标/标准文件/EW10.0-220上置/认证证书/部件认证/齿轮箱",
                    },
                    {
                        "id": "RAW-2",
                        "name": "EW10.0-220上置-CGC2025（乙厂）齿轮箱型式认证A.pdf",
                        "materialTier": "standard",
                        "folderPath": "技术标/标准文件/EW10.0-220上置/认证证书/部件认证/齿轮箱",
                    },
                ],
                ["[齿轮箱型式认证-完整插入，待插入]"],
                rules=[_rule("[齿轮箱型式认证-完整插入，待插入]", "齿轮箱")],
            )

        self.assertEqual(sources[0]["status"], "need_brand")
        self.assertEqual(sources[0]["component"], "齿轮箱")
        self.assertEqual(sources[0]["candidateCount"], 2)

    def test_duplicate_records_of_one_file_are_not_treated_as_a_collision(self) -> None:
        """同一份素材挂在上置/下置两个机型目录下会各出一条记录，去重后才是唯一。"""
        with tempfile.TemporaryDirectory() as raw:
            sources = self._run(
                Path(raw),
                [
                    {"id": "RAW-1", "name": "设备清单.docx", "materialTier": "project", "folderPath": "技术标/标准文件/A"},
                    {"id": "RAW-2", "name": "设备清单.docx", "materialTier": "project", "folderPath": "技术标/标准文件/B"},
                ],
                ["[设备清单，待插入]"],
                extra_patches=(patch.object(ai_fill, "_run_async", side_effect=RuntimeError("stop here")),),
            )

        self.assertNotEqual(sources[0]["status"], "ambiguous")

    def test_download_failure_degrades_to_manual_not_exception(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            sources = self._run(
                Path(raw),
                [{"id": "RAW-1", "name": "设备清单.docx", "materialTier": "project"}],
                ["[设备清单，待插入]"],
                extra_patches=(patch.object(ai_fill, "_run_async", side_effect=RuntimeError("minio down")),),
            )

        # 一份素材取不到不能中断整份文件的填写
        self.assertEqual(sources[0]["status"], "download_failed")
        self.assertIn("minio down", sources[0]["statusMessage"])

    def test_ready_source_carries_local_path_for_the_skill(self) -> None:
        payload = {"bucket": "materials", "key": "cleaned/设备清单.docx", "fileName": "设备清单.docx"}

        def _run_async_stub(awaitable: object) -> tuple[dict, str]:
            # 真实 _run_async 会 await 掉协程；mock 不 await，这里显式关闭免得留下未等待警告
            if hasattr(awaitable, "close"):
                awaitable.close()
            return payload, "cleaned"

        with tempfile.TemporaryDirectory() as raw:
            with patch.object(ai_fill.minio_client, "download_file") as download:
                sources = self._run(
                    Path(raw),
                    [{"id": "RAW-1", "name": "设备清单.docx", "materialTier": "project"}],
                    ["[设备清单，待插入]"],
                    extra_patches=(patch.object(ai_fill, "_run_async", side_effect=_run_async_stub),),
                )

        self.assertEqual(sources[0]["status"], "ready")
        self.assertEqual(sources[0]["materialTier"], "project")
        self.assertTrue(sources[0]["docxPath"].endswith(".docx"))
        self.assertIn("embed_sources", sources[0]["docxPath"])
        download.assert_called_once()

    def test_no_embed_placeholder_skips_rule_and_material_lookup_entirely(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            blank = tmp / "待填写-方案.docx"
            _write_docx(blank, ["本项目安全等级为[安全等级，待填写]。"])
            with (
                patch.object(ai_fill, "load_embed_rules") as rules,
                patch.object(ai_fill, "_allowed_technical_material_index") as lookup,
            ):
                sources = ai_fill._embed_sources_for_fill(self.project, blank, tmp)

        self.assertEqual(sources, [])
        rules.assert_not_called()
        lookup.assert_not_called()


class EmbedHeadingRangeTests(unittest.TestCase):
    """插入范围来自规则表的起点/终点两列，不再从占位符字符串里拆。

    占位符里那串 `文件-起点-终点` 是给人看的，机器不解析它——素材名自带连字符
    （型式认证名里有四个），按语法拆必然把文件名切碎。
    """

    def setUp(self) -> None:
        self.project = {"id": "PRJ-0001", "name": "示例项目", "bidType": "技术标"}

    def _run(self, tmp: Path, rules: list[dict], paragraph: str) -> list[dict]:
        blank = tmp / "待填写-方案.docx"
        _write_docx(blank, [paragraph])
        payload = {"bucket": "materials", "key": "cleaned/物流解决方案.docx", "fileName": "物流解决方案.docx"}

        def _run_async_stub(awaitable: object) -> tuple[dict, str]:
            if hasattr(awaitable, "close"):
                awaitable.close()
            return payload, "cleaned"

        with (
            patch.object(ai_fill, "load_embed_rules", return_value=rules),
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
            return ai_fill._embed_sources_for_fill(self.project, blank, tmp)

    def test_closed_range_is_handed_to_the_filler(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            sources = self._run(
                Path(raw),
                [
                    _rule(
                        "[物流解决方案-项目运输方案-场内道路建议参数，待插入]",
                        "物流解决方案",
                        start="项目运输方案",
                        end="场内道路建议参数",
                    )
                ],
                "[物流解决方案-项目运输方案-场内道路建议参数，待插入]",
            )

        self.assertEqual(sources[0]["status"], "ready")
        self.assertEqual(sources[0]["headingRange"], {"start": "项目运输方案", "end": "场内道路建议参数"})

    def test_start_only_means_start_equals_end(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            sources = self._run(
                Path(raw),
                [_rule("[物流解决方案-发电量结果，待插入]", "物流解决方案", start="发电量结果")],
                "[物流解决方案-发电量结果，待插入]",
            )

        self.assertEqual(sources[0]["headingRange"], {"start": "发电量结果", "end": "发电量结果"})

    def test_empty_range_means_whole_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            sources = self._run(
                Path(raw),
                [_rule("[物流解决方案-完整插入，待插入]", "物流解决方案")],
                "[物流解决方案-完整插入，待插入]",
            )

        self.assertEqual(sources[0]["status"], "ready")
        self.assertNotIn("headingRange", sources[0])

    def test_hyphenated_placeholder_is_matched_whole_not_split(self) -> None:
        """占位符里带四个连字符也只当匹配键整体比对，切碎它就找不回规则。"""
        placeholder = "[EW5.0-202-FD24C3018（南高齿）齿轮箱型式认证A-完整插入，待插入]"
        with tempfile.TemporaryDirectory() as raw:
            sources = self._run(
                Path(raw), [_rule(placeholder, "物流解决方案")], placeholder
            )

        self.assertEqual(sources[0]["status"], "ready")


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
            patch.object(
                ai_fill,
                "load_embed_rules",
                return_value=[_rule(f"[{source.stem}，待插入]", source.stem)],
            ),
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
