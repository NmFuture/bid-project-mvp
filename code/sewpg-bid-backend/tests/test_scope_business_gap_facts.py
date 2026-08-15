import asyncio
import json
from pathlib import Path
from unittest.mock import patch
from app.services.business_gap_repository import (
    persist_business_gap_project,
    require_business_gap_project_for_update,
)
from app.services.business_gap_service import business_gap_service
from app.services.bid_runtime_state import now_iso
from app.services.store import store
from app.services.business_gap_fact_table import (
    PROJECT_FACT_TABLE_SCHEMA_VERSION as BUSINESS_FACT_TABLE_SCHEMA_VERSION,
)

from bid_scope_helpers import (
    _seed_business_gap_project,
)


def test_business_gap_fact_table_lookup_stays_in_business_service() -> None:
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
        "fields": [{"label": "项目名称", "value": "商务标服务拆分测试项目"}],
        "summary": {"totalCount": 1},
    }
    store._persist_project(record)

    with patch(
        "app.services.store.store.get_business_gap_fact_table",
        side_effect=AssertionError("business_gap_service must not delegate fact lookup back to store"),
        create=True,
    ):
        payload = business_gap_service.facts(project_id)

    assert payload["schemaVersion"] == BUSINESS_FACT_TABLE_SCHEMA_VERSION
    assert payload["fields"][0]["label"] == "项目名称"


def test_business_gap_empty_fact_table_stays_in_fact_table_helper() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [],
            "tasks": [],
            "summary": {},
        }
    )

    with patch(
        "app.services.store.store._empty_project_fact_table",
        side_effect=AssertionError("business_gap_service must use business_gap_fact_table for empty facts"),
        create=True,
    ):
        payload = business_gap_service.facts(project_id)

    assert payload["schemaVersion"] == BUSINESS_FACT_TABLE_SCHEMA_VERSION
    assert payload["status"] == "empty"
    assert payload["summary"]["totalCount"] == 0


def test_business_gap_build_facts_stays_in_business_service() -> None:
    project_id = _seed_business_gap_project(
        {
            "schemaVersion": "bid-business-gap-plan-v1",
            "tocRefs": [],
            "tasks": [],
            "summary": {},
        }
    )
    built_table = {
        "schemaVersion": BUSINESS_FACT_TABLE_SCHEMA_VERSION,
        "projectId": project_id,
        "status": "draft",
        "builtAt": now_iso(),
        "updatedAt": now_iso(),
        "fields": [{"label": "招标编号", "value": "BIZ-001"}],
        "summary": {"totalCount": 1},
    }

    with patch(
        "app.services.store.store.build_business_gap_fact_table",
        side_effect=AssertionError("business_gap_service must not delegate fact build back to store"),
        create=True,
    ), patch(
        "app.services.store.store._build_project_fact_table",
        side_effect=AssertionError("business_gap_service must use business_gap_fact_table for fact building"),
        create=True,
    ), patch(
        "app.services.business_gap_service.build_project_fact_table",
        return_value=built_table,
    ), patch(
        "app.services.business_gap_service.require_business_gap_project_for_update",
        wraps=require_business_gap_project_for_update,
    ) as require_project, patch(
        "app.services.business_gap_service.persist_business_gap_project",
        wraps=persist_business_gap_project,
    ) as persist_project:
        payload = asyncio.run(business_gap_service.build_facts(project_id))

    assert payload["fields"][0]["label"] == "招标编号"
    require_project.assert_called_once_with(project_id)
    persist_project.assert_called_once()
    assert store._require(project_id)["business_gap_state"]["projectFactTable"]["fields"][0]["value"] == "BIZ-001"


def test_business_fact_table_ignores_empty_turbine_model_dict_and_signature_party_noise() -> None:
    from app.services.business_gap_fact_table import build_project_fact_table

    project = {
        "id": "PRJ-BIZ-FACT-NOISE",
        "name": "真实样本事实表降噪测试",
        "customerName": "京能集团",
        "bidType": "商务标",
        "turbineModel": {
            "model": "",
            "platform": "",
            "layout": "",
            "status": "manual",
            "aliases": [],
        },
        "parse_result": {
            "status": "completed",
            "structured": {
                "projectFactFields": [
                    {
                        "fieldKey": "tenderer",
                        "label": "招标人",
                        "value": "山西漳山发电有限责任公司 （盖单位章",
                        "confidence": 0.95,
                    },
                    {
                        "fieldKey": "tenderer",
                        "label": "招标人",
                        "value": "将在收到异议之日起 3 日内作出答复，作出答复前，将暂停招标投标活动",
                        "confidence": 0.96,
                    },
                    {
                        "fieldKey": "tenderer",
                        "label": "招标人",
                        "value": "收到澄清后12小时内,逾期未在规定时间内确认的，招标人一律视为已收到",
                        "confidence": 0.97,
                    },
                    {
                        "fieldKey": "tenderer",
                        "label": "招标人",
                        "value": "在本章第 4.2.1 项规定的投标截止时间(开标时间),通过中国华能集团有限公司电子商务平台公开开标",
                        "confidence": 0.98,
                    },
                ]
            },
        },
    }

    table = build_project_fact_table(project, {"plan": {}})
    labels = {field["label"]: field for field in table["fields"]}
    # 盖章装饰剥离后封面招标人是可信值；句子型噪声仍被拒绝
    assert labels["招标人"]["value"] == "山西漳山发电有限责任公司"
    assert labels["风机型号"]["value"] == ""


def test_business_fact_table_accepts_party_name_with_seal_decoration() -> None:
    from app.services.business_gap_fact_table import build_project_fact_table

    project = {
        "id": "PRJ-BIZ-FACT-SEAL",
        "name": "盖章尾巴清洗测试",
        "customerName": "京能集团",
        "bidType": "商务标",
        "parse_result": {
            "status": "completed",
            "structured": {
                "projectFactFields": [
                    {
                        "fieldKey": "tenderer",
                        "label": "招标人",
                        "value": "山西漳山发电有限责任公司 （盖单位章",
                        "confidence": 0.95,
                    }
                ]
            },
        },
    }
    gap_state = {
        "plan": {},
        "projectFactTable": {
            "schemaVersion": "bid-project-fact-table-v1",
            "fields": [
                {
                    "label": "招标人",
                    "value": "京能集团",
                    "status": "candidate",
                    "sourceRefs": [{"type": "project", "field": "customerName", "title": "招标人"}],
                }
            ],
        },
    }

    table = build_project_fact_table(project, gap_state)
    labels = {field["label"]: field for field in table["fields"]}
    assert labels["招标人"]["value"] == "山西漳山发电有限责任公司"


def test_business_fact_table_drops_placeholder_values_on_rebuild() -> None:
    from app.services.business_gap_fact_table import build_project_fact_table

    project = {
        "id": "PRJ-BIZ-FACT-PLACEHOLDER",
        "name": "占位符清洗测试",
        "bidType": "商务标",
        "parse_result": {
            "status": "completed",
            "structured": {
                "projectFactFields": [
                    {
                        "fieldKey": "projectName",
                        "label": "项目名称",
                        "value": "（项目名称）",
                        "confidence": 0.9,
                    }
                ]
            },
        },
    }
    gap_state = {
        "plan": {},
        "projectFactTable": {
            "schemaVersion": "bid-project-fact-table-v1",
            "fields": [
                {
                    "label": "招标项目名称",
                    "value": "（项目名称）",
                    "status": "candidate",
                    "confidence": 0.86,
                },
                {
                    "label": "招标编号",
                    "value": "ZBA272600801",
                    "status": "candidate",
                    "confidence": 0.9,
                },
            ],
        },
    }

    table = build_project_fact_table(project, gap_state)
    labels = {field["label"]: field for field in table["fields"]}
    assert labels["招标项目名称"]["value"] == "占位符清洗测试"
    assert labels["招标编号"]["value"] == "ZBA272600801"


def test_business_fact_table_uses_shared_bidder_profile() -> None:
    from app.services.business_gap_fact_table import build_project_fact_table

    project = {"id": "PRJ-BIDDER-PROFILE", "name": "档案测试项目", "bidType": "商务标"}
    with patch(
        "app.services.business_gap_fact_table.load_business_bidder_facts_sync",
        return_value={"投标人地址": "上海市闵行区东川路555号", "投标人电话": "021-00000000"},
    ):
        table = build_project_fact_table(project, {"plan": {}})
    labels = {field["label"]: field for field in table["fields"]}
    assert labels["投标人地址"]["value"] == "上海市闵行区东川路555号"
    assert labels["投标人地址"]["sourceRefs"][0]["type"] == "bidderProfile"
    assert labels["投标人电话"]["value"] == "021-00000000"
    assert labels["投标人"]["value"] == "上海电气风电集团股份有限公司"


def test_business_fact_table_profile_refreshes_unconfirmed_fixed_candidates() -> None:
    from app.services.business_gap_fact_table import build_project_fact_table

    project = {"id": "PRJ-BIDDER-PROFILE-2", "name": "档案刷新测试", "bidType": "商务标"}
    gap_state = {
        "plan": {},
        "projectFactTable": {
            "schemaVersion": "bid-project-fact-table-v1",
            "fields": [
                {"label": "投标人地址", "value": "旧地址", "status": "candidate"},
                {
                    "label": "投标人电话",
                    "value": "010-11111111",
                    "status": "confirmed",
                    "confirmedAt": "2026-06-01T00:00:00+00:00",
                    "confirmedBy": "人工",
                },
            ],
        },
    }
    with patch(
        "app.services.business_gap_fact_table.load_business_bidder_facts_sync",
        return_value={"投标人地址": "上海市浦东新区新地址1号", "投标人电话": "021-22222222"},
    ):
        table = build_project_fact_table(project, gap_state)
    labels = {field["label"]: field for field in table["fields"]}
    assert labels["投标人地址"]["value"] == "上海市浦东新区新地址1号"
    assert labels["投标人电话"]["value"] == "010-11111111"


def test_business_assembly_fact_table_stays_in_fact_table_helper(tmp_path) -> None:
    from app.services import business_assembly

    source = Path("app/services/business_assembly.py").read_text(encoding="utf-8")
    built_table = {
        "schemaVersion": BUSINESS_FACT_TABLE_SCHEMA_VERSION,
        "projectId": "PRJ-BIZ-ASSEMBLY",
        "status": "draft",
        "fields": [{"label": "项目名称", "value": "商务标装配测试"}],
        "summary": {"totalCount": 1},
    }

    assert "from app.services.store import store" not in source
    with patch(
        "app.services.business_assembly.build_project_fact_table",
        return_value=built_table,
    ):
        path = business_assembly._prepare_project_fact_table(
            {"id": "PRJ-BIZ-ASSEMBLY", "bidType": "商务标"},
            {},
            tmp_path,
        )

    assert json.loads(path.read_text(encoding="utf-8"))["fields"][0]["value"] == "商务标装配测试"
