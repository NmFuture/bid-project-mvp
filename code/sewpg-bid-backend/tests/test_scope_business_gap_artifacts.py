import asyncio
import json
from base64 import b64encode
from pathlib import Path
from unittest.mock import patch
from app.services.business_gap_service import business_gap_service
from app.services.bid_runtime_state import now_iso
from app.services.store import store
from app.services.business_gap_fact_table import (
    PROJECT_FACT_TABLE_SCHEMA_VERSION as BUSINESS_FACT_TABLE_SCHEMA_VERSION,
)

from bid_scope_helpers import (
    _DummyRequest,
    _seed_business_gap_project,
)


def test_business_gap_task_state_helpers_stay_in_domain_layer() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "承诺函", "taskIds": ["BTASK-001"], "status": "partial"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "人工上传承诺函",
                    "taskType": "attachment",
                    "sourceType": "manual_user",
                    "decision": "material_required",
                    "status": "needs_input",
                    "moduleKey": "commitments_and_notes",
                    "candidateMaterials": [],
                    "selectedMaterialRefs": [],
                    "resolvedArtifacts": [],
                    "riskFlags": ["missing_material", "manual_upload_required"],
                }
            ],
            "summary": {},
        }
    )

    with patch(
        "app.services.store.store._update_business_gap_toc_ref_statuses",
        side_effect=AssertionError("business_gap_service must use business_gap_domain for toc status updates"),
        create=True,
    ), patch(
        "app.services.store.store._recompute_business_gap_task_after_artifact_change",
        side_effect=AssertionError("business_gap_service must use business_gap_domain for task recompute"),
        create=True,
    ), patch(
        "app.services.store.store._apply_business_task_artifact_intent",
        side_effect=AssertionError("business_gap_service must use business_gap_domain for artifact intent"),
        create=True,
    ), patch(
        "app.services.store.store._finalize_business_gap_plan_update",
        side_effect=AssertionError("business_gap_service must use business_gap_state for plan finalization"),
        create=True,
    ), patch(
        "app.services.store.store._refresh_business_gap_urls_for_result",
        side_effect=AssertionError("business_gap_service must use business_gap_planning URL refresh directly"),
        create=True,
    ):
        manual_payload = business_gap_service.create_manual_task(
            project_id,
            "TOC-1",
            {"title": "本章节补充说明材料"},
        )
        update_payload = business_gap_service.update_task(
            project_id,
            "BTASK-001",
            {"assemblyMode": "template_fill_docx"},
        )
        upload_payload = business_gap_service.upload_artifact(
            project_id,
            "BTASK-001",
            _DummyRequest(),
            {
                "files": [
                    {
                        "name": "补充承诺函.pdf",
                        "mimeType": "application/pdf",
                        "data": "data:application/pdf;base64," + b64encode(b"%PDF-business-domain").decode("ascii"),
                    }
                ]
            },
        )

    assert manual_payload["task"]["id"].startswith("BTASK-MANUAL-")
    assert update_payload["task"]["fillPlan"]["mode"] == "template_fill_docx"
    assert upload_payload["task"]["status"] == "ready"
    assert upload_payload["artifact"]["sourceMode"] == "uploaded_in_business_s3"


def test_business_gap_upload_artifact_stays_in_business_service() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "承诺函", "taskIds": ["BTASK-001"], "status": "partial"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "人工上传承诺函",
                    "taskType": "attachment",
                    "sourceType": "manual_user",
                    "decision": "material_required",
                    "status": "needs_input",
                    "moduleKey": "commitments_and_notes",
                    "candidateMaterials": [],
                    "selectedMaterialRefs": [],
                    "resolvedArtifacts": [],
                    "riskFlags": ["missing_material", "manual_upload_required"],
                }
            ],
            "summary": {},
        }
    )

    with patch(
        "app.services.store.store.upload_business_gap_artifact",
        side_effect=AssertionError("business_gap_service must not delegate artifact upload back to store"),
        create=True,
    ):
        payload = business_gap_service.upload_artifact(
            project_id,
            "BTASK-001",
            _DummyRequest(),
            {
                "files": [
                    {
                        "name": "补充承诺函.pdf",
                        "mimeType": "application/pdf",
                        "data": "data:application/pdf;base64," + b64encode(b"%PDF-business-upload").decode("ascii"),
                    }
                ]
            },
        )

    assert payload["task"]["status"] == "ready"
    assert payload["task"]["handlingMode"] == "manual_upload"
    assert payload["artifact"]["sourceMode"] == "uploaded_in_business_s3"
    assert "business-workspace/gaps/uploads" in Path(payload["artifact"]["filePath"]).as_posix()


def test_business_gap_upload_artifact_files_stays_in_business_service() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "承诺函", "taskIds": ["BTASK-001"], "status": "partial"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "人工上传承诺函",
                    "taskType": "attachment",
                    "sourceType": "manual_user",
                    "decision": "material_required",
                    "status": "needs_input",
                    "moduleKey": "commitments_and_notes",
                    "candidateMaterials": [],
                    "selectedMaterialRefs": [],
                    "resolvedArtifacts": [],
                    "riskFlags": ["missing_material", "manual_upload_required"],
                }
            ],
            "summary": {},
        }
    )

    with patch(
        "app.services.store.store.upload_business_gap_artifact_bytes",
        side_effect=AssertionError("business_gap_service must not delegate artifact file upload back to store"),
        create=True,
    ):
        payload = business_gap_service.upload_artifact_files(
            project_id,
            "BTASK-001",
            _DummyRequest(),
            [{"name": "补充承诺函.docx", "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "rawBytes": b"docx"}],
            operator="测试用户",
        )

    assert payload["task"]["status"] == "ready"
    assert payload["artifact"]["operator"] == "测试用户"
    assert payload["artifact"]["sourceMode"] == "uploaded_in_business_s3"


def test_business_gap_sync_artifact_to_material_stays_in_business_service(tmp_path) -> None:
    artifact_path = tmp_path / "补充承诺函.pdf"
    artifact_path.write_bytes(b"%PDF-business-sync")
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "承诺函", "taskIds": ["BTASK-001"], "status": "ready"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "人工上传承诺函",
                    "taskType": "attachment",
                    "sourceType": "manual_user",
                    "decision": "ready",
                    "status": "ready",
                    "moduleKey": "commitments_and_notes",
                    "candidateMaterials": [],
                    "selectedMaterialRefs": [],
                    "resolvedArtifacts": [
                        {
                            "artifactId": "ART-SYNC",
                            "fileName": artifact_path.name,
                            "filePath": str(artifact_path),
                            "sourceMode": "uploaded_in_business_s3",
                            "materialSyncStatus": "not_synced",
                            "mimeType": "application/pdf",
                        }
                    ],
                    "riskFlags": [],
                }
            ],
            "summary": {},
        }
    )

    async def fake_raw_upload(**kwargs):
        assert "bid_type" not in kwargs
        assert kwargs["target_path"].startswith(f"商务标/项目素材/{project_id}/")
        assert kwargs["material_tier"] == "project"
        return {
            "items": [
                {
                    "id": "RAW-SYNC-001",
                    "name": "补充承诺函.pdf",
                    "folderPath": kwargs["target_path"],
                    "bidType": "商务标",
                    "materialTier": "project",
                    "projectId": project_id,
                }
            ]
        }

    with patch(
        "app.services.store.store.sync_business_gap_artifact_to_material_library",
        side_effect=AssertionError("business_gap_service must not delegate material sync back to store"),
        create=True,
    ), patch(
        "app.services.business_gap_service.business_material_store.raw_upload",
        side_effect=fake_raw_upload,
    ):
        payload = asyncio.run(
            business_gap_service.sync_artifact_to_material(
                project_id,
                "BTASK-001",
                _DummyRequest(),
                {"artifactId": "ART-SYNC"},
            )
        )

    assert payload["artifact"]["materialSyncStatus"] == "synced_to_project_material"
    assert payload["artifact"]["wikiSyncStatus"] == "wiki_rebuild_required"
    assert payload["material"]["bidType"] == "商务标"
    assert payload["wikiRebuildRequired"] is True


def test_business_gap_ai_draft_stays_in_business_service() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "投标函", "taskIds": ["BTASK-001"], "status": "partial"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "投标函",
                    "taskType": "form",
                    "decision": "ai_draft_required",
                    "status": "needs_input",
                    "assigneeMode": "ai_draft",
                    "moduleKey": "base_documents_guarantees",
                    "assemblyMode": "ai_draft",
                    "candidateMaterials": [],
                    "selectedMaterialRefs": [],
                    "resolvedArtifacts": [],
                    "riskFlags": ["ai_draft_required"],
                }
            ],
            "summary": {},
        }
    )
    record = store._require(project_id)
    record["business_gap_state"]["projectFactTable"] = {
        "schemaVersion": BUSINESS_FACT_TABLE_SCHEMA_VERSION,
        "projectId": project_id,
        "status": "confirmed",
        "builtAt": now_iso(),
        "updatedAt": now_iso(),
        "fields": [
            {"label": "项目名称", "value": "商务标服务拆分测试项目", "status": "confirmed"},
            {"label": "招标编号", "value": "BIZ-001", "status": "confirmed"},
            {"label": "投标人", "value": "测试投标单位", "status": "confirmed"},
        ],
        "summary": {"totalCount": 3, "confirmedCount": 3},
    }
    store._persist_project(record)

    with patch(
        "app.services.store.store.run_business_gap_ai_draft",
        side_effect=AssertionError("business_gap_service must not delegate AI draft back to store"),
        create=True,
    ), patch(
        "app.services.store.store._fact_table_value_map",
        side_effect=AssertionError("business_gap_service must use business_gap_fact_table for fact value maps"),
        create=True,
    ), patch(
        "app.services.store.store._write_business_ai_draft_docx",
        side_effect=AssertionError("business_gap_service must use business_gap_ai_draft for docx generation"),
        create=True,
    ):
        payload = asyncio.run(
            business_gap_service.ai_draft(
                project_id,
                "BTASK-001",
                _DummyRequest(),
                {"operator": "测试用户"},
            )
        )

    assert payload["task"]["status"] == "review_required"
    assert payload["artifact"]["sourceMode"] == "generated_by_business_s3_ai_draft"
    assert payload["artifact"]["operator"] == "测试用户"
    assert payload["artifact"]["factTableStatus"] == "confirmed"


def test_business_gap_table_fill_stays_in_business_service(tmp_path) -> None:
    target_path = tmp_path / "投标函模板.docx"
    target_path.write_bytes(b"fake-docx-template")
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "投标函", "taskIds": ["BTASK-001"], "status": "partial"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "投标函",
                    "taskType": "table",
                    "decision": "fill_required",
                    "status": "needs_input",
                    "moduleKey": "structured_response_tables",
                    "assemblyMode": "template_fill_docx",
                    "materialUsage": "fill_table",
                    "templateCandidates": [
                        {
                            "templateId": "TPL-001",
                            "templateName": "投标函模板.docx",
                            "fileName": target_path.name,
                            "filePath": str(target_path),
                            "assemblyMode": "template_fill_docx",
                            "materialUsage": "fill_table",
                            "sourceMode": "project_uploaded_bid_template",
                        }
                    ],
                    "candidateMaterials": [],
                    "selectedMaterialRefs": [],
                    "resolvedArtifacts": [],
                    "riskFlags": ["missing_material"],
                }
            ],
            "summary": {},
        }
    )
    record = store._require(project_id)
    record["business_gap_state"]["projectFactTable"] = {
        "schemaVersion": BUSINESS_FACT_TABLE_SCHEMA_VERSION,
        "projectId": project_id,
        "status": "confirmed",
        "builtAt": now_iso(),
        "updatedAt": now_iso(),
        "fields": [{"label": "项目名称", "value": "商务标服务拆分测试项目", "status": "confirmed"}],
        "summary": {"totalCount": 1, "confirmedCount": 1},
    }
    store._persist_project(record)

    def fake_runner(manifest_path: Path) -> dict[str, object]:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        assert manifest["target"]["templateId"] == "TPL-001"
        output_path = Path(manifest["outputFile"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"filled-docx")
        return {
            "schemaVersion": "bid-business-table-fill-v1",
            "outputFile": str(output_path),
            "fillReport": {"filledFieldCount": 1},
            "unfilledFields": [],
            "evidenceRefs": [],
        }

    with patch(
        "app.services.store.store.run_business_gap_table_fill",
        side_effect=AssertionError("business_gap_service must not delegate table fill back to store"),
        create=True,
    ), patch(
        "app.services.store.store._fact_table_value_map",
        side_effect=AssertionError("business_gap_service must use business_gap_fact_table for fact value maps"),
        create=True,
    ), patch(
        "app.services.store.store._business_table_fill_source_materials",
        side_effect=AssertionError("business_gap_service must use business_gap_table_fill for source materials"),
        create=True,
    ), patch(
        "app.services.store.store._prepare_business_table_fill_target",
        side_effect=AssertionError("business_gap_service must use business_gap_table_fill for target prep"),
        create=True,
    ), patch(
        "app.services.store.store._prepare_business_table_fill_sources",
        side_effect=AssertionError("business_gap_service must use business_gap_table_fill for source prep"),
        create=True,
    ), patch(
        "app.services.business_gap_service.run_business_table_fill_skill",
        side_effect=fake_runner,
    ):
        payload = asyncio.run(
            business_gap_service.table_fill(
                project_id,
                "BTASK-001",
                _DummyRequest(),
                {"target": {"templateId": "TPL-001"}, "operator": "测试用户"},
            )
        )

    assert payload["task"]["status"] == "review_required"
    assert payload["task"]["handlingMode"] == "ai_table_fill"
    assert payload["artifact"]["sourceMode"] == "generated_by_business_table_fill"
    assert payload["artifact"]["operator"] == "测试用户"


def test_business_table_fill_source_prep_uses_business_material_store(tmp_path) -> None:
    from app.services.business_gap_table_fill import prepare_business_table_fill_sources

    async def fake_cleaned_download(material_id: str) -> dict[str, object]:
        assert material_id == "BMAT-001"
        return {
            "bucket": "bucket",
            "key": "business/BMAT-001.docx",
            "fileName": "商务素材.docx",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }

    def fake_download_file(bucket: str, key: str, target_path: Path) -> None:
        assert bucket == "bucket"
        assert key == "business/BMAT-001.docx"
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(b"business-material")

    with patch(
        "app.services.business_gap_table_fill.business_material_store.raw_download_cleaned_content",
        side_effect=fake_cleaned_download,
    ), patch(
        "app.services.business_gap_table_fill.minio_client.download_file",
        side_effect=fake_download_file,
    ):
        prepared = prepare_business_table_fill_sources(
            [{"id": "BMAT-001", "materialName": "商务素材.docx"}],
            tmp_path,
        )

    assert prepared[0]["sourceKind"] == "cleaned"
    assert Path(prepared[0]["path"]).exists()


def test_business_gap_create_manual_task_stays_in_business_service() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "number": "1.1", "title": "补充说明", "taskIds": [], "status": "empty"}],
            "tasks": [],
            "summary": {},
        }
    )

    with patch(
        "app.services.store.store.create_business_gap_manual_task",
        side_effect=AssertionError("business_gap_service must not delegate manual task creation back to store"),
        create=True,
    ):
        payload = business_gap_service.create_manual_task(project_id, "TOC-1", {"title": "本章节补充说明材料"})

    assert payload["task"]["sourceType"] == "manual_user"
    assert payload["task"]["tocTarget"]["nodeId"] == "TOC-1"
    assert payload["task"]["status"] == "needs_input"
    assert payload["task"]["id"] in payload["plan"]["tocRefs"][0]["taskIds"]


def test_business_gap_confirm_artifact_stays_in_business_service() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "承诺函", "taskIds": ["BTASK-001"], "status": "review_required"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "待确认承诺函",
                    "taskType": "attachment",
                    "decision": "review_required",
                    "status": "review_required",
                    "moduleKey": "commitments_and_notes",
                    "candidateMaterials": [],
                    "resolvedArtifacts": [
                        {
                            "artifactId": "ART-001",
                            "fileName": "承诺函.docx",
                            "confirmed": False,
                            "reviewStatus": "pending_review",
                        }
                    ],
                    "riskFlags": ["missing_material", "parser_generated_unconfirmed"],
                }
            ],
            "summary": {},
        }
    )

    with patch(
        "app.services.store.store.confirm_business_gap_artifact",
        side_effect=AssertionError("business_gap_service must not delegate artifact confirmation back to store"),
        create=True,
    ):
        payload = business_gap_service.confirm_artifact(project_id, "BTASK-001", {"artifactId": "ART-001"})

    assert payload["task"]["status"] == "ready"
    assert payload["artifact"]["confirmed"] is True
    assert payload["artifact"]["reviewStatus"] == "approved"
    assert "missing_material" not in payload["task"]["riskFlags"]


def test_business_gap_remove_artifact_stays_in_business_service(tmp_path) -> None:
    artifact_path = tmp_path / "补料.pdf"
    artifact_path.write_bytes(b"%PDF-manual-upload")
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "承诺函", "taskIds": ["BTASK-001"], "status": "ready"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "人工补料",
                    "taskType": "attachment",
                    "sourceType": "manual_user",
                    "decision": "ready",
                    "status": "ready",
                    "moduleKey": "commitments_and_notes",
                    "candidateMaterials": [],
                    "selectedMaterialRefs": [{"materialId": "RAW-BIZ-001"}],
                    "resolvedArtifacts": [
                        {
                            "artifactId": "ART-REMOVE",
                            "fileName": artifact_path.name,
                            "filePath": str(artifact_path),
                            "sourceMode": "selected_from_business_material_library",
                            "materialId": "RAW-BIZ-001",
                            "materialSyncStatus": "not_synced",
                            "confirmed": True,
                        }
                    ],
                    "riskFlags": [],
                }
            ],
            "summary": {},
        }
    )

    with patch(
        "app.services.store.store.remove_business_gap_artifact",
        side_effect=AssertionError("business_gap_service must not delegate artifact removal back to store"),
        create=True,
    ), patch(
        "app.services.store.store._refresh_business_gap_urls_for_result",
        side_effect=AssertionError("business_gap_service must use business_gap_planning URL refresh directly"),
        create=True,
    ):
        payload = business_gap_service.remove_artifact(project_id, "BTASK-001", "ART-REMOVE", _DummyRequest())

    assert payload["artifact"]["artifactId"] == "ART-REMOVE"
    assert payload["task"]["resolvedArtifacts"] == []
    assert payload["task"]["selectedMaterialRefs"] == []
    assert not artifact_path.exists()


def test_business_gap_select_material_stays_in_business_service() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "资质文件", "taskIds": ["BTASK-001"], "status": "partial"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "资质证书",
                    "taskType": "certificate",
                    "decision": "material_required",
                    "status": "needs_input",
                    "moduleKey": "qualification_compliance_certificates",
                    "candidateMaterials": [],
                    "selectedMaterialRefs": [],
                    "resolvedArtifacts": [],
                    "riskFlags": ["missing_material"],
                }
            ],
            "summary": {},
        }
    )

    async def fake_download_content(material_id: str) -> dict[str, str]:
        return {
            "fileId": material_id,
            "fileName": "商务资质证书.pdf",
            "bucket": "mock-bucket",
            "key": "mock-key",
            "mimeType": "application/pdf",
        }

    def fake_download_file(bucket: str, key: str, target_path) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(b"%PDF-business-material")

    with patch(
        "app.services.store.store.select_business_gap_material",
        side_effect=AssertionError("business_gap_service must not delegate material selection back to store"),
        create=True,
    ), patch(
        "app.services.store.store._record_business_material_feedback",
        side_effect=AssertionError("business_gap_service must use business_gap_state for material feedback"),
        create=True,
    ), patch(
        "app.services.business_gap_service.business_material_store.raw_download_cleaned_content",
        side_effect=RuntimeError("no cleaned content in this test"),
    ), patch(
        "app.services.business_gap_service.business_material_store.raw_download_content",
        side_effect=fake_download_content,
    ), patch(
        "app.services.business_gap_service.minio_client.download_file",
        side_effect=fake_download_file,
    ):
        payload = asyncio.run(
            business_gap_service.select_material(
                project_id,
                "BTASK-001",
                _DummyRequest(),
                {
                    "materials": [
                        {
                            "materialId": "RAW-BIZ-001",
                            "materialName": "商务资质证书.pdf",
                            "folderPath": "商务标/通用素材/资质合规库",
                            "materialTier": "standard",
                            "businessMaterialKind": "fixed",
                            "businessMaterialKindLabel": "固定素材",
                        }
                    ]
                },
            )
        )

    assert payload["task"]["status"] == "ready"
    assert payload["task"]["handlingMode"] == "fixed_material"
    assert payload["selectedMaterialRefs"][0]["materialId"] == "RAW-BIZ-001"
    assert payload["artifact"]["sourceMode"] == "selected_from_business_material_library"
    assert payload["artifact"]["businessMaterialKind"] == "fixed"
    feedback = store._require(project_id)["business_gap_state"]["materialFeedback"]
    assert feedback[0]["materialId"] == "RAW-BIZ-001"


def test_business_gap_select_performance_package_uses_performance_service() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "业绩情况表", "taskIds": ["BTASK-001"], "status": "partial"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "近年类似项目业绩表",
                    "taskType": "performance",
                    "decision": "material_required",
                    "status": "needs_input",
                    "moduleKey": "performance_cooperation_support",
                    "candidateMaterials": [],
                    "selectedMaterialRefs": [],
                    "resolvedArtifacts": [],
                    "riskFlags": ["missing_material"],
                }
            ],
            "summary": {},
        }
    )

    async def fake_download_item_attachment(category_id: str, item_id: str, attachment_id: str) -> dict[str, str]:
        assert category_id == "PERCAT-0011"
        assert item_id == "PERITEM-0268"
        assert attachment_id == "PERITEMATT-0118"
        return {
            "fileName": "001-华电新疆喀什_合同.docx",
            "bucket": "mock-bucket",
            "key": "performance-categories/PERCAT-0011/item-contracts/PERITEM-0268/doc.docx",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }

    def fake_download_file(bucket: str, key: str, target_path) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(b"performance-package-docx")

    with patch(
        "app.services.performance_material_resolver.performance_package_service.download_item_attachment",
        side_effect=fake_download_item_attachment,
    ), patch(
        "app.services.business_gap_service.business_material_store.raw_download_cleaned_content",
        side_effect=AssertionError("performance package must not use raw cleaned material downloads"),
    ), patch(
        "app.services.business_gap_service.business_material_store.raw_download_content",
        side_effect=AssertionError("performance package must not use raw material downloads"),
    ), patch(
        "app.services.business_gap_service.minio_client.download_file",
        side_effect=fake_download_file,
    ):
        payload = asyncio.run(
            business_gap_service.select_material(
                project_id,
                "BTASK-001",
                _DummyRequest(),
                {
                    "materials": [
                        {
                            "materialId": "PERITEM-0268",
                            "categoryId": "PERCAT-0011",
                            "materialName": "华电新疆喀什 2x66 万千瓦",
                            "folderPath": "业绩库/陆上6MW业绩",
                            "materialTier": "standard",
                            "businessMaterialKind": "performance",
                            "businessMaterialKindLabel": "共用业绩",
                            "sourceType": "performance_package",
                            "candidateType": "performance_item",
                            "attachments": [
                                {
                                    "id": "PERITEMATT-0118",
                                    "categoryId": "PERCAT-0011",
                                    "itemId": "PERITEM-0268",
                                    "attachmentType": "contract_item",
                                    "fileName": "001-华电新疆喀什_合同.docx",
                                }
                            ],
                        }
                    ]
                },
            )
        )

    assert payload["task"]["status"] == "ready"
    assert payload["selectedMaterialRefs"][0]["sourceType"] == "performance_package"
    assert payload["artifact"]["materialSourceType"] == "performance_package"
    assert payload["artifact"]["sourceKind"] == "performance_package_item"
    assert payload["artifact"]["sourceType"] == "performance_package"
    assert "华电新疆喀什_合同" in payload["artifact"]["fileName"]
    assert payload["artifact"]["fileName"].endswith(".docx")


def test_business_gap_select_non_fixed_material_counts_as_manual_supplement() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "资质文件", "taskIds": ["BTASK-001"], "status": "partial"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "资质证书",
                    "taskType": "certificate",
                    "decision": "material_required",
                    "status": "needs_input",
                    "moduleKey": "qualification_compliance_certificates",
                    "candidateMaterials": [],
                    "selectedMaterialRefs": [],
                    "resolvedArtifacts": [],
                    "riskFlags": ["missing_material"],
                }
            ],
            "summary": {},
        }
    )

    async def fake_download_content(material_id: str) -> dict[str, str]:
        return {
            "fileId": material_id,
            "fileName": "商务补充材料.pdf",
            "bucket": "mock-bucket",
            "key": "mock-key",
            "mimeType": "application/pdf",
        }

    def fake_download_file(bucket: str, key: str, target_path) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(b"%PDF-business-material")

    with patch(
        "app.services.business_gap_service.business_material_store.raw_download_cleaned_content",
        side_effect=RuntimeError("no cleaned content in this test"),
    ), patch(
        "app.services.business_gap_service.business_material_store.raw_download_content",
        side_effect=fake_download_content,
    ), patch(
        "app.services.business_gap_service.minio_client.download_file",
        side_effect=fake_download_file,
    ):
        payload = asyncio.run(
            business_gap_service.select_material(
                project_id,
                "BTASK-001",
                _DummyRequest(),
                {
                    "materials": [
                        {
                            "materialId": "RAW-BIZ-OTHER",
                            "materialName": "商务补充材料.pdf",
                            "folderPath": "商务标/通用素材/其他材料",
                            "materialTier": "standard",
                            "businessMaterialKind": "other",
                            "businessMaterialKindLabel": "其他",
                            "handlingMode": "manual_select",
                        }
                    ],
                    "handlingMode": "manual_select",
                },
            )
        )

    assert payload["task"]["status"] == "ready"
    assert payload["task"]["handlingMode"] == "manual_upload"
    assert payload["artifact"]["sourceMode"] == "selected_from_business_material_library"
    assert payload["artifact"]["businessMaterialKind"] == "other"


def test_business_gap_select_template_stays_in_business_service(tmp_path) -> None:
    template_path = tmp_path / "投标函模板.docx"
    template_path.write_bytes(b"fake-docx-template")
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "投标函", "taskIds": ["BTASK-001"], "status": "partial"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "投标函",
                    "taskType": "form",
                    "decision": "fill_required",
                    "status": "needs_input",
                    "moduleKey": "base_documents_guarantees",
                    "assemblyMode": "template_fill_docx",
                    "candidateMaterials": [],
                    "templateCandidates": [
                        {
                            "templateId": "TPL-001",
                            "templateName": "投标函模板.docx",
                            "filePath": str(template_path),
                            "sourceMode": "project_uploaded_bid_template",
                        }
                    ],
                    "resolvedArtifacts": [],
                    "riskFlags": ["template_missing_for_fill"],
                }
            ],
            "summary": {},
        }
    )

    with patch(
        "app.services.store.store.select_business_gap_template",
        side_effect=AssertionError("business_gap_service must not delegate template selection back to store"),
        create=True,
    ):
        payload = business_gap_service.select_template(
            project_id,
            "BTASK-001",
            _DummyRequest(),
            {"template": {"templateId": "TPL-001"}},
        )

    assert payload["task"]["status"] == "ready"
    assert payload["artifact"]["templateId"] == "TPL-001"
    assert payload["artifact"]["sourceMode"] == "project_uploaded_bid_template"
    assert "business-workspace/gaps/selected-templates" in Path(payload["artifact"]["filePath"]).as_posix()


def test_business_gap_artifact_lookup_stays_in_business_service() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "承诺函", "taskIds": ["BTASK-001"], "status": "ready"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "承诺函",
                    "taskType": "attachment",
                    "decision": "ready",
                    "status": "ready",
                    "moduleKey": "commitments_and_notes",
                    "candidateMaterials": [],
                    "resolvedArtifacts": [
                        {
                            "artifactId": "ART-LOOKUP",
                            "fileName": "承诺函.docx",
                            "filePath": "/tmp/承诺函.docx",
                            "sourceMode": "uploaded_in_business_s3",
                        }
                    ],
                    "riskFlags": [],
                }
            ],
            "summary": {},
        }
    )

    with patch(
        "app.services.store.store.get_business_gap_artifact",
        side_effect=AssertionError("business_gap_service must not delegate artifact lookup back to store"),
        create=True,
    ):
        payload = business_gap_service.artifact(project_id, "ART-LOOKUP")

    assert payload["artifactId"] == "ART-LOOKUP"
    assert payload["sourceMode"] == "uploaded_in_business_s3"
