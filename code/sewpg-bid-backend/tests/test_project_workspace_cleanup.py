"""删项目时磁盘工作区的清理边界。

删除接口此前只清 `parsed_dir/{PID}`，`documents_dir/{PID}` 下的 technical-workspace
会带着 `tender_review_state.json` 残留；一旦新项目拿到同一编号，就会被判定为「已有解析
状态」而降级成续跑，最终报成功却没有产物。这里锁住四处产物都被清掉，同时锁住共享目录
和别的项目不受牵连。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.core.config import settings
from app.services.workspace_artifacts import cleanup_project_disk_workspaces


class ProjectWorkspaceCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        self.original = (settings.uploads_dir, settings.documents_dir, settings.parsed_dir)
        settings.uploads_dir = base / "uploads"
        settings.documents_dir = base / "documents"
        settings.parsed_dir = base / "parsed"
        settings.ensure_dirs()

    def tearDown(self) -> None:
        settings.uploads_dir, settings.documents_dir, settings.parsed_dir = self.original
        self.temp_dir.cleanup()

    def _seed_project(self, project_id: str) -> dict[str, Path]:
        review_state = (
            settings.documents_dir / project_id / "technical-workspace" / "tender_review_state.json"
        )
        review_state.parent.mkdir(parents=True, exist_ok=True)
        review_state.write_text('{"status": "completed"}', encoding="utf-8")

        upload = settings.uploads_dir / project_id / "tender" / "招标文件.docx"
        upload.parent.mkdir(parents=True, exist_ok=True)
        upload.write_bytes(b"upload")

        parsed = settings.parsed_dir / project_id / "s1_structured_result.json"
        parsed.parent.mkdir(parents=True, exist_ok=True)
        parsed.write_text("{}", encoding="utf-8")

        document = settings.documents_dir / f"{project_id}.docx"
        document.write_bytes(b"docx")

        return {"reviewState": review_state, "upload": upload, "parsed": parsed, "document": document}

    def test_removes_all_project_scoped_artifacts(self) -> None:
        seeded = self._seed_project("PRJ-0011")

        result = cleanup_project_disk_workspaces("PRJ-0011")

        self.assertEqual(result["failures"], [])
        self.assertCountEqual(
            result["removed"], ["parsed", "documents", "uploads", "onlyofficeDocument"]
        )
        for path in seeded.values():
            self.assertFalse(path.exists(), f"{path} 应已被删除")
        self.assertFalse((settings.documents_dir / "PRJ-0011").exists())

    def test_keeps_shared_runtime_dir_and_other_projects(self) -> None:
        self._seed_project("PRJ-0011")
        kept = self._seed_project("PRJ-0012")
        runtime_marker = settings.documents_dir / "_runtime" / "materials" / "index.json"
        runtime_marker.parent.mkdir(parents=True, exist_ok=True)
        runtime_marker.write_text("{}", encoding="utf-8")

        cleanup_project_disk_workspaces("PRJ-0011")

        self.assertTrue(runtime_marker.exists(), "共享 _runtime 目录不能被牵连")
        for path in kept.values():
            self.assertTrue(path.exists(), f"{path} 属于另一个项目，不该被删")

    def test_missing_workspace_is_not_an_error(self) -> None:
        result = cleanup_project_disk_workspaces("PRJ-9999")

        self.assertEqual(result["removed"], [])
        self.assertEqual(result["failures"], [])

    def test_rejects_project_id_that_escapes_root(self) -> None:
        runtime_marker = settings.documents_dir / "_runtime" / "keep.json"
        runtime_marker.parent.mkdir(parents=True, exist_ok=True)
        runtime_marker.write_text("{}", encoding="utf-8")

        result = cleanup_project_disk_workspaces("../documents/_runtime")

        self.assertTrue(runtime_marker.exists())
        self.assertEqual(result["removed"], [])
        self.assertEqual(
            sorted(item["target"] for item in result["failures"]),
            ["documents", "parsed", "uploads"],
        )


if __name__ == "__main__":
    unittest.main()
