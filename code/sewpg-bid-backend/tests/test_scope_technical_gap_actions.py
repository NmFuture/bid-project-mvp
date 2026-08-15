import asyncio
import json
from pathlib import Path
from unittest.mock import patch
import pytest
import app.services.technical_gap_actions as technical_gap_actions_module
import app.services.technical_gap_ai_fill as technical_gap_ai_fill_module
from app.services.bid_runtime_state import now_iso
from app.services.store import store
from app.services.technical_gap_fact_table import PROJECT_FACT_TABLE_SCHEMA_VERSION
from app.services.technical_gap_domain import technical_gap_artifact_is_s7_ready
from app.services.technical_gap_repository import (
    mutate_technical_gap_project,
    require_technical_gap_project_for_update,
)
from app.services.technical_gap_service import technical_gap_service

from bid_scope_helpers import (
    _DummyRequest,
    _seed_technical_gap_project,
)


def test_technical_manual_upload_action_stays_in_technical_actions(tmp_path) -> None:
    project_id = _seed_technical_gap_project(
        {
            "items": [
                {
                    "id": "TG-UPLOAD",
                    "section": "技术方案",
                    "title": "补充技术说明",
                    "status": "needs_input",
                    "decision": "material_required",
                    "resolvedArtifacts": [],
                }
            ],
            "summary": {"totalTocItems": 1},
        }
    )
    project = store._require(project_id)

    with patch.object(
        technical_gap_actions_module,
        "technical_workspace_dir",
        return_value=tmp_path / "technical-workspace",
    ):
        payload = technical_gap_actions_module.register_technical_manual_gap_upload(
            project,
            "TG-UPLOAD",
            {
                "files": [{"name": "补充技术说明.txt", "text": "这里是技术标人工补充内容。"}],
                "operator": "技术用户",
            },
            browser_base_url="http://testserver",
            onlyoffice_base_url="http://onlyoffice",
        )

    artifact = payload["artifact"]
    assert payload["item"]["status"] == "resolved"
    assert artifact["source"] == "manual_upload"
    assert artifact["operator"] == "技术用户"
    assert artifact["fileName"].endswith(".docx")
    assert Path(artifact["path"]).exists()
    assert artifact["onlyoffice"]["browserFileUrl"].startswith("http://testserver/api/technical/")


def test_technical_existing_material_action_uses_technical_material_store(tmp_path) -> None:
    project_id = _seed_technical_gap_project(
        {
            "items": [
                {
                    "id": "TG-MAT",
                    "section": "技术方案",
                    "title": "引用技术素材",
                    "status": "needs_input",
                    "decision": "material_required",
                    "resolvedArtifacts": [],
                }
            ],
            "summary": {"totalTocItems": 1},
        }
    )
    project = store._require(project_id)

    async def fake_raw_download(material_id: str) -> dict[str, str]:
        assert material_id == "RAW-TECH-001"
        return {
            "bucket": "mock-bucket",
            "key": "technical/RAW-TECH-001-original.docx",
            "fileName": "技术素材原件.docx",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }

    async def fake_cleaned_download(material_id: str) -> dict[str, str]:
        assert material_id == "RAW-TECH-001"
        return {
            "bucket": "mock-bucket",
            "key": "technical/RAW-TECH-001.docx",
            "fileName": "技术素材.docx",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }

    def fake_download_file(bucket: str, key: str, target_path: Path) -> None:
        assert bucket == "mock-bucket"
        if key == "technical/RAW-TECH-001-original.docx":
            target_path.with_suffix(f"{target_path.suffix}.download").write_bytes(b"partial")
            raise RuntimeError("raw object missing")
        assert key == "technical/RAW-TECH-001.docx"
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(b"technical-material-docx")

    with patch.object(
        technical_gap_actions_module,
        "technical_workspace_dir",
        return_value=tmp_path / "technical-workspace",
    ), patch.object(
        technical_gap_actions_module.technical_material_store,
        "raw_download_cleaned_content",
        side_effect=fake_cleaned_download,
    ), patch.object(
        technical_gap_actions_module.technical_material_store,
        "raw_download_content",
        side_effect=fake_raw_download,
    ), patch.object(
        technical_gap_actions_module.minio_client,
        "download_file",
        side_effect=fake_download_file,
    ):
        prepared = asyncio.run(
            technical_gap_actions_module.prepare_technical_existing_gap_material_files(
                project,
                "TG-MAT",
                {
                    "materials": [
                        {
                            "materialId": "RAW-TECH-001",
                            "materialName": "技术素材.docx",
                            "folderPath": "技术标/通用素材",
                            "materialTier": "standard",
                        }
                    ]
                },
            )
        )
        payload = technical_gap_actions_module.register_technical_existing_gap_material(
            project,
            "TG-MAT",
            {"operator": "技术用户"},
            prepared,
            browser_base_url="http://testserver",
        )

    artifact = payload["artifact"]
    assert prepared[0]["sourceKind"] == "cleaned"
    assert Path(prepared[0]["path"]).exists()
    assert payload["item"]["status"] == "resolved"
    assert artifact["source"] == "material_library"
    assert artifact["materialId"] == "RAW-TECH-001"
    assert artifact["operator"] == "技术用户"
    assert artifact["onlyoffice"]["browserFileUrl"].startswith("http://testserver/api/technical/")


def test_technical_ai_fill_action_stays_in_technical_ai_fill_module(tmp_path) -> None:
    project_id = _seed_technical_gap_project(
        {
            "scopeBoundary": {"readableScopes": []},
            "materialIndex": [],
            "items": [
                {
                    "id": "TG-AI",
                    "section": "技术方案",
                    "title": "技术参数响应",
                    "status": "needs_input",
                    "decision": "fill_required",
                    "usage": "table_fill",
                    "appendixTasks": [
                        {
                            "id": "BLANK-TABLE",
                            "title": "技术参数表",
                            "availableParseFields": [
                                {
                                    "id": "FIELD-001",
                                    "label": "项目名称",
                                    "value": "技术标服务拆分测试项目",
                                }
                            ],
                        }
                    ],
                    "fillTasks": [
                        {
                            "id": "FILL-TABLE",
                            "skill": "bid-tech-table-filler",
                            "status": "pending",
                            "blankSource": {"id": "BLANK-TABLE", "title": "技术参数表"},
                        }
                    ],
                    "resolvedArtifacts": [],
                }
            ],
            "summary": {"totalTocItems": 1, "fillableTaskCount": 1},
        }
    )
    project = store._require(project_id)
    project["gap_state"]["projectFactTable"] = {
        "status": "confirmed",
        "fields": [{"label": "项目名称", "value": "技术标服务拆分测试项目", "status": "confirmed"}],
    }

    def fake_table_runner(manifest_path: Path) -> dict[str, object]:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        output_path = Path(manifest["outputFile"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"technical-ai-filled-docx")
        assert manifest["schemaVersion"] == "bid-tech-table-fill-v1"
        assert manifest["projectFactTable"]["status"] == "confirmed"
        return {
            "schema_version": "bid-tech-table-fill-v1",
            "outputFile": str(output_path),
            "unfilledFields": [],
            "evidenceRefs": [{"fieldId": "FIELD-001", "source": "projectFactTable"}],
            "fillReport": {
                "targetFieldCount": 1,
                "filledFieldCount": 1,
                "unfilledFieldCount": 0,
                "semanticCheckCount": 1,
                "semanticFailedCount": 0,
                "semanticValidationRate": 1,
            },
        }

    with patch.object(
        technical_gap_ai_fill_module,
        "technical_workspace_dir",
        return_value=tmp_path / "technical-workspace",
    ), patch.object(
        technical_gap_ai_fill_module,
        "run_technical_table_filler_skill",
        side_effect=fake_table_runner,
    ):
        payload = technical_gap_actions_module.run_technical_ai_fill_for_gap(
            project,
            "TG-AI",
            {"fillTaskId": "FILL-TABLE", "operator": "技术用户"},
            browser_base_url="http://testserver",
        )

    artifact = payload["artifact"]
    assert payload["item"]["status"] == "resolved"
    assert payload["item"]["fillTasks"][0]["status"] == "completed"
    assert artifact["source"] == "ai_fill"
    assert artifact["skill"] == "bid-tech-table-filler"
    assert artifact["operator"] == "技术用户"
    assert artifact["qualityReport"]["status"] == "passed"
    assert Path(artifact["path"]).exists()
    assert artifact["onlyoffice"]["browserFileUrl"].startswith("http://testserver/api/technical/")


def test_technical_ai_fill_no_fill_required_reaches_s7_ready(tmp_path) -> None:
    """空白模板没有待填单元格时，填 0 格要走到 S7-ready 终态。

    质量门给出 no_fill_required 后，写回链路若仍按 == "passed" 判定，产物会带
    s7Ready=False 落库，technical_gap_artifact_is_s7_ready 的第一行短路就再也
    放行不了——放行逻辑形同虚设。这里从 run_technical_ai_fill_for_gap 端到端断言。
    """
    project_id = _seed_technical_gap_project(
        {
            "scopeBoundary": {"readableScopes": []},
            "materialIndex": [],
            "items": [
                {
                    "id": "TG-NOFILL",
                    "section": "技术方案",
                    "title": "机型配置品牌表",
                    "status": "needs_input",
                    "decision": "fill_required",
                    "usage": "table_fill",
                    "appendixTasks": [{"id": "BLANK-NOFILL", "title": "机型配置品牌表"}],
                    "fillTasks": [
                        {
                            "id": "FILL-NOFILL",
                            "skill": "bid-tech-table-filler",
                            "status": "pending",
                            "blankSource": {"id": "BLANK-NOFILL", "title": "机型配置品牌表"},
                        }
                    ],
                    "resolvedArtifacts": [],
                }
            ],
            "summary": {"totalTocItems": 1, "fillableTaskCount": 1},
        }
    )
    project = store._require(project_id)

    def fake_no_fill_runner(manifest_path: Path) -> dict[str, object]:
        output_path = Path(json.loads(Path(manifest_path).read_text(encoding="utf-8"))["outputFile"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"technical-ai-filled-docx")
        return {
            "schema_version": "bid-tech-table-fill-v1",
            "outputFile": str(output_path),
            "unfilledFields": [],
            "evidenceRefs": [{"type": "blank_source", "path": "机型配置品牌表.docx"}],
            "fillReport": {
                "targetFieldCount": 0,
                "filledFieldCount": 0,
                "unfilledFieldCount": 0,
                "noFillRequired": True,
            },
        }

    with patch.object(
        technical_gap_ai_fill_module,
        "technical_workspace_dir",
        return_value=tmp_path / "technical-workspace",
    ), patch.object(
        technical_gap_ai_fill_module,
        "run_technical_table_filler_skill",
        side_effect=fake_no_fill_runner,
    ):
        payload = technical_gap_actions_module.run_technical_ai_fill_for_gap(
            project,
            "TG-NOFILL",
            {"fillTaskId": "FILL-NOFILL", "operator": "技术用户"},
            browser_base_url="http://testserver",
        )

    artifact = payload["artifact"]
    assert artifact["qualityReport"]["status"] == "no_fill_required"
    assert artifact["s7Ready"] is True
    assert technical_gap_artifact_is_s7_ready(artifact) is True
    assert payload["item"]["status"] == "resolved"
    assert payload["item"]["qualityStatus"] == "no_fill_required"
    assert not any("验收未达标" in note for note in payload["item"]["reviewNotes"])


def test_technical_body_fill_rejects_fact_table_without_spec_columns() -> None:
    """正文填写的清单元数据缺失时显式失败，不再静默回退到旧的模糊匹配链路。"""
    project_id = _seed_technical_gap_project(
        {
            "items": [
                {
                    "id": "TG-BODY",
                    "number": "5.8.2",
                    "title": "变桨系统专题",
                    "status": "needs_input",
                    "decision": "fill_required",
                    "usage": "section_fill",
                    "appendixTasks": [{"id": "BLANK-BODY", "title": "待填写-变桨系统专题.docx"}],
                    "fillTasks": [
                        {
                            "id": "FILL-BODY",
                            "skill": "bid-tech-word-placeholder-filler",
                            "status": "pending",
                            "blankSource": {
                                "id": "BLANK-BODY",
                                "title": "待填写-变桨系统专题.docx",
                                "sourceType": "material_fill_template",
                            },
                        }
                    ],
                    "resolvedArtifacts": [],
                }
            ],
            "summary": {"totalTocItems": 1, "fillableTaskCount": 1},
        }
    )
    project = store._require(project_id)
    project["gap_state"]["projectFactTable"] = {
        "status": "confirmed",
        "fields": [{"label": "项目名称", "value": "技术标服务拆分测试项目", "status": "confirmed"}],
    }

    with pytest.raises(RuntimeError, match="重新上传"):
        technical_gap_actions_module.run_technical_ai_fill_for_gap(
            project,
            "TG-BODY",
            {"fillTaskId": "FILL-BODY", "operator": "技术用户"},
        )


def test_technical_gap_fact_table_lookup_stays_in_technical_service() -> None:
    project_id = _seed_technical_gap_project({"items": [], "summary": {}})
    record = store._require(project_id)
    record["gap_state"]["projectFactTable"] = {
        "schemaVersion": PROJECT_FACT_TABLE_SCHEMA_VERSION,
        "projectId": project_id,
        "status": "draft",
        "fields": [{"label": "项目名称", "value": "技术标服务拆分测试项目"}],
        "summary": {"totalCount": 1},
    }
    store._persist_project(record)

    with patch(
        "app.services.store.store.get_gap_fact_table",
        side_effect=AssertionError("technical_gap_service must not delegate fact lookup back to store"),
        create=True,
    ):
        payload = asyncio.run(technical_gap_service.facts(project_id))

    assert payload["schemaVersion"] == PROJECT_FACT_TABLE_SCHEMA_VERSION
    assert payload["fields"][0]["label"] == "项目名称"


def test_technical_gap_build_facts_stays_in_technical_service() -> None:
    project_id = _seed_technical_gap_project({"items": [], "summary": {}})
    built_table = {
        "schemaVersion": PROJECT_FACT_TABLE_SCHEMA_VERSION,
        "projectId": project_id,
        "status": "draft",
        "builtAt": now_iso(),
        "updatedAt": now_iso(),
        "fields": [{"label": "招标编号", "value": "TECH-001"}],
        "summary": {"totalCount": 1},
    }

    with patch(
        "app.services.store.store.build_gap_fact_table",
        side_effect=AssertionError("technical_gap_service must not delegate fact build back to store"),
        create=True,
    ), patch(
        "app.services.store.store._build_project_fact_table",
        side_effect=AssertionError("technical_gap_service must use fact table helper for fact building"),
        create=True,
    ), patch(
        "app.services.technical_gap_service.build_project_fact_table",
        return_value=built_table,
    ), patch(
        "app.services.technical_gap_service.require_technical_gap_project_for_update",
        wraps=require_technical_gap_project_for_update,
    ) as require_project, patch(
        "app.services.technical_gap_service.mutate_technical_gap_project",
        wraps=mutate_technical_gap_project,
    ) as persist_project:
        payload = asyncio.run(technical_gap_service.build_facts(project_id))

    assert payload["fields"][0]["label"] == "招标编号"
    require_project.assert_called_once_with(project_id)
    persist_project.assert_called_once()
    assert store._require(project_id)["gap_state"]["projectFactTable"]["fields"][0]["value"] == "TECH-001"


def test_technical_gap_save_facts_stays_in_technical_service() -> None:
    project_id = _seed_technical_gap_project({"items": [], "summary": {}})
    record = store._require(project_id)
    record["gap_state"]["projectFactTable"] = {
        "schemaVersion": PROJECT_FACT_TABLE_SCHEMA_VERSION,
        "projectId": project_id,
        "status": "draft",
        "builtAt": now_iso(),
        "updatedAt": now_iso(),
        "fields": [],
        "summary": {"totalCount": 0},
    }
    store._persist_project(record)

    with patch(
        "app.services.store.store.save_gap_fact_table",
        side_effect=AssertionError("technical_gap_service must not delegate fact save back to store"),
        create=True,
    ), patch(
        "app.services.store.store._normalize_project_fact_field",
        side_effect=AssertionError("technical_gap_service must use fact table helper for fact normalization"),
        create=True,
    ), patch(
        "app.services.store.store._summarize_project_fact_fields",
        side_effect=AssertionError("technical_gap_service must use fact table helper for fact summaries"),
        create=True,
    ):
        payload = asyncio.run(
            technical_gap_service.save_facts(
                project_id,
                {
                    "fields": [{"label": "投标机型", "value": "WTG-1", "required": True}],
                    "confirm": True,
                    "operator": "技术用户",
                },
            )
        )

    assert payload["status"] == "confirmed"
    assert payload["confirmedBy"] == "技术用户"
    # 整表 confirm 只升表级状态；字段级"人工产出"标记只能由 PATCH 单字段接口产生，
    # 否则一次保存就把整张表变成 AI 禁区（三态收敛后这层约束落在 sourceRefs 标记上，
    # 字段状态本身只反映有无取值）
    assert payload["fields"][0]["status"] == "confirmed"
    assert all(
        ref.get("type") not in {"manualEdit", "manualFact"}
        for ref in payload["fields"][0].get("sourceRefs") or []
    )
    assert store._require(project_id)["gap_state"]["projectFactTable"]["status"] == "confirmed"


def test_technical_gap_detection_stays_out_of_store_private_helpers() -> None:
    project_id = _seed_technical_gap_project({"items": [], "summary": {}})
    plan = {
        "items": [
            {
                "id": "TG-1",
                "section": "技术方案",
                "title": "总体方案",
                "status": "needs_input",
                "priority": "high",
                "decision": "material_required",
            }
        ],
        "summary": {"totalTocItems": 1},
    }

    with patch(
        "app.services.store.store.run_gap_detection",
        side_effect=AssertionError("technical_gap_service must not delegate gap detection back to store"),
        create=True,
    ), patch(
        "app.services.store.store._ensure_gap_state",
        create=True,
        side_effect=AssertionError("technical_gap_service must use technical_gap_state.ensure_technical_gap_state"),
    ), patch(
        "app.services.store.store._legacy_gap_items_from_plan",
        create=True,
        side_effect=AssertionError("technical_gap_service must use technical_gap_state.legacy_technical_gap_items_from_plan"),
    ), patch(
        "app.services.store.store._build_gap_detection_payload",
        create=True,
        side_effect=AssertionError("technical_gap_service must use technical_gap_domain.build_technical_gap_detection_payload"),
    ), patch(
        "app.services.store.store._default_review_document_state",
        create=True,
        side_effect=AssertionError("technical_gap_service must use technical_gap_state.default_technical_review_document_state"),
    ), patch(
        "app.services.technical_gap_service.build_technical_gap_plan_for_project",
        return_value=plan,
    ):
        payload = technical_gap_service.run_detection(project_id)

    assert payload["message"] == "缺口识别完成，共识别 1 个目录项。"
    assert store._require(project_id)["gap_state"]["items"][0]["id"] == "TG-1"


def test_technical_gap_filling_stays_in_technical_service() -> None:
    project_id = _seed_technical_gap_project(
        {
            "items": [
                {
                    "id": "TG-1",
                    "section": "技术方案",
                    "title": "总体方案",
                    "status": "needs_input",
                    "decision": "material_required",
                }
            ],
            "summary": {"totalTocItems": 1},
        }
    )

    with patch(
        "app.services.store.store.get_gap_filling",
        side_effect=AssertionError("technical_gap_service must not delegate gap filling back to store"),
        create=True,
    ), patch(
        "app.services.store.store._ensure_gap_state",
        create=True,
        side_effect=AssertionError("technical_gap_service must use technical_gap_state.ensure_technical_gap_state"),
    ), patch(
        "app.services.store.store._refresh_gap_plan_artifact_urls",
        create=True,
        side_effect=AssertionError("technical_gap_service must use technical_gap_domain.refresh_technical_gap_plan_artifact_urls"),
    ):
        payload = asyncio.run(technical_gap_service.gaps(project_id, _DummyRequest()))

    assert payload["status"] == "ready"
    assert payload["gapPlan"]["items"][0]["id"] == "TG-1"


def test_technical_gap_update_stays_in_technical_service() -> None:
    project_id = _seed_technical_gap_project(
        {
            "items": [
                {
                    "id": "TG-1",
                    "section": "技术方案",
                    "title": "总体方案",
                    "status": "needs_input",
                    "decision": "material_required",
                    "reviewNotes": [],
                }
            ],
            "summary": {"totalTocItems": 1},
        }
    )

    with patch(
        "app.services.store.store.update_gap_item",
        side_effect=AssertionError("technical_gap_service must not delegate gap updates back to store"),
        create=True,
    ), patch(
        "app.services.store.store._ensure_gap_state",
        create=True,
        side_effect=AssertionError("technical_gap_service must use technical_gap_state.ensure_technical_gap_state"),
    ), patch(
        "app.services.store.store._find_gap_item",
        create=True,
        side_effect=AssertionError("technical_gap_service must use technical_gap_domain.find_technical_gap_item"),
    ), patch(
        "app.services.store.store._find_gap_plan_item",
        create=True,
        side_effect=AssertionError("technical_gap_service must use technical_gap_domain.find_technical_gap_plan_item"),
    ), patch(
        "app.services.store.store._default_review_document_state",
        create=True,
        side_effect=AssertionError("technical_gap_service must use technical_gap_state.default_technical_review_document_state"),
    ):
        payload = asyncio.run(
            technical_gap_service.update_gap(
                project_id,
                "TG-1",
                {"status": "skipped", "reason": "技术标单独确认"},
            )
        )

    assert payload["item"]["status"] == "skipped"
    assert store._require(project_id)["gap_state"]["plan"]["items"][0]["status"] == "ignored"


def test_technical_gap_review_submit_stays_in_technical_service() -> None:
    project_id = _seed_technical_gap_project(
        {
            "items": [
                {
                    "id": "TG-1",
                    "section": "技术方案",
                    "title": "总体方案",
                    "status": "ignored",
                    "decision": "material_required",
                }
            ],
            "summary": {"totalTocItems": 1},
        }
    )

    with patch(
        "app.services.store.store.submit_gap_review",
        side_effect=AssertionError("technical_gap_service must not delegate review submit back to store"),
        create=True,
    ), patch(
        "app.services.store.store._ensure_gap_state",
        create=True,
        side_effect=AssertionError("technical_gap_service must use technical_gap_state.ensure_technical_gap_state"),
    ):
        payload = asyncio.run(technical_gap_service.submit_review(project_id))

    assert payload["payload"]["submittedForReview"] is True
    assert store._require(project_id)["gap_state"]["submittedForReview"] is True
