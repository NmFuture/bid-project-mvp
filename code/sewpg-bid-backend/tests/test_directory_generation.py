from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services.outline_generation import _run_local_outline_skill
from app.services.store import store
from app.services.workspace_artifacts import technical_workspace_dir


class DirectoryGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        settings.uploads_dir = base / "uploads"
        settings.documents_dir = base / "documents"
        settings.parsed_dir = base / "parsed"
        settings.ensure_dirs()

        store.reset_for_tests()
        self.client = TestClient(app, base_url="http://127.0.0.1:8000")

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def _write_docx(self, path: Path, paragraphs: list[tuple[str, str | None]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = Document()
        for text, style in paragraphs:
            doc.add_paragraph(text, style=style) if style else doc.add_paragraph(text)
        doc.save(path)

    def _prepare_project_with_parse_result(self) -> str:
        project = store.create_project(
            {
                "name": "目录生成联调项目",
                "customerName": "测试业主",
            }
        )
        project_id = project["id"]

        project_dir = technical_workspace_dir(project_id)
        project_dir.mkdir(parents=True, exist_ok=True)

        tender_path = settings.uploads_dir / project_id / "tender" / "招标文件.docx"
        self._write_docx(
            tender_path,
            [
                ("第一章 采购需求", "Heading 1"),
                ("1.1 项目范围", "Heading 2"),
                ("投标人应提供实施方案。", None),
                ("投标人须提交服务团队安排。", None),
                ("第二章 评审办法", "Heading 1"),
                ("评分项：实施方案，分值30分，证明材料要求：提供项目计划。", None),
            ],
        )

        template_path = settings.uploads_dir / project_id / "template" / "投标文件-正文.docx"
        self._write_docx(
            template_path,
            [
                ("第一章 投标响应概述", "Heading 1"),
                ("1.1 项目理解", "Heading 2"),
                ("第二章 实施方案", "Heading 1"),
                ("2.1 工作计划", "Heading 2"),
            ],
        )

        combined_text_path = project_dir / "combined.txt"
        combined_text_path.write_text(
            "\n".join(
                [
                    "# 文件：招标文件.docx",
                    "",
                    "第一章 采购需求",
                    "1.1 项目范围",
                    "投标人应提供实施方案。",
                    "投标人须提交服务团队安排。",
                    "第二章 评审办法",
                    "评分项：实施方案，分值30分，证明材料要求：提供项目计划。",
                ]
            ),
            encoding="utf-8",
        )

        store.complete_parse(
            project_id,
            tender_files=[
                {
                    "id": "TEN-1",
                    "name": "招标文件.docx",
                    "path": str(tender_path),
                    "size_label": "1.0 MB",
                }
            ],
            template_files=[
                {
                    "id": "TPL-1",
                    "name": "投标文件-正文.docx",
                    "path": str(template_path),
                    "size_label": "1.0 MB",
                }
            ],
            summary={
                "fileCount": 1,
                "extractedCount": 2,
                "textLength": 120,
                "textPreview": "",
                "warnings": [],
            },
            parse_storage={
                "projectDir": str(project_dir),
                "combinedTextPath": str(combined_text_path),
                "manifestPath": "",
                "documents": [],
            },
        )
        return project_id

    def _mock_futurecode_outline(self, prompt: str, *args, **kwargs) -> dict:
        self.assertIn("s2toc", prompt)
        manifest_line = next(line for line in prompt.splitlines() if line.strip().startswith("s2toc "))
        manifest_path = Path(manifest_line.strip().split(" ", 1)[1])
        result = _run_local_outline_skill(manifest_path)
        result["opencodeOutput"] = {
            "status": "received",
            "sessionId": "test-s2-session",
            "providerId": "opencode",
            "modelId": "big-pickle",
            "receivedAt": "2026-05-02T00:00:00Z",
            "parts": [{"type": "text", "text": "{}"}],
        }
        return result

    def test_generate_outline_for_project_calls_futurecode_s2toc_skill(self) -> None:
        from app.services.outline_generation import generate_outline_for_project

        project_id = self._prepare_project_with_parse_result()

        with patch(
            "app.services.opencode_client.OpencodeClient.generate_outline_with_trace",
            side_effect=self._mock_futurecode_outline,
        ) as mock_generate:
            payload = generate_outline_for_project(project_id, {"outlineStrategy": "strict"})

        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["output"]["chapterCount"], 2)
        self.assertTrue(payload["events"])
        self.assertEqual(payload["events"][-1]["level"], "success")
        self.assertTrue(mock_generate.called)
        self.assertEqual(payload["opencodeOutput"]["status"], "received")

    def test_generate_outline_uses_s1_text_and_visual_template_for_non_docx_inputs(self) -> None:
        from app.services.outline_generation import generate_outline_for_project

        project = store.create_project(
            {
                "name": "图片模板目录项目",
                "customerName": "测试业主",
            }
        )
        project_id = project["id"]
        project_dir = technical_workspace_dir(project_id)
        project_dir.mkdir(parents=True, exist_ok=True)

        tender_path = settings.uploads_dir / project_id / "tender" / "招标文件.png"
        tender_path.parent.mkdir(parents=True, exist_ok=True)
        tender_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        template_path = settings.uploads_dir / project_id / "template" / "投标模板.png"
        template_path.parent.mkdir(parents=True, exist_ok=True)
        template_path.write_bytes(b"\x89PNG\r\n\x1a\nfake-template")

        combined_text_path = project_dir / "combined.txt"
        combined_text_path.write_text(
            "\n".join(
                [
                    "# 文件：招标文件.png",
                    "",
                    "第一章 采购需求",
                    "投标人应提供实施方案。",
                    "投标人须提交服务团队安排。",
                ]
            ),
            encoding="utf-8",
        )
        store.complete_parse(
            project_id,
            tender_files=[
                {
                    "id": "TEN-1",
                    "name": "招标文件.png",
                    "path": str(tender_path),
                    "size_label": "1.0 MB",
                }
            ],
            template_files=[
                {
                    "id": "TPL-1",
                    "name": "投标模板.png",
                    "path": str(template_path),
                    "size_label": "1.0 MB",
                }
            ],
            summary={
                "fileCount": 1,
                "extractedCount": 1,
                "textLength": 80,
                "textPreview": "",
                "warnings": [],
            },
            parse_storage={
                "projectDir": str(project_dir),
                "combinedTextPath": str(combined_text_path),
                "manifestPath": "",
                "documents": [],
            },
        )

        with patch(
            "app.services.outline_generation._ocr_fallback_text",
            return_value=("第一章 投标响应概述\n1.1 项目理解\n第二章 实施方案\n2.1 工作计划", {"status": "completed"}),
        ):
            payload = generate_outline_for_project(project_id, {"outlineStrategy": "strict"})

        self.assertEqual(payload["status"], "completed")
        self.assertGreaterEqual(payload["output"]["chapterCount"], 2)
        workspace = store.get_directory_state(project_id)["opencodeOutput"]["workDir"]
        manifest = json.loads((Path(workspace) / "s2_input.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(manifest["templateFile"]).suffix, ".docx")
        self.assertEqual(Path(manifest["tenderFiles"][0]["path"]).suffix, ".docx")
        self.assertEqual(payload["opencodeOutput"]["engine"], "bid-tech-outline-generator")
        self.assertEqual(payload["opencodeOutput"]["skill"], "bid-tech-outline-generator")
        self.assertTrue(payload["opencodeOutput"]["parts"])
        self.assertTrue(Path(payload["opencodeOutput"]["tocJsonPath"]).exists())
        self.assertTrue(Path(payload["opencodeOutput"]["evidencePath"]).exists())
        self.assertEqual(
            payload["opencodeOutput"]["manifestPath"],
            payload["opencodeOutput"]["canonicalManifestPath"],
        )
        self.assertTrue(Path(payload["opencodeOutput"]["canonicalManifestPath"]).exists())
        self.assertFalse((settings.parsed_dir / project_id / "s2.json").exists())
        self.assertEqual(Path(payload["opencodeOutput"]["workDir"]).name, "s2_toc_workdir")

        outline = store.get_outline_state(project_id)
        self.assertEqual(outline["reviewStatus"], "draft")
        self.assertEqual(len(outline["nodes"]), 2)
        self.assertEqual(outline["nodes"][0]["title"], "第一章 投标响应概述")
        self.assertEqual(outline["nodes"][1]["title"], "第二章 实施方案")
        self.assertFalse(
            any(child["title"] == "服务团队安排" for child in outline["nodes"][1]["children"])
        )
        self.assertEqual(outline["summary"]["totalNodeCount"], 4)

    def test_generate_outline_archives_previous_successful_workspace_on_success(self) -> None:
        from app.services.outline_generation import generate_outline_for_project

        project_id = self._prepare_project_with_parse_result()

        with patch(
            "app.services.opencode_client.OpencodeClient.generate_outline_with_trace",
            side_effect=self._mock_futurecode_outline,
        ):
            first_payload = generate_outline_for_project(project_id, {"outlineStrategy": "strict"})

        project_dir = technical_workspace_dir(project_id)
        work_dir = project_dir / "s2_toc_workdir"
        marker = work_dir / "previous-marker.txt"
        marker.write_text("previous run", encoding="utf-8")

        with patch(
            "app.services.opencode_client.OpencodeClient.generate_outline_with_trace",
            side_effect=self._mock_futurecode_outline,
        ):
            second_payload = generate_outline_for_project(project_id, {"outlineStrategy": "strict"})

        self.assertTrue(Path(first_payload["opencodeOutput"]["tocJsonPath"]).exists())
        self.assertTrue(Path(second_payload["opencodeOutput"]["tocJsonPath"]).exists())
        self.assertFalse(marker.exists())
        archive_root = project_dir / "s2_toc_workdir.runs"
        archived_markers = list(archive_root.glob("*/previous-marker.txt"))
        self.assertEqual(len(archived_markers), 1)

        manifest = json.loads(Path(second_payload["opencodeOutput"]["canonicalManifestPath"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["workDir"], str(work_dir))
        self.assertFalse(any(".new" in str(value) for value in manifest.values() if isinstance(value, str)))

    def test_generate_outline_failure_preserves_previous_successful_workspace(self) -> None:
        from app.services.outline_generation import generate_outline_for_project

        project_id = self._prepare_project_with_parse_result()

        with patch(
            "app.services.opencode_client.OpencodeClient.generate_outline_with_trace",
            side_effect=self._mock_futurecode_outline,
        ):
            first_payload = generate_outline_for_project(project_id, {"outlineStrategy": "strict"})

        work_dir = technical_workspace_dir(project_id) / "s2_toc_workdir"
        previous_toc = Path(first_payload["opencodeOutput"]["tocJsonPath"])
        marker = work_dir / "previous-marker.txt"
        marker.write_text("keep me", encoding="utf-8")

        with patch(
            "app.services.opencode_client.OpencodeClient.generate_outline_with_trace",
            side_effect=RuntimeError("futurecode down"),
        ), patch(
            "app.services.outline_generation._run_local_outline_skill",
            side_effect=RuntimeError("local fallback down"),
        ):
            with self.assertRaises(RuntimeError):
                generate_outline_for_project(project_id, {"outlineStrategy": "strict"})

        self.assertTrue(work_dir.exists())
        self.assertTrue(previous_toc.exists())
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep me")
        self.assertTrue((technical_workspace_dir(project_id) / "s2_toc_workdir.new").exists())

    def test_publish_failure_preserves_previous_successful_workspace(self) -> None:
        from app.services.outline_generation import generate_outline_for_project

        project_id = self._prepare_project_with_parse_result()

        with patch(
            "app.services.opencode_client.OpencodeClient.generate_outline_with_trace",
            side_effect=self._mock_futurecode_outline,
        ):
            first_payload = generate_outline_for_project(project_id, {"outlineStrategy": "strict"})

        project_dir = technical_workspace_dir(project_id)
        work_dir = project_dir / "s2_toc_workdir"
        previous_toc = Path(first_payload["opencodeOutput"]["tocJsonPath"])
        marker = work_dir / "previous-marker.txt"
        marker.write_text("keep me", encoding="utf-8")

        with patch(
            "app.services.opencode_client.OpencodeClient.generate_outline_with_trace",
            side_effect=self._mock_futurecode_outline,
        ), patch(
            "app.services.outline_generation._remap_json_file",
            side_effect=RuntimeError("remap failed"),
        ):
            with self.assertRaises(RuntimeError):
                generate_outline_for_project(project_id, {"outlineStrategy": "strict"})

        self.assertTrue(work_dir.exists())
        self.assertTrue(previous_toc.exists())
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep me")
        self.assertTrue((project_dir / "s2_toc_workdir.new").exists())

    def test_generate_outline_outputs_template_and_tender_evidence_only(self) -> None:
        from app.services.outline_generation import generate_outline_for_project

        project_id = self._prepare_project_with_parse_result()

        with patch(
            "app.services.opencode_client.OpencodeClient.generate_outline_with_trace",
            side_effect=self._mock_futurecode_outline,
        ):
            payload = generate_outline_for_project(project_id, {"outlineStrategy": "strict"})
        toc_path = Path(payload["opencodeOutput"]["tocJsonPath"])
        toc = __import__("json").loads(toc_path.read_text(encoding="utf-8"))

        self.assertEqual(toc["schema_version"], "bid-toc-json-v1")
        self.assertTrue(toc["items"])
        sources = {item["source"] for item in toc["items"]}
        self.assertLessEqual(sources, {"template", "tender"})
        self.assertNotIn("wiki", sources)
        self.assertTrue(all(item.get("material_refs") == [] for item in toc["items"]))
        self.assertFalse(any(item["annotation"] == "新增-招标要求" for item in toc["items"]))

    def test_generate_outline_records_generic_evidence(self) -> None:
        from app.services.outline_generation import generate_outline_for_project

        project_id = self._prepare_project_with_parse_result()
        with patch(
            "app.services.opencode_client.OpencodeClient.generate_outline_with_trace",
            side_effect=self._mock_futurecode_outline,
        ):
            payload = generate_outline_for_project(project_id, {"outlineStrategy": "strict"})
        evidence_path = Path(payload["opencodeOutput"]["evidencePath"])
        evidence = __import__("json").loads(evidence_path.read_text(encoding="utf-8"))

        self.assertEqual(evidence["schema_version"], "bid-toc-evidence-v1")
        self.assertEqual(evidence["engine"], "bid-tech-outline-generator")
        self.assertTrue(evidence["templateOutline"])
        self.assertTrue(evidence["tenderCandidates"])
        self.assertTrue(
            any(
                item["action"] == "candidate" and item["title"] == "服务团队安排"
                for item in evidence["decisions"]
            )
        )
        self.assertFalse(any("华能" in __import__("json").dumps(item, ensure_ascii=False) for item in evidence["decisions"]))

    def test_generate_outline_links_tender_basis_and_adds_appendix_items(self) -> None:
        from app.services.outline_generation import generate_outline_for_project

        project_id = self._prepare_project_with_parse_result()
        tender_path = settings.uploads_dir / project_id / "tender" / "招标文件.docx"
        self._write_docx(
            tender_path,
            [
                ("第一章 采购需求", "Heading 1"),
                ("投标人应提供实施方案。", None),
                ("附表D.7 性能及考核承诺保证表", None),
            ],
        )

        with patch(
            "app.services.opencode_client.OpencodeClient.generate_outline_with_trace",
            side_effect=self._mock_futurecode_outline,
        ):
            payload = generate_outline_for_project(project_id, {"outlineStrategy": "strict"})
        toc = __import__("json").loads(Path(payload["opencodeOutput"]["tocJsonPath"]).read_text(encoding="utf-8"))

        implementation_item = next(item for item in toc["items"] if "实施方案" in item["title"])
        tender_refs = [ref for ref in implementation_item["source_refs"] if ref["type"] == "tender"]
        self.assertTrue(tender_refs)
        self.assertEqual(tender_refs[0]["fileId"], "TEN-1")
        self.assertIn("投标人应提供实施方案", tender_refs[0]["basisText"])

        appendix_items = [item for item in toc["items"] if item["annotation"] == "新增-副表"]
        self.assertTrue(any("性能及考核承诺保证表" in item["title"] for item in appendix_items))
        self.assertTrue(appendix_items[0]["source_refs"][0]["basisText"])

    def test_tender_candidate_zero_limit_means_unlimited_and_strips_page_numbers(self) -> None:
        from app.services.outline_generation import generate_outline_for_project

        project_id = self._prepare_project_with_parse_result()
        tender_path = settings.uploads_dir / project_id / "tender" / "招标文件.docx"
        paragraphs = [("第一章 采购需求", "Heading 1")]
        paragraphs.extend((f"投标人须提交前置章节{index}说明 {100 + index}", None) for index in range(1, 30))
        paragraphs.append(("附表D.7 性能及考核承诺保证表 188", None))
        self._write_docx(tender_path, paragraphs)

        with patch(
            "app.services.opencode_client.OpencodeClient.generate_outline_with_trace",
            side_effect=self._mock_futurecode_outline,
        ):
            payload = generate_outline_for_project(project_id, {"outlineStrategy": "strict"})

        toc = __import__("json").loads(Path(payload["opencodeOutput"]["tocJsonPath"]).read_text(encoding="utf-8"))
        evidence = __import__("json").loads(Path(payload["opencodeOutput"]["evidencePath"]).read_text(encoding="utf-8"))

        self.assertGreaterEqual(len(evidence["tenderCandidates"]), 30)
        self.assertTrue(
            any(
                item["title"] == "性能及考核承诺保证表"
                for item in toc["items"]
                if item["annotation"] == "新增-副表"
            )
        )
        self.assertFalse(
            any(
                item["title"].endswith("188")
                for item in toc["items"]
                if "性能及考核承诺保证表" in item["title"]
            )
        )

    def test_only_explicit_appendix_tables_are_auto_added_after_template_outline(self) -> None:
        from app.services.outline_generation import generate_outline_for_project

        project_id = self._prepare_project_with_parse_result()
        template_path = settings.uploads_dir / project_id / "template" / "投标模板.docx"
        self._write_docx(
            template_path,
            [
                ("第1章 风资源评估与机位排布方案", "Heading 1"),
                ("1.1 项目风资源评估与机组选型排布及发电量计算", "Heading 2"),
                ("第2章 产品交付、考核及验收", "Heading 1"),
            ],
        )
        tender_path = settings.uploads_dir / project_id / "tender" / "招标文件.docx"
        self._write_docx(
            tender_path,
            [
                ("第一章 招标要求", "Heading 1"),
                ("技术附表E 项目风资源评估及机组选型排布及发电量计算 194", None),
                ("附表E.2 风电场保证电量计算折减因素及相关要求表 194", None),
                ("表5.2.6-1 测风塔不同高度间风速相关系数表", None),
            ],
        )

        parse_result = store.get_parse_result(project_id)
        parse_storage = store.get_parse_storage(project_id)
        store.complete_parse(
            project_id,
            tender_files=[
                {
                    "id": "TEN-1",
                    "name": "招标文件.docx",
                    "path": str(tender_path),
                    "size_label": "1.0 MB",
                }
            ],
            template_files=[
                {
                    "id": "TPL-1",
                    "name": "投标模板.docx",
                    "path": str(template_path),
                    "size_label": "1.0 MB",
                }
            ],
            summary=parse_result["summary"],
            parse_storage=parse_storage,
        )

        with patch(
            "app.services.opencode_client.OpencodeClient.generate_outline_with_trace",
            side_effect=self._mock_futurecode_outline,
        ):
            payload = generate_outline_for_project(project_id, {"outlineStrategy": "strict"})
        toc = __import__("json").loads(Path(payload["opencodeOutput"]["tocJsonPath"]).read_text(encoding="utf-8"))
        titles = [item["title"] for item in toc["items"]]

        self.assertIn("风电场保证电量计算折减因素及相关要求表", titles)
        self.assertNotIn("测风塔不同高度间风速相关系数表", titles)
        wind_index = titles.index("风资源评估与机位排布方案")
        wind_child_index = titles.index("项目风资源评估与机组选型排布及发电量计算")
        appendix_index = titles.index("风电场保证电量计算折减因素及相关要求表")
        delivery_index = titles.index("产品交付、考核及验收")
        self.assertGreater(wind_child_index, wind_index)
        self.assertGreater(appendix_index, delivery_index)
        self.assertEqual(appendix_index, len(titles) - 1)
        self.assertEqual(toc["items"][appendix_index]["level"], 1)
        self.assertEqual(toc["items"][appendix_index]["number"], "附表E.2")

    def test_added_items_do_not_shift_later_template_source_refs(self) -> None:
        import importlib.util
        import sys

        script_path = (
            Path(__file__).resolve().parents[1]
            / "opencode"
            / "skill"
            / "bid-tech-outline-generator"
            / "scripts"
            / "run_from_manifest.py"
        )
        spec = importlib.util.spec_from_file_location("outline_runner_for_shift_test", script_path)
        outline_runner = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules["outline_runner_for_shift_test"] = outline_runner
        spec.loader.exec_module(outline_runner)

        template_outline = [
            outline_runner.OutlineEntry("1", "风资源评估与机位排布方案", 1, "template.docx", 1, "第1章 风资源评估与机位排布方案"),
            outline_runner.OutlineEntry("1.1", "项目风资源评估与机组选型排布及发电量计算", 2, "template.docx", 2, "1.1 项目风资源评估与机组选型排布及发电量计算"),
            outline_runner.OutlineEntry("2", "产品交付、考核及验收", 1, "template.docx", 3, "第2章 产品交付、考核及验收"),
            outline_runner.OutlineEntry("2.1", "设备安装、调试与试运行", 2, "template.docx", 4, "2.1 设备安装、调试与试运行"),
        ]
        tender_candidates = [
            outline_runner.Candidate(
                id="TC-0001",
                title="附表E.2 风电场保证电量计算折减因素及相关要求表",
                raw_text="附表E.2 风电场保证电量计算折减因素及相关要求表 194",
                source_file="tender.docx",
                file_id="TEN-1",
                file_name="tender.docx",
                paragraph_index=10,
                kind="appendix",
                number="附表E.2",
                context_title="技术附表E 项目风资源评估及机组选型排布及发电量计算",
            ),
            outline_runner.Candidate(
                id="TC-0002",
                title="设备安装、调试与试运行",
                raw_text="5. 设备安装、调试与试运行 101",
                source_file="tender.docx",
                file_id="TEN-1",
                file_name="tender.docx",
                paragraph_index=20,
                kind="heading",
                number="5",
            ),
        ]
        items, _ = outline_runner.build_items(template_outline, [], tender_candidates)

        install_item = next(item for item in items if item["title"] == "设备安装、调试与试运行")
        refs = [ref for ref in install_item["source_refs"] if ref["type"] == "tender"]
        self.assertTrue(refs)
        self.assertIn("设备安装、调试与试运行", refs[0]["basisText"])

    def test_get_directory_state_loads_rule_evidence_from_existing_file(self) -> None:
        from app.services.outline_generation import generate_outline_for_project

        project_id = self._prepare_project_with_parse_result()
        with patch(
            "app.services.opencode_client.OpencodeClient.generate_outline_with_trace",
            side_effect=self._mock_futurecode_outline,
        ):
            payload = generate_outline_for_project(project_id, {"outlineStrategy": "strict"})
        project = store._require(project_id)
        project["directory_state"].pop("ruleEvidence", None)

        state = store.get_directory_state(project_id)

        self.assertEqual(state["ruleEvidence"]["engine"], "bid-tech-outline-generator")
        self.assertGreater(state["ruleEvidence"]["tenderCandidateCount"], 0)
        self.assertTrue(state["ruleEvidence"]["decisions"])
        self.assertEqual(
            state["ruleEvidence"]["schemaVersion"],
            "bid-toc-evidence-v1",
        )
        self.assertTrue(Path(payload["opencodeOutput"]["evidencePath"]).exists())

    def test_generate_outline_prefers_template_headings_then_adds_uncovered_tender_requirements(self) -> None:
        from app.services.outline_generation import generate_outline_for_project

        project_id = self._prepare_project_with_parse_result()
        template_path = settings.uploads_dir / project_id / "template" / "投标模板.docx"
        template_path.parent.mkdir(parents=True, exist_ok=True)

        document = Document()
        document.add_paragraph("目录")
        document.add_paragraph("第1章 响应概述")
        document.add_paragraph("1.1 基本响应")
        document.add_paragraph("第2章 项目交付方案")
        document.add_paragraph("2.1 进度安排")
        document.save(template_path)

        parse_result = store.get_parse_result(project_id)
        parse_storage = store.get_parse_storage(project_id)
        store.complete_parse(
            project_id,
            tender_files=[
                {
                    "id": "TEN-1",
                    "name": "招标文件.docx",
                    "path": str(settings.uploads_dir / project_id / "tender" / "招标文件.docx"),
                    "size_label": "1.0 MB",
                }
            ],
            template_files=[
                {
                    "id": "TPL-1",
                    "name": "投标模板.docx",
                    "path": str(template_path),
                    "size_label": "2.0 MB",
                }
            ],
            summary=parse_result["summary"],
            parse_storage=parse_storage,
        )

        with patch(
            "app.services.opencode_client.OpencodeClient.generate_outline_with_trace",
            side_effect=self._mock_futurecode_outline,
        ):
            generate_outline_for_project(project_id, {"outlineStrategy": "strict"})

        outline = store.get_outline_state(project_id)
        self.assertEqual(outline["nodes"][0]["title"], "第1章 响应概述")
        self.assertEqual(outline["nodes"][0]["children"][0]["title"], "基本响应")
        self.assertEqual(outline["nodes"][1]["title"], "第2章 项目交付方案")
        self.assertFalse(any(child["title"] == "服务团队安排" for child in outline["nodes"][1]["children"]))

    def test_generate_outline_uses_template_toc_region_not_full_body_headings(self) -> None:
        from app.services.outline_generation import generate_outline_for_project

        project_id = self._prepare_project_with_parse_result()
        template_path = settings.uploads_dir / project_id / "template" / "投标模板.docx"
        template_path.parent.mkdir(parents=True, exist_ok=True)

        document = Document()
        document.styles.add_style("toc 1", WD_STYLE_TYPE.PARAGRAPH)
        document.styles.add_style("toc 2", WD_STYLE_TYPE.PARAGRAPH)
        document.add_paragraph("目录")
        document.add_paragraph("第1章 模板总述\t1", style="toc 1")
        document.add_paragraph("1.1 基本情况\t2", style="toc 2")
        document.add_paragraph("第2章 正文标题不能进入目录", style="Heading 1")
        document.add_paragraph("2.1 正文小节不能进入目录", style="Heading 2")
        document.add_paragraph("（1）正文编号清单不能进入目录")
        document.save(template_path)

        parse_result = store.get_parse_result(project_id)
        parse_storage = store.get_parse_storage(project_id)
        store.complete_parse(
            project_id,
            tender_files=[
                {
                    "id": "TEN-1",
                    "name": "招标文件.docx",
                    "path": str(settings.uploads_dir / project_id / "tender" / "招标文件.docx"),
                    "size_label": "1.0 MB",
                }
            ],
            template_files=[
                {
                    "id": "TPL-1",
                    "name": "投标模板.docx",
                    "path": str(template_path),
                    "size_label": "2.0 MB",
                }
            ],
            summary=parse_result["summary"],
            parse_storage=parse_storage,
        )

        with patch(
            "app.services.opencode_client.OpencodeClient.generate_outline_with_trace",
            side_effect=self._mock_futurecode_outline,
        ):
            payload = generate_outline_for_project(project_id, {"outlineStrategy": "strict"})
        toc_path = Path(payload["opencodeOutput"]["tocJsonPath"])
        toc = __import__("json").loads(toc_path.read_text(encoding="utf-8"))
        template_items = [item for item in toc["items"] if item["source"] == "template"]

        self.assertEqual([item["title"] for item in template_items], ["模板总述", "基本情况"])
        self.assertFalse(any("不能进入目录" in item["title"] for item in toc["items"]))

    def test_run_directory_generation_returns_running_state_immediately(self) -> None:
        project_id = self._prepare_project_with_parse_result()

        with patch("app.api.routes.directory._schedule_directory_generation_job"):
            response = self.client.post(
                f"/api/projects/{project_id}/directory-generation/run",
                json={"outlineStrategy": "strict"},
            )

        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertEqual(payload["status"], "running")
        self.assertEqual(payload["tasks"][0]["status"], "running")
        self.assertEqual(payload["tasks"][1]["status"], "pending")

    def test_generate_outline_fails_when_template_is_missing(self) -> None:
        from app.services.outline_generation import generate_outline_for_project

        project_id = self._prepare_project_with_parse_result()
        store.update_template_fallback(project_id, {"enabled": False})
        parse_result = store.get_parse_result(project_id)
        parse_storage = store.get_parse_storage(project_id)
        store.complete_parse(
            project_id,
            tender_files=[
                {
                    "id": "TEN-1",
                    "name": "招标文件.docx",
                    "path": str(settings.uploads_dir / project_id / "tender" / "招标文件.docx"),
                    "size_label": "1.0 MB",
                }
            ],
            template_files=[],
            summary=parse_result["summary"],
            parse_storage=parse_storage,
        )

        with self.assertRaisesRegex(ValueError, "投标模板"):
            generate_outline_for_project(project_id, {"outlineStrategy": "strict"})

    def test_generate_outline_rejects_invalid_project_template_docx(self) -> None:
        from app.services.outline_generation import generate_outline_for_project

        project_id = self._prepare_project_with_parse_result()
        parse_result = store.get_parse_result(project_id)
        parse_storage = store.get_parse_storage(project_id)
        bad_template = settings.uploads_dir / project_id / "template" / "bad-template.docx"
        bad_template.parent.mkdir(parents=True, exist_ok=True)
        bad_template.write_bytes(b"bad docx")
        store.complete_parse(
            project_id,
            tender_files=[
                {
                    "id": "TEN-1",
                    "name": "招标文件.docx",
                    "path": str(settings.uploads_dir / project_id / "tender" / "招标文件.docx"),
                    "size_label": "1.0 MB",
                }
            ],
            template_files=[
                {
                    "id": "TPL-1",
                    "name": "坏模板.docx",
                    "path": str(bad_template),
                    "size_label": "7 B",
                }
            ],
            summary=parse_result["summary"],
            parse_storage=parse_storage,
        )

        with self.assertRaisesRegex(ValueError, "不是有效 DOCX"):
            generate_outline_for_project(project_id, {"outlineStrategy": "strict"})

    def test_futurecode_progress_updates_before_completion(self) -> None:
        from app.api.routes.directory import _handle_directory_progress

        project_id = self._prepare_project_with_parse_result()
        store.start_directory_generation(project_id)

        _handle_directory_progress(
            project_id,
            "outline_session_ready",
            {
                "sessionId": "SESSION-1",
                "providerId": "opencode",
                "modelId": "big-pickle",
            },
        )

        state = store.get_directory_state(project_id)
        self.assertEqual(state["status"], "running")
        self.assertEqual(state["percentage"], 45)
        self.assertEqual(state["opencodeOutput"]["status"], "waiting")
        self.assertEqual(state["opencodeOutput"]["sessionId"], "SESSION-1")
        self.assertEqual(state["events"][-1]["step"], "futurecode_session")
        self.assertIn("futurecode", state["events"][-1]["message"])

    def test_background_job_updates_running_state_then_completes(self) -> None:
        from app.api.routes.directory import _handle_directory_progress, _run_directory_generation_job

        project_id = self._prepare_project_with_parse_result()
        store.start_directory_generation(project_id)

        _handle_directory_progress(
            project_id,
            "inputs_ready",
            {"tenderFileCount": 1, "templateFileCount": 1},
        )
        running_state = store.get_directory_state(project_id)
        self.assertEqual(running_state["status"], "running")
        self.assertEqual(running_state["percentage"], 30)
        self.assertEqual(running_state["tasks"][1]["status"], "running")
        self.assertEqual(running_state["events"][-1]["step"], "hint_ready")
        self.assertEqual(running_state["opencodeOutput"]["status"], "idle")

        _handle_directory_progress(
            project_id,
            "outline_session_ready",
            {
                "sessionId": "SESSION-1",
                "providerId": "opencode",
                "modelId": "big-pickle",
            },
        )

        with patch(
            "app.services.opencode_client.OpencodeClient.generate_outline_with_trace",
            side_effect=self._mock_futurecode_outline,
        ):
            _run_directory_generation_job(project_id, {"outlineStrategy": "strict"})

        completed_state = store.get_directory_state(project_id)
        self.assertEqual(completed_state["status"], "completed")
        self.assertEqual(completed_state["percentage"], 100)
        self.assertEqual(completed_state["tasks"][2]["status"], "done")
        self.assertEqual(completed_state["events"][-1]["level"], "success")
        self.assertEqual(completed_state["opencodeOutput"]["status"], "received")
        self.assertTrue(completed_state["opencodeOutput"]["parts"])

    def test_directory_generation_stream_returns_event_stream_payload(self) -> None:
        project_id = self._prepare_project_with_parse_result()
        store.complete_directory_generation(project_id, {})

        with self.client.stream(
            "GET",
            f"/api/projects/{project_id}/directory-generation/stream",
        ) as response:
            chunks = response.iter_text()
            first_chunk = next(chunks)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"].split(";")[0], "text/event-stream")
        self.assertIn('"status": "completed"', first_chunk)
        self.assertIn('"summary": "目录生成完成。"', first_chunk)


if __name__ == "__main__":
    unittest.main()
