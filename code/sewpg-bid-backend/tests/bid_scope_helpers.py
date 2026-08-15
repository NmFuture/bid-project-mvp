"""test_scope_* 共享夹具：假请求/OCR service、商务与技术 gap 项目播种。

由 test_bid_material_scope_services.py 拆分而来，只搬不改。
"""
import copy
from typing import Any
from starlette.datastructures import URL
from app.services.bid_runtime_state import now_iso
from app.services.store import store


class _DummyRequest:
    base_url = URL("http://testserver/")
    url = URL("http://testserver/")


class _DummyOcrProjectService:
    bid_type = "商务标"

    @staticmethod
    def ensure_project(project_id: str) -> dict[str, Any]:
        return {
            "id": project_id,
            "name": "商务 OCR 项目",
            "projectCode": "BIZ-OCR-001",
            "customerName": "测试业主",
            "bidType": "商务标",
        }


def _seed_business_gap_project(plan: dict) -> str:
    store.reset_for_tests()
    project = store.create_project({"name": "商务标服务拆分测试项目", "customerName": "测试业主", "bidType": "商务标"})
    project_id = project["id"]
    record = store._require(project_id)
    record["business_gap_state"].update(
        {
            "recognitionStatus": "completed",
            "recognizedAt": now_iso(),
            "plan": plan,
            "integrity": {},
        }
    )
    store._persist_project(record)
    return project_id


def _seed_technical_gap_project(plan: dict) -> str:
    store.reset_for_tests()
    project = store.create_project({"name": "技术标服务拆分测试项目", "customerName": "测试业主", "bidType": "技术标"})
    project_id = project["id"]
    record = store._require(project_id)
    # 素材匹配启动前要求目录已确认（R11-B07-03），seed 一个已确认的非空目录
    record["outline_state"] = {
        "outlineVersion": 1,
        "reviewStatus": "confirmed",
        "generatedAt": now_iso(),
        "summary": {"totalNodeCount": 1},
        "nodes": [{"id": "OL-1", "title": "总体方案", "level": 1, "children": []}],
    }
    record["gap_state"].update(
        {
            "recognitionStatus": "completed",
            "recognizedAt": now_iso(),
            "plan": plan,
            "items": copy.deepcopy(plan.get("items") or []),
            "integrity": {},
            # build_facts 门控 seed：测试绕过实时表上传，直接注入小清单作为项目 specs
            "factSpecs": {
                "fileName": "测试实时表.xlsx",
                "uploadedAt": "2026-07-27T00:00:00",
                "specs": [
                    {
                        "seq": 1,
                        "key": "招标编号",
                        "label": "招标编号",
                        "reviewLabel": "",
                        "sourceFile": "",
                        "placeholder": "",
                        "note": "",
                        "needsConfirmation": False,
                        "referenceFile": "招标文件",
                        "valueRequired": True,
                        "sourceKind": "tender",
                        "aliases": [],
                    }
                ],
            },
        }
    )
    store._persist_project(record)
    return project_id
