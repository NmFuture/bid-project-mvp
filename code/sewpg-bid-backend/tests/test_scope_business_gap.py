import asyncio
from unittest.mock import patch
from app.services.business_gap_repository import persist_business_gap_project
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


def test_business_gap_selectable_materials_stays_in_business_service() -> None:
    project = {
        "id": "PRJ-BIZ-SCOPE",
        "bidType": "商务标",
        "business_gap_state": {"recognitionStatus": "completed"},
    }
    picker = {
        "templateIndex": [],
        "materialIndex": [
            {
                "id": "RAW-BIZ-0001",
                "name": "商务资质证书.pdf",
                "folderPath": "商务标/通用素材/资质合规库",
                "materialTier": "standard",
            }
        ],
        "evidenceSegments": [],
        "materialScope": {"paths": ["商务标/通用素材"]},
    }

    with patch("app.services.workspace_project_access.store.get_project_runtime_state", return_value=project), patch(
        "app.services.store.store._ensure_business_gap_state",
        side_effect=AssertionError("business_gap_service must use business_gap_state.ensure_business_gap_state"),
        create=True,
    ), patch(
        "app.services.business_gap_service.build_business_gap_material_picker_index",
        return_value=picker,
    ), patch(
        "app.services.store.store.list_business_gap_selectable_materials",
        side_effect=AssertionError("business_gap_service must not delegate selectable materials back to store"),
        create=True,
    ):
        payload = business_gap_service.selectable_materials("PRJ-BIZ-SCOPE", keyword="资质")

    assert payload["bidType"] == "商务标"
    assert payload["items"][0]["materialId"] == "RAW-BIZ-0001"


def test_business_gap_payload_stays_in_business_service() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "承诺函", "taskIds": ["BTASK-001"], "status": "partial"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "承诺函",
                    "taskType": "attachment",
                    "decision": "material_required",
                    "status": "needs_input",
                    "moduleKey": "commitments_and_notes",
                    "candidateMaterials": [],
                    "resolvedArtifacts": [],
                    "riskFlags": ["missing_material"],
                }
            ],
            "summary": {},
        }
    )

    with patch(
        "app.services.store.store.get_business_gap_filling",
        side_effect=AssertionError("business_gap_service must not delegate gap payload back to store"),
        create=True,
    ), patch(
        "app.services.store.store._refresh_business_gap_template_candidates",
        side_effect=AssertionError("business_gap_service must use business_gap_refresh for template refresh"),
        create=True,
    ), patch(
        "app.services.store.store._refresh_business_gap_material_kind_labels",
        side_effect=AssertionError("business_gap_service must use business_gap_refresh for material kind refresh"),
        create=True,
    ):
        payload = business_gap_service.gaps(project_id, _DummyRequest())

    assert payload["status"] == "completed"
    assert payload["source"]["bidType"] == "商务标"
    assert payload["tasks"][0]["id"] == "BTASK-001"


def test_business_gap_run_detection_stays_in_business_service() -> None:
    store.reset_for_tests()
    project = store.create_project({"name": "商务标缺口识别测试项目", "customerName": "测试业主", "bidType": "商务标"})
    project_id = project["id"]
    record = store._require(project_id)
    record["outline_state"]["reviewStatus"] = "confirmed"
    store._persist_project(record)
    built_plan = {
        "schemaVersion": "bid-business-gap-plan-v1",
        "tocRefs": [{"nodeId": "TOC-1", "title": "投标函", "taskIds": ["BTASK-001"], "status": "partial"}],
        "tasks": [
            {
                "id": "BTASK-001",
                "title": "投标函",
                "status": "needs_input",
                "decision": "material_required",
            }
        ],
        "moduleGroups": [],
        "planFile": "/tmp/business_gap_plan.json",
    }

    with patch(
        "app.services.store.store.run_business_gap_detection",
        side_effect=AssertionError("business_gap_service must not delegate detection back to store"),
        create=True,
    ), patch(
        "app.services.business_gap_service.build_business_gap_plan_for_project",
        return_value=built_plan,
    ), patch(
        "app.services.business_gap_service.persist_business_gap_project",
        wraps=persist_business_gap_project,
    ) as persist_project:
        payload = business_gap_service.run_detection(project_id)

    assert payload["status"] == "completed"
    assert payload["summary"]["taskCount"] == 1
    assert payload["plan"]["integrity"]["status"] == "blocked"
    assert payload["message"] == "商务标缺口计划生成完成，共 1 个任务。"
    persist_project.assert_called_once()
    stored_state = store._require(project_id)["business_gap_state"]
    assert stored_state["recognitionStatus"] == "completed"
    assert stored_state["planFile"] == "/tmp/business_gap_plan.json"
    assert store._require(project_id)["gap_state"]["recognitionStatus"] == "idle"


def test_business_gap_save_facts_allows_user_add_and_delete_fields() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [],
            "tasks": [],
            "summary": {},
        }
    )
    record = store._require(project_id)
    record["business_gap_state"]["projectFactTable"] = {
        "schemaVersion": BUSINESS_FACT_TABLE_SCHEMA_VERSION,
        "projectId": project_id,
        "status": "draft",
        "builtAt": now_iso(),
        "updatedAt": now_iso(),
        "fields": [
            {"label": "招标项目名称", "value": "", "status": "missing"},
            {"label": "招标编号", "value": "", "status": "missing"},
        ],
        "summary": {"totalCount": 2},
    }
    store._persist_project(record)

    payload = asyncio.run(
        business_gap_service.save_facts(
            project_id,
            {
                "fields": [
                    {"label": "项目名称", "value": "商务标服务拆分测试项目"},
                    {"label": "投标人", "value": "测试投标单位"},
                    {"label": "自定义联系人", "value": "张三"},
                ],
                "confirm": False,
                "operator": "测试用户",
            },
        )
    )

    labels = {field["label"]: field for field in payload["fields"]}
    assert len(payload["fields"]) == 3
    assert payload["fields"][0]["label"] == "招标项目名称"
    assert labels["招标项目名称"]["value"] == "商务标服务拆分测试项目"
    assert labels["投标人"]["value"] == "测试投标单位"
    assert labels["自定义联系人"]["category"] == "人工补充事实"
    assert labels["自定义联系人"]["sourceMode"] == "manual"
    assert "招标编号" not in labels
    assert "项目名称" not in labels


def test_business_gap_save_facts_persists_fixed_fields_to_bidder_profile() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [],
            "tasks": [],
            "summary": {},
        }
    )
    captured: dict[str, object] = {}

    async def fake_store(values, *, updated_by=""):
        captured["values"] = dict(values)
        captured["updated_by"] = updated_by
        return dict(values)

    with patch("app.services.business_gap_service.store_business_bidder_facts", side_effect=fake_store):
        asyncio.run(
            business_gap_service.save_facts(
                project_id,
                {
                    "fields": [
                        {"label": "投标人地址", "value": "上海市闵行区东川路555号"},
                        {"label": "招标项目名称", "value": "某风电项目"},
                        {"label": "自定义联系人", "value": "张三"},
                    ],
                    "confirm": False,
                    "operator": "测试用户",
                },
            )
        )

    assert captured["values"] == {"投标人地址": "上海市闵行区东川路555号"}
    assert captured["updated_by"] == "测试用户"


def test_drop_unconfirmed_generated_artifacts_supersedes_same_target() -> None:
    from app.services.business_gap_service import _drop_unconfirmed_generated_artifacts

    task = {
        "resolvedArtifacts": [
            {"artifactType": "parse_appendix_template", "confirmed": True, "fileName": "APPX-0001.docx"},
            {
                "artifactType": "business_table_fill",
                "confirmed": False,
                "fileName": "投标函-AI填写.docx",
                "target": {"fileName": "投标函.docx"},
            },
            {
                "artifactType": "business_table_fill",
                "confirmed": True,
                "fileName": "投标函-AI填写-旧确认.docx",
                "target": {"fileName": "投标函.docx"},
            },
            {
                "artifactType": "business_table_fill",
                "confirmed": False,
                "fileName": "其他表-AI填写.docx",
                "target": {"fileName": "其他表.docx"},
            },
        ]
    }
    _drop_unconfirmed_generated_artifacts(task, artifact_type="business_table_fill", target_file_name="投标函.docx")
    names = [item["fileName"] for item in task["resolvedArtifacts"]]
    # 同目标未确认的被替换；已确认的与其他目标的保留
    assert "投标函-AI填写.docx" not in names
    assert "投标函-AI填写-旧确认.docx" in names
    assert "其他表-AI填写.docx" in names
    assert "APPX-0001.docx" in names


def test_confirm_generated_artifact_converges_task_to_single_output() -> None:
    from app.services.business_gap_service import (
        _converge_task_to_final_artifact,
        _restore_task_reference_artifacts,
    )

    final = {"artifactId": "BART-1-TBL-2", "artifactType": "business_table_fill", "sourceMode": "generated_by_business_table_fill", "confirmed": True}
    task = {
        "resolvedArtifacts": [
            {"artifactId": "APPX-0001", "artifactType": "parse_appendix_template", "sourceMode": "parsed_from_tender_attachment_template", "confirmed": True},
            {"artifactId": "SEL-1", "artifactType": "selected_material", "sourceMode": "selected_from_business_material_library", "materialUsage": "fill_template", "confirmed": True},
            {"artifactId": "BART-1-TBL-1", "artifactType": "business_table_fill", "sourceMode": "generated_by_business_table_fill", "confirmed": False},
            final,
            {"artifactId": "UP-1", "artifactType": "manual_supplement", "sourceMode": "uploaded_in_business_s3", "confirmed": True},
        ]
    }

    _converge_task_to_final_artifact(task, final)
    resolved_ids = [item["artifactId"] for item in task["resolvedArtifacts"]]
    reference_ids = [item["artifactId"] for item in task["referenceArtifacts"]]
    # 终局产物 + 人工上传留在装配列表；底稿与填写参考素材挪入过程参考；旧生成产物删除
    assert resolved_ids == ["BART-1-TBL-2", "UP-1"]
    assert set(reference_ids) == {"APPX-0001", "SEL-1"}
    assert task["finalArtifactId"] == "BART-1-TBL-2"

    _restore_task_reference_artifacts(task)
    restored_ids = {item["artifactId"] for item in task["resolvedArtifacts"]}
    assert {"BART-1-TBL-2", "UP-1", "APPX-0001", "SEL-1"} <= restored_ids
    assert task["referenceArtifacts"] == []
    assert task["finalArtifactId"] == ""


def test_business_gap_save_facts_stays_in_business_service() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [],
            "tasks": [],
            "summary": {},
        }
    )
    record = store._require(project_id)
    record["business_gap_state"]["projectFactTable"] = {
        "schemaVersion": BUSINESS_FACT_TABLE_SCHEMA_VERSION,
        "projectId": project_id,
        "status": "draft",
        "builtAt": now_iso(),
        "updatedAt": now_iso(),
        "fields": [],
        "summary": {"totalCount": 0},
    }
    store._persist_project(record)

    with patch(
        "app.services.store.store.save_business_gap_fact_table",
        side_effect=AssertionError("business_gap_service must not delegate fact save back to store"),
        create=True,
    ), patch(
        "app.services.store.store._normalize_project_fact_field",
        side_effect=AssertionError("business_gap_service must use business_gap_fact_table for fact normalization"),
        create=True,
    ), patch(
        "app.services.store.store._summarize_project_fact_fields",
        side_effect=AssertionError("business_gap_service must use business_gap_fact_table for fact summaries"),
        create=True,
    ):
        payload = asyncio.run(
            business_gap_service.save_facts(
                project_id,
                {
                    "fields": [
                        {
                            "label": "投标人",
                            "value": "测试投标单位",
                            "required": True,
                            "confidence": 0.9,
                        }
                    ],
                    "confirm": True,
                    "operator": "测试用户",
                },
            )
        )

    assert payload["status"] == "confirmed"
    assert payload["confirmedBy"] == "测试用户"
    labels = {field["label"]: field for field in payload["fields"]}
    assert len(payload["fields"]) == 1
    assert labels["投标人"]["status"] == "confirmed"
    assert labels["投标人"]["value"] == "测试投标单位"
    assert store._require(project_id)["business_gap_state"]["projectFactTable"]["status"] == "confirmed"


def test_business_gap_update_task_stays_in_business_service() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [{"nodeId": "TOC-1", "title": "承诺函", "taskIds": ["BTASK-001"], "status": "partial"}],
            "tasks": [
                {
                    "id": "BTASK-001",
                    "title": "可忽略事项",
                    "taskType": "attachment",
                    "decision": "review_required",
                    "status": "review_required",
                    "moduleKey": "commitments_and_notes",
                    "candidateMaterials": [],
                    "resolvedArtifacts": [],
                    "riskFlags": [],
                }
            ],
            "summary": {},
        }
    )

    with patch(
        "app.services.store.store.update_business_gap_task",
        side_effect=AssertionError("business_gap_service must not delegate task updates back to store"),
        create=True,
    ):
        payload = business_gap_service.update_task(project_id, "BTASK-001", {"status": "ignored", "notes": "无需响应"})

    assert payload["task"]["status"] == "ignored"
    assert payload["task"]["handlingMode"] == "ignored"
    assert payload["plan"]["tocRefs"][0]["status"] == "ready"


def test_business_gap_update_task_template_refresh_stays_in_refresh_helper() -> None:
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
                    "candidateMaterials": [],
                    "resolvedArtifacts": [],
                    "riskFlags": ["missing_material"],
                }
            ],
            "summary": {},
        }
    )

    with patch(
        "app.services.store.store.update_business_gap_task",
        side_effect=AssertionError("business_gap_service must not delegate task updates back to store"),
        create=True,
    ), patch(
        "app.services.store.store._refresh_business_gap_template_candidates",
        side_effect=AssertionError("business_gap_service must use business_gap_refresh for template refresh"),
        create=True,
    ), patch(
        "app.services.business_gap_service.refresh_template_candidates",
        return_value=True,
    ) as refresh:
        payload = business_gap_service.update_task(project_id, "BTASK-001", {"assemblyMode": "template_fill_docx"})

    refresh.assert_called_once()
    assert payload["task"]["assemblyMode"] == "template_fill_docx"


def test_business_gap_refresh_material_kind_labels_updates_task_records() -> None:
    from app.services.business_gap_refresh import refresh_material_kind_labels

    project = {"id": "PRJ-BIZ-REFRESH", "name": "商务刷新测试", "bidType": "商务标"}
    state = {
        "plan": {
            "tasks": [
                {
                    "id": "BTASK-001",
                    "handlingMode": "manual_select",
                    "candidateMaterials": [{"materialId": "BMAT-001"}],
                    "selectedMaterialRefs": [{"materialId": "BMAT-001"}],
                    "resolvedArtifacts": [{"materialId": "BMAT-001"}],
                }
            ]
        }
    }

    with patch(
        "app.services.business_gap_refresh.build_business_gap_material_picker_index",
        return_value={
            "materialIndex": [
                {
                    "id": "BMAT-001",
                    "businessMaterialKind": "fixed",
                    "businessMaterialKindLabel": "固定素材",
                }
            ]
        },
    ):
        changed = refresh_material_kind_labels(project, state)

    task = state["plan"]["tasks"][0]
    assert changed is True
    assert task["candidateMaterials"][0]["businessMaterialKind"] == "fixed"
    assert task["selectedMaterialRefs"][0]["businessMaterialKindLabel"] == "固定素材"
    assert task["resolvedArtifacts"][0]["businessMaterialKind"] == "fixed"
    assert task["handlingMode"] == "fixed_material"
