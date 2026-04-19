from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.core.config import settings
from app.services.store import AppStore


class StorePersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        settings.sqlite_path = base / "sqlite" / "app.db"
        settings.uploads_dir = base / "uploads"
        settings.documents_dir = base / "documents"
        settings.ensure_dirs()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_project_persists_across_store_restart(self) -> None:
        store1 = AppStore()
        created = store1.create_project(
            {
                "name": "SQLite 持久化验证",
                "customerName": "测试业主",
            }
        )
        store1.complete_directory_generation(created["id"], {})

        store2 = AppStore()
        project = store2.get_project(created["id"])
        directory = store2.get_directory_state(created["id"])

        self.assertEqual(project["name"], "SQLite 持久化验证")
        self.assertEqual(directory["status"], "completed")
        self.assertTrue(settings.sqlite_path.exists())

    def test_project_id_continues_after_restart(self) -> None:
        store1 = AppStore()
        first = store1.create_project({"name": "项目一"})

        store2 = AppStore()
        second = store2.create_project({"name": "项目二"})

        self.assertEqual(first["id"], "PRJ-0001")
        self.assertEqual(second["id"], "PRJ-0002")


if __name__ == "__main__":
    unittest.main()
