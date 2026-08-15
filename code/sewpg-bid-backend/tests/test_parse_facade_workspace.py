from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch
from app.core.config import settings
from app.services.file_utils import format_size_mb
from app.services.store import store

from parse_pipeline_helpers import (
    ParsePipelineTestBase,
    build_appendix_docx_bytes,
    build_docx_bytes,
    complete_parse_for_tests,
    parse_inputs_for_tests,
)


class ParsePipelineTests(ParsePipelineTestBase):

    def test_participating_promotes_parse_json_and_appendices_to_workspace(self) -> None:
        project_id = self.create_project()
        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "tenderFiles",
                    (
                        "含附表招标文件.docx",
                        build_appendix_docx_bytes(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
        )
        self.assertEqual(response.status_code, 200)
        temp_appendix_path = Path(response.json()["structured"]["appendices"][0]["docxPath"])
        self.assertIn(str(settings.parsed_dir / project_id / "s1_appendices"), str(temp_appendix_path))
        temp_project_dir = settings.parsed_dir / project_id
        self.assertTrue(temp_project_dir.exists())
        stale_path = settings.documents_dir / project_id / "technical-workspace" / "appendices" / "stale.docx"
        stale_path.parent.mkdir(parents=True, exist_ok=True)
        stale_path.write_bytes(b"old")

        updated = self.client.put(
            self.project_url(project_id),
            json={
                "name": "参与后归档项目",
                "customerName": "测试业主",
                "manager": "项目经理",
                "startDate": "2026-01-01",
                "endDate": "2026-02-01",
                "bidType": "技术标",
                "reviewDecision": "participate",
            },
        )

        self.assertEqual(updated.status_code, 200)
        self.assertFalse(stale_path.exists())
        workspace_parse_dir = settings.documents_dir / project_id / "technical-workspace" / "parse"
        workspace_appendix_dir = settings.documents_dir / project_id / "technical-workspace" / "appendices"
        self.assertTrue((workspace_parse_dir / "s1_structured_result.json").exists())
        self.assertTrue((workspace_parse_dir / "parse-result.workspace.json").exists())
        workspace_appendices = sorted(workspace_appendix_dir.glob("*.docx"))
        self.assertEqual(len(workspace_appendices), 1)
        self.assertFalse(temp_project_dir.exists())

        promoted_payload = self.client.get(self.parse_results_url(project_id))
        self.assertEqual(promoted_payload.status_code, 200)
        appendix = promoted_payload.json()["structured"]["appendices"][0]
        self.assertIn(str(workspace_appendix_dir), appendix["docxPath"])
        self.assertEqual(appendix["workspacePath"], f"technical-workspace/appendices/{workspace_appendices[0].name}")

        project = store._require(project_id)
        parse_storage = project["parse_storage"]
        self.assertEqual(Path(parse_storage["projectDir"]), settings.documents_dir / project_id / "technical-workspace")
        self.assertEqual(Path(parse_storage["parseDir"]), workspace_parse_dir)
        self.assertEqual(Path(parse_storage["combinedTextPath"]), workspace_parse_dir / "combined.txt")
        self.assertEqual(Path(parse_storage["structuredResultPath"]), workspace_parse_dir / "s1_structured_result.json")
        self.assertEqual(Path(parse_storage["manifestPath"]), workspace_parse_dir / "manifest.json")
        self.assertEqual(Path(parse_storage["skillManifestPath"]), workspace_parse_dir / "s1_parse_manifest.json")
        self.assertTrue(all(str(workspace_parse_dir) in item["textPath"] for item in parse_storage["documents"]))

        preview = self.client.get(self.parse_results_url(project_id, "/appendices/APPX-0001/preview"))
        self.assertEqual(preview.status_code, 200)
        self.assertIn(str(workspace_appendix_dir), preview.json()["docxPath"])
        self.assertFalse(temp_project_dir.exists())



    def test_participating_project_reparse_refreshes_workspace_parse_artifacts(self) -> None:
        project_id = self.create_project()

        def fake_parse_with_appendix(title: str):
            def fake_parse(
                project_id_arg,
                tender_files,
                *,
                bid_type,
                progress_callback=None,
                cancel_check=None,
                require_preparsed_pdf=False,
            ):
                parse_dir = settings.parsed_dir / project_id_arg
                parse_dir.mkdir(parents=True, exist_ok=True)
                combined_path = parse_dir / "combined.txt"
                manifest_path = parse_dir / "manifest.json"
                skill_manifest_path = parse_dir / "s1_parse_manifest.json"
                structured_path = parse_dir / "s1_structured_result.json"
                rows = [["序号", "项目", "投标响应"], ["1", title, ""]]
                structured = {
                    "schemaVersion": "bid-tender-structured-v1",
                    "projectDates": {"startDate": "", "endDate": ""},
                    "appendices": [
                        {
                            "id": "APPX-0001",
                            "title": title,
                            "status": "generated",
                            "sourceFile": tender_files[0]["name"],
                            "rows": rows,
                            "contentBlocks": [{"type": "table", "rows": rows}],
                            "rowCount": len(rows),
                            "docxPath": "",
                            "extractionMode": "pdf_document_nav_slice",
                        }
                    ],
                }
                combined_path.write_text(title, encoding="utf-8")
                manifest = {
                    "documents": [
                        {
                            "id": "TEN-1",
                            "name": tender_files[0]["name"],
                            "textPath": str(combined_path),
                            "pageCount": 1,
                            "textLength": len(title),
                        }
                    ]
                }
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
                skill_manifest_path.write_text(json.dumps({"structuredResultPath": str(structured_path)}), encoding="utf-8")
                structured_path.write_text(
                    json.dumps({"items": [], "structured": structured}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                return (
                    {"fileCount": 1, "extractedCount": 0, "textLength": len(title), "textPreview": title, "warnings": []},
                    {
                        "documents": manifest["documents"],
                        "items": [],
                        "structured": structured,
                        "combinedTextPath": str(combined_path),
                        "manifestPath": str(manifest_path),
                        "skillManifestPath": str(skill_manifest_path),
                        "structuredResultPath": str(structured_path),
                        "projectUpdates": {},
                    },
                )

            return fake_parse

        with patch("app.services.bid_parse_service.parse_tender_documents", side_effect=fake_parse_with_appendix("附表1 初版")):
            first = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[("tenderFiles", ("first.pdf", b"%PDF-1.4\n", "application/pdf"))],
            )
        self.assertEqual(first.status_code, 200)

        updated = self.client.put(
            self.project_url(project_id),
            json={
                "name": "参与后重复解析项目",
                "customerName": "测试业主",
                "bidType": "技术标",
                "reviewDecision": "participate",
            },
        )
        self.assertEqual(updated.status_code, 200)

        workspace_parse_result = settings.documents_dir / project_id / "technical-workspace" / "parse" / "parse-result.workspace.json"
        self.assertTrue(workspace_parse_result.exists())
        self.assertEqual(
            json.loads(workspace_parse_result.read_text(encoding="utf-8"))["structured"]["appendices"][0]["title"],
            "附表1 初版",
        )

        with patch("app.services.bid_parse_service.parse_tender_documents", side_effect=fake_parse_with_appendix("附表2 重解析新版")):
            second = self.client.post(
                self.parse_results_url(project_id, "/upload-and-run"),
                files=[("tenderFiles", ("second.pdf", b"%PDF-1.4\n", "application/pdf"))],
            )
        self.assertEqual(second.status_code, 200)

        refreshed = json.loads(workspace_parse_result.read_text(encoding="utf-8"))
        appendix = refreshed["structured"]["appendices"][0]
        self.assertEqual(appendix["title"], "附表2 重解析新版")
        self.assertEqual(appendix["extractionMode"], "pdf_document_nav_slice")
        self.assertIn("technical-workspace/appendices/", appendix["workspacePath"])
        self.assertTrue(Path(appendix["docxPath"]).exists())



    def test_business_bid_participating_promotes_parse_json_to_business_workspace(self) -> None:
        project_id = self.create_business_project()
        tender = "\n".join(
            [
                "# 商务招标文件",
                "项目名称：商务归档测试项目",
                "招标编号：BUS-2026-002",
                "投标保证金：须提交保函。",
                "投标人不得存在下列情形之一。",
                "附表1：商务偏差表",
                "| 序号 | 条款 | 偏差说明 |",
                "| --- | --- | --- |",
                "| 1 | 付款条件 | |",
            ]
        ).encode("utf-8")

        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[("tenderFiles", ("商务招标文件.md", tender, "text/markdown"))],
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["structured"]["schemaVersion"], "bid-business-tender-structured-v1")
        approve_response = self.client.post(
            self.parse_results_url(project_id, "/commitment-letters/approve"),
            json={"approved": True},
        )
        self.assertEqual(approve_response.status_code, 200)
        self.assertEqual(approve_response.json()["approvedCount"], 1)

        updated = self.client.put(
            self.project_url(project_id),
            json={
                "name": "商务归档测试项目",
                "customerName": "测试业主",
                "bidType": "商务标",
                "reviewDecision": "participate",
            },
        )
        self.assertEqual(updated.status_code, 200)

        workspace_parse_dir = settings.documents_dir / project_id / "business-workspace" / "parse"
        workspace_appendix_dir = settings.documents_dir / project_id / "business-workspace" / "appendices"
        workspace_commitment_dir = settings.documents_dir / project_id / "business-workspace" / "commitment-letters"
        self.assertTrue((workspace_parse_dir / "s1_structured_result.json").exists())
        self.assertTrue((workspace_parse_dir / "parse-result.workspace.json").exists())
        self.assertTrue(workspace_appendix_dir.exists())
        self.assertTrue(workspace_commitment_dir.exists())

        project = store._require(project_id)
        parse_storage = project["parse_storage"]
        self.assertEqual(Path(parse_storage["projectDir"]), settings.documents_dir / project_id / "business-workspace")
        self.assertEqual(Path(parse_storage["parseDir"]), workspace_parse_dir)
        s1_handoff = project["stageArtifacts"]["s1"]
        self.assertEqual(s1_handoff["schemaVersion"], "business-s1-handoff-v1")
        self.assertEqual(s1_handoff["status"], "published")
        self.assertEqual(s1_handoff["parseProfile"], "business")
        self.assertEqual(Path(s1_handoff["paths"]["structuredResultPath"]), workspace_parse_dir / "s1_structured_result.json")
        self.assertEqual(Path(s1_handoff["paths"]["appendicesDir"]), workspace_appendix_dir)
        self.assertEqual(Path(s1_handoff["paths"]["commitmentLettersDir"]), workspace_commitment_dir)

        structured_result = json.loads((workspace_parse_dir / "s1_structured_result.json").read_text(encoding="utf-8"))
        self.assertEqual(structured_result["schemaVersion"], "bid-business-tender-structured-v1")
        self.assertEqual(structured_result["structured"]["schemaVersion"], "bid-business-tender-structured-v1")
        commitment_letters = structured_result["structured"]["commitmentLetters"]
        self.assertEqual(len(commitment_letters), 1)
        self.assertIn(str(workspace_commitment_dir), commitment_letters[0]["docxPath"])
        self.assertEqual(
            commitment_letters[0]["workspacePath"],
            f"business-workspace/commitment-letters/{Path(commitment_letters[0]['docxPath']).name}",
        )

        preview = self.client.get(
            self.parse_results_url(project_id, f"/commitment-letters/{commitment_letters[0]['id']}/preview")
        )
        self.assertEqual(preview.status_code, 200)
        self.assertIn(str(workspace_commitment_dir), preview.json()["docxPath"])



    def test_delete_project_cleans_parse_temp_workspace(self) -> None:
        project_id = self.create_project()
        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "tenderFiles",
                    (
                        "含附表招标文件.docx",
                        build_appendix_docx_bytes(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
        )
        self.assertEqual(response.status_code, 200)
        temp_project_dir = settings.parsed_dir / project_id
        self.assertTrue(temp_project_dir.exists())

        deleted = self.client.delete(self.project_url(project_id))

        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(temp_project_dir.exists())



    def test_delete_business_project_cleans_project_material_folder(self) -> None:
        project_id = self.create_business_project()
        deleted_calls: list[tuple[str, str]] = []

        def fake_delete_folder(path: str, *, expected_project_id: str = "") -> dict[str, object]:
            deleted_calls.append((path, expected_project_id))
            return {"message": "deleted", "folderPath": path, "deletedFileCount": 2}

        with patch("app.services.bid_project_state.run_workspace_material_folder_delete", side_effect=fake_delete_folder):
            deleted = self.client.delete(self.project_url(project_id))

        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted_calls, [(f"商务标/项目素材/{project_id}", project_id)])



    def test_parse_results_materializes_legacy_required_appendix_preview_docx(self) -> None:
        project_id = self.create_project()
        complete_parse_for_tests(
            project_id,
            [{"id": "TEN-1", "name": "招标文件.docx", "size_label": "1.0 MB"}],
            [],
            summary={"fileCount": 1, "extractedCount": 0, "textLength": 0, "warnings": []},
            parse_storage={
                "items": [],
                "structured": {
                    "appendices": [
                        {
                            "id": "APPX-0007",
                            "title": "附表7：技术资料递交表",
                            "status": "required_no_template",
                            "sourceFile": "招标文件.docx",
                            "evidence": "附表7：技术资料递交表",
                            "evidenceLocation": "L88",
                            "rows": [],
                            "rowCount": 0,
                            "docxPath": "",
                        }
                    ]
                },
            },
        )

        response = self.client.get(self.parse_results_url(project_id))
        self.assertEqual(response.status_code, 200)
        appendix = response.json()["structured"]["appendices"][0]
        self.assertEqual(appendix["status"], "generated")
        self.assertEqual(appendix["rowCount"], 0)
        appendix_path = Path(appendix["docxPath"])
        self.assertTrue(appendix_path.exists())

        preview = self.client.get(self.parse_results_url(project_id, "/appendices/APPX-0007/preview"))
        self.assertEqual(preview.status_code, 200)
        preview_payload = preview.json()
        self.assertEqual(preview_payload["id"], "APPX-0007")
        self.assertEqual(preview_payload["onlyoffice"]["documentType"], "word")
        self.assertTrue(preview_payload["onlyoffice"]["documentKey"])

        file_response = self.client.get(
            self.parse_results_url(project_id, f"/appendices/APPX-0007/file/{appendix_path.name}")
        )
        self.assertEqual(file_response.status_code, 200)
        self.assertGreater(len(file_response.content), 0)



    def test_template_only_reparse_works_after_tender_uploaded(self) -> None:
        project_id = self.create_project()
        tender_bytes = build_docx_bytes("招标文件正文", "项目概况", "这是第一次上传的招标文件。")
        template_bytes = build_docx_bytes("投标模板", "封面", "这是后补上传的模板文件。")

        first_response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "tenderFiles",
                    ("招标文件.docx", tender_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                )
            ],
        )
        self.assertEqual(first_response.status_code, 200)

        second_response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "templateFiles",
                    ("投标模板.docx", template_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                )
            ],
        )

        self.assertEqual(second_response.status_code, 200)
        payload = second_response.json()
        self.assertEqual(payload["summary"]["fileCount"], 1)
        self.assertEqual(len(payload["project"]["templateFiles"]), 1)
        self.assertEqual(payload["project"]["templateFiles"][0]["name"], "投标模板.docx")



    def test_parse_inputs_do_not_use_legacy_template_when_project_has_no_template(self) -> None:
        project_id = self.create_project()
        tender_bytes = build_docx_bytes("招标文件正文", "项目概况", "项目没有单独上传投标模板。")
        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "tenderFiles",
                    ("招标文件.docx", tender_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                )
            ],
        )
        self.assertEqual(response.status_code, 200)

        with patch("app.services.template_store.resolve_system_default_bid_template_file", return_value=None):
            _, template_files = parse_inputs_for_tests(project_id)

        self.assertEqual(template_files, [])



    def test_parse_inputs_use_settings_default_template_when_project_has_no_template(self) -> None:
        project_id = self.create_project()
        tender_bytes = build_docx_bytes("招标文件正文", "项目概况", "项目没有单独上传投标模板。")
        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "tenderFiles",
                    ("招标文件.docx", tender_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                )
            ],
        )
        self.assertEqual(response.status_code, 200)

        default_path = settings.uploads_dir / project_id / "system-default-template" / "默认技术标模板.docx"
        default_path.parent.mkdir(parents=True, exist_ok=True)
        default_path.write_bytes(build_docx_bytes("默认技术标模板", "第一章 模板章节"))
        default_record = {
            "id": "TPL-0001",
            "name": "默认技术标模板.docx",
            "stored_name": "默认技术标模板.docx",
            "size_bytes": default_path.stat().st_size,
            "size_label": format_size_mb(default_path.stat().st_size),
            "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "path": str(default_path),
            "source": "system-default",
            "isFallback": True,
            "templateType": "technical",
            "templateTypeLabel": "技术标",
            "minioBucket": "bid-templates",
            "minioKey": "templates/default/technical/default-template.docx",
        }

        with patch("app.services.template_store.resolve_system_default_bid_template_file", return_value=default_record):
            _, template_files = parse_inputs_for_tests(project_id)

        self.assertEqual(len(template_files), 1)
        self.assertEqual(template_files[0]["name"], "默认技术标模板.docx")
        self.assertEqual(template_files[0]["source"], "system-default")
        self.assertEqual(template_files[0]["templateType"], "technical")



    def test_project_template_overrides_fallback_template(self) -> None:
        project_id = self.create_project()
        tender_bytes = build_docx_bytes("招标文件正文", "项目概况", "项目后续上传自己的投标模板。")
        template_bytes = build_docx_bytes("项目投标模板", "第一章 项目模板章节")
        response = self.client.post(
            self.parse_results_url(project_id, "/upload-and-run"),
            files=[
                (
                    "tenderFiles",
                    ("招标文件.docx", tender_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                ),
                (
                    "templateFiles",
                    ("项目模板.docx", template_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                ),
            ],
        )
        self.assertEqual(response.status_code, 200)

        default_record = {
            "id": "TPL-0001",
            "name": "默认技术标模板.docx",
            "path": "/tmp/default-template.docx",
            "source": "system-default",
            "isFallback": True,
        }
        with patch("app.services.template_store.resolve_system_default_bid_template_file", return_value=default_record):
            _, template_files = parse_inputs_for_tests(project_id)

        self.assertEqual(len(template_files), 1)
        self.assertEqual(template_files[0]["name"], "项目模板.docx")
        self.assertNotEqual(template_files[0].get("source"), "system-default")
