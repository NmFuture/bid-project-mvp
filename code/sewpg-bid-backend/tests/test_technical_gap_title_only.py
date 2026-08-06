"""S3 树状改造（产品裁决 2026-08-04）后端行为单测。

一、目录节点「忽略」：仅保留标题骨架，titleOnly 标记可设可撤，冻结/释放由前端派生。
二、选定即定案：人工选素材/上传素材本身就是人工决策，register 后直接落
humanConfirmed，不再要求二次点「确认」。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.technical_gap_actions import (
    register_technical_existing_gap_material,
    register_technical_manual_gap_upload,
)
from app.services.technical_gap_domain import (
    recompute_technical_gap_decisions,
    technical_gap_artifact_is_s7_ready,
)
from app.services.technical_gap_service import technical_gap_service


def _project(items: list[dict]) -> dict:
    return {
        "id": "PRJ-TEST",
        "bidType": "技术标",
        "gap_state": {"recognitionStatus": "completed", "plan": {"items": items}},
    }


def _items() -> list[dict]:
    return [
        {
            "id": "GAP-0001",
            "number": "第3章",
            "title": "风资源评估与机位排布方案",
            "level": 1,
            "status": "matched",
            "decision": "review_required",
            "matchedMaterials": [{"id": "RAW-1", "name": "风资源报告.docx"}],
        },
        {
            "id": "GAP-0002",
            "number": "3.1",
            "title": "风资源分析",
            "level": 2,
            "status": "missing",
            "decision": "material_required",
            "matchedMaterials": [],
        },
    ]


class TitleOnlyServiceTests(unittest.TestCase):
    def _call(self, project: dict, gap_id: str, data: dict) -> dict:
        with (
            patch(
                "app.services.technical_gap_service.require_technical_gap_project_for_update",
                return_value=project,
            ),
            patch("app.services.technical_gap_service.persist_technical_gap_project"),
        ):
            return technical_gap_service.set_title_only("PRJ-TEST", gap_id, data)

    def test_set_and_unset_title_only(self) -> None:
        project = _project(_items())
        result = self._call(project, "GAP-0001", {"operator": "测试员"})
        item = result["item"]
        self.assertTrue(item["titleOnly"])
        self.assertEqual(item["titleOnlyBy"], "测试员")
        self.assertTrue(item["titleOnlyAt"])
        self.assertIn("仅保留标题", result["message"])

        result = self._call(project, "GAP-0001", {"enabled": False, "operator": "测试员"})
        item = result["item"]
        self.assertFalse(item["titleOnly"])
        self.assertEqual(item["titleOnlyAt"], "")
        self.assertEqual(item["titleOnlyBy"], "")

    def test_unknown_gap_raises_not_found(self) -> None:
        project = _project(_items())
        with self.assertRaises(Exception):
            self._call(project, "GAP-9999", {})


class SelectionAutoConfirmTests(unittest.TestCase):
    def test_manual_upload_stamps_human_confirmed(self) -> None:
        project = _project(_items())
        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "app.services.technical_gap_actions._project_dir",
                return_value=Path(tmp),
            ):
                result = register_technical_manual_gap_upload(
                    project,
                    "GAP-0002",
                    {"files": [{"name": "补充素材.docx", "content": "正文"}], "operator": "测试员"},
                )
        item = result["item"]
        self.assertEqual(item["status"], "resolved")
        self.assertTrue(item["humanConfirmed"])
        self.assertEqual(item["humanConfirmedBy"], "测试员")

    def test_select_existing_material_stamps_human_confirmed(self) -> None:
        project = _project(_items())
        with tempfile.TemporaryDirectory() as tmp:
            prepared_path = Path(tmp) / "01-已选素材.docx"
            prepared_path.write_bytes(b"docx-bytes")
            result = register_technical_existing_gap_material(
                project,
                "GAP-0002",
                {"operator": "测试员"},
                [
                    {
                        "materialId": "RAW-9",
                        "materialName": "已选素材",
                        "fileName": prepared_path.name,
                        "path": str(prepared_path),
                        "folderPath": "技术标/通用素材/示例",
                        "materialTier": "standard",
                        "sourceKind": "cleaned",
                    }
                ],
            )
        item = result["item"]
        self.assertEqual(item["status"], "resolved")
        self.assertTrue(item["humanConfirmed"])
        self.assertEqual(item["humanConfirmedBy"], "测试员")

    def test_select_fill_template_enters_pending_fill_and_stays_out_of_s7(self) -> None:
        """R10-B07-01：选中「待填写-」空模板 → 待填写而非已就绪，产物 s7Ready=False。"""
        project = _project(_items())
        with tempfile.TemporaryDirectory() as tmp:
            prepared_path = Path(tmp) / "01-待填写-投标说明函.docx"
            prepared_path.write_bytes(b"docx-bytes")
            result = register_technical_existing_gap_material(
                project,
                "GAP-0002",
                {"operator": "测试员"},
                [
                    {
                        "materialId": "RAW-TPL1",
                        "materialName": "待填写-投标说明函.docx",
                        "fileName": prepared_path.name,
                        "path": str(prepared_path),
                        "folderPath": "技术标/通用素材/示例",
                        "materialTier": "standard",
                        "sourceKind": "cleaned",
                    }
                ],
            )
        item = result["item"]
        artifact = result["artifact"]
        # 空模板不是成稿：产物保持 s7Ready=False，S7 闸口与决策终审同口径拦截。
        self.assertFalse(artifact["s7Ready"])
        self.assertFalse(technical_gap_artifact_is_s7_ready(artifact))
        # 目录项进入「待填写」而非「已就绪」。
        self.assertEqual(item["status"], "needs_input")
        self.assertEqual(item["decision"], "fill_required")
        self.assertNotIn("resolvedAt", item)
        # 选定即定案仍然成立：定下的是模板本身，并挂出待执行的 AI 填写任务。
        self.assertTrue(item["humanConfirmed"])
        fill_tasks = item.get("fillTasks") or []
        self.assertEqual(len(fill_tasks), 1)
        self.assertEqual(fill_tasks[0]["status"], "pending")
        self.assertEqual(fill_tasks[0]["blankSource"]["sourceType"], "material_fill_template")
        self.assertEqual(fill_tasks[0]["blankSource"]["materialId"], "RAW-TPL1")
        # 决策终审不得把空模板产物翻回成稿。
        plan = project["gap_state"]["plan"]
        recompute_technical_gap_decisions(plan)
        final_item = next(entry for entry in plan["items"] if entry["id"] == "GAP-0002")
        self.assertEqual(final_item["decision"], "fill_required")
        self.assertEqual(final_item["status"], "needs_input")


if __name__ == "__main__":
    unittest.main()
