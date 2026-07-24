from __future__ import annotations

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.material_certificate_time import migrate_certificate_time_scopes_on_path_change
from app.services.material_folder_scope import (
    is_raw_folder_move_protected_path,
    is_raw_folder_rename_protected_path,
)
from app.services.material_move_operations import _relocate_folder_subtree, rename_raw_folder
from app.services.peripheral import PeripheralError
from app.services.technical_material_store import TechnicalMaterialStore
from app.services.technical_wiki_preview_generation import PREVIEW_EXT_FIELD, _preview_signature


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return list(self._value)


class IdentityFolderProtectionTests(IsolatedAsyncioTestCase):
    def test_identity_directories_are_rename_protected(self) -> None:
        identity_paths = [
            "技术标/客户定制/华能集团",
            "技术标/项目定制/PRJ-001",
            "商务标/客户素材/华能集团",
            "商务标/项目素材/PRJ-001",
        ]
        for path in identity_paths:
            with self.subTest(path=path):
                self.assertTrue(is_raw_folder_rename_protected_path(path))
                self.assertTrue(is_raw_folder_move_protected_path(path))

    async def test_rename_raw_folder_rejects_identity_directory(self) -> None:
        folder = SimpleNamespace(
            id=1,
            path="技术标/项目定制/PRJ-001",
            name="PRJ-001",
            bid_type="技术标",
            tier="project",
            project_id="PRJ-001",
        )
        session = _ScalarResult(folder)

        with patch(
            "app.services.material_move_operations.async_session",
            return_value=session,
        ):
            with self.assertRaises(PeripheralError) as context:
                await rename_raw_folder(
                    path="技术标/项目定制/PRJ-001",
                    new_name="PRJ-002",
                    bid_type="技术标",
                    ensure_runtime_tables=AsyncMock(),
                    raw_object_key=lambda path, name: f"{path}/{name}",
                    infer_material_tier_from_folder=lambda folder: "project",
                    raw_tree=AsyncMock(return_value={"tree": []}),
                )

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.code, "RAW_FOLDER_RENAME_PROTECTED")


class RelocateFolderSubtreeLockTests(IsolatedAsyncioTestCase):
    async def test_relocate_rejects_duplicate_target_after_locking(self) -> None:
        source = SimpleNamespace(
            id=1,
            path="技术标/客户定制/华能集团",
            name="华能集团",
            bid_type="技术标",
            tier="customer",
            project_id=None,
            customer_name="华能集团",
            parent_id=10,
        )
        existing_target = SimpleNamespace(path="技术标/客户定制/华能集团新")

        class _LockSession:
            def __init__(self):
                self.locks = []
                self.statements = []
                self._folder_query_count = 0

            async def execute(self, statement, parameters=None):
                self.statements.append(str(statement))
                stmt = str(statement)
                if "pg_advisory_xact_lock" in stmt:
                    self.locks.append(parameters)
                    return _ScalarResult(None)
                if "raw_folders.path" in stmt.lower():
                    self._folder_query_count += 1
                    # 第一次 raw_folders.path 查询是目标目录存在性检查
                    if self._folder_query_count == 1:
                        return _ScalarResult(existing_target)
                    return _ScalarResult([])
                return _ScalarResult(None)

            async def commit(self):
                return None

        session = _LockSession()

        with self.assertRaises(PeripheralError) as context:
            await _relocate_folder_subtree(
                session,
                source=source,
                target_parent=SimpleNamespace(
                    id=10,
                    path="技术标/客户定制",
                    bid_type="技术标",
                    tier="customer",
                    project_id=None,
                    customer_name=None,
                ),
                next_root_path="技术标/客户定制/华能集团新",
                raw_object_key=lambda path, name: f"{path}/{name}",
                infer_material_tier_from_folder=lambda folder: "customer",
                rename=True,
            )

        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(context.exception.code, "RAW_FOLDER_EXISTS")
        self.assertTrue(any("pg_advisory_xact_lock" in s for s in session.statements))


class TagImportOverwriteTests(IsolatedAsyncioTestCase):
    async def test_raw_tag_import_commit_overwrite_replaces_tags(self) -> None:
        store = TechnicalMaterialStore()
        with patch.object(
            store,
            "set_index_tags",
            new=AsyncMock(return_value={"name": "file.docx", "tags": ["新标签"]}),
        ) as mock_set_tags:
            result = await store.raw_tag_import_commit(
                items=[{"fileId": "RAW-0001", "tags": ["新标签"]}],
                import_mode="overwrite",
            )

        self.assertEqual(len(result["succeeded"]), 1)
        mock_set_tags.assert_awaited_once_with("RAW-0001", ["新标签"], merge=False)

    async def test_raw_tag_import_commit_merge_merges_tags(self) -> None:
        store = TechnicalMaterialStore()
        with patch.object(
            store,
            "set_index_tags",
            new=AsyncMock(return_value={"name": "file.docx", "tags": ["旧标签", "新标签"]}),
        ) as mock_set_tags:
            result = await store.raw_tag_import_commit(
                items=[{"fileId": "RAW-0001", "tags": ["新标签"]}],
                import_mode="merge",
            )

        self.assertEqual(len(result["succeeded"]), 1)
        mock_set_tags.assert_awaited_once_with("RAW-0001", ["新标签"], merge=True)


class CertificateScopeMigrationTests(IsolatedAsyncioTestCase):
    async def test_certificate_scopes_migrated_on_path_change(self) -> None:
        initial_config = {
            "scopes": [
                {
                    "path": "技术标/项目定制/PRJ-001/证书",
                    "name": "证书",
                    "enabled": True,
                    "source": "manual",
                    "updatedAt": "2026-01-01T00:00:00",
                },
                {
                    "path": "技术标/标准文件/型式认证",
                    "name": "型式认证",
                    "enabled": True,
                    "source": "manual",
                    "updatedAt": "2026-01-01T00:00:00",
                },
            ]
        }
        written_config: dict | None = None

        def fake_read(_path):
            return initial_config

        def fake_write(_path, payload):
            nonlocal written_config
            written_config = payload

        with patch("app.services.material_certificate_time.read_json_file", side_effect=fake_read):
            with patch("app.services.material_certificate_time.write_json_file_atomic", side_effect=fake_write):
                migrate_certificate_time_scopes_on_path_change(
                    bid_type="技术标",
                    old_path="技术标/项目定制/PRJ-001",
                    new_path="技术标/项目定制/PRJ-002",
                )

        self.assertIsNotNone(written_config)
        scopes = {scope["path"]: scope for scope in written_config["scopes"]}
        self.assertEqual(scopes["技术标/项目定制/PRJ-002/证书"]["name"], "证书")
        self.assertEqual(scopes["技术标/标准文件/型式认证"]["name"], "型式认证")
        self.assertNotIn("技术标/项目定制/PRJ-001/证书", scopes)


class WikiPreviewCacheInvalidationTests(IsolatedAsyncioTestCase):
    def test_preview_signature_includes_folder_path(self) -> None:
        profile = {
            "headings": [{"title": "章节1"}],
            "paragraphs": ["段落1"],
            "tableCount": 0,
        }
        sig_old_path = _preview_signature("file.docx", profile, "技术标/项目定制/PRJ-001")
        sig_new_path = _preview_signature("file.docx", profile, "技术标/项目定制/PRJ-002")
        self.assertNotEqual(sig_old_path, sig_new_path)

    async def test_relocate_clears_tech_wiki_preview_cache(self) -> None:
        source = SimpleNamespace(
            id=1,
            path="技术标/项目定制/PRJ-001",
            name="PRJ-001",
            bid_type="技术标",
            tier="project",
            project_id="PRJ-001",
            customer_name=None,
            parent_id=10,
        )
        child_folder = SimpleNamespace(
            id=2,
            path="技术标/项目定制/PRJ-001/证书",
            name="证书",
            bid_type="技术标",
            tier="project",
            project_id="PRJ-001",
            customer_name=None,
            parent_id=1,
        )
        moved_file = SimpleNamespace(
            id=101,
            name="cert.docx",
            folder_id=2,
            minio_bucket="bucket",
            minio_key="技术标/项目定制/PRJ-001/证书/cert.docx",
            ext_fields={PREVIEW_EXT_FIELD: {"signature": "old", "preview": {"lead": "old"}}, "other": "keep"},
            folder=child_folder,
        )

        class _RelocateSession:
            def __init__(self):
                self.committed = False

            async def execute(self, statement, parameters=None):
                stmt = str(statement)
                if "pg_advisory_xact_lock" in stmt:
                    return _ScalarResult(None)
                if "raw_files" in stmt.lower() or "RawFile" in stmt:
                    return _ScalarResult([moved_file])
                if "raw_folders.path" in stmt.lower() and "like" not in stmt.lower() and "start" not in stmt.lower():
                    return _ScalarResult(None)
                if "raw_folders.path" in stmt.lower():
                    return _ScalarResult([source, child_folder])
                return _ScalarResult(None)

            async def commit(self):
                self.committed = True

        session = _RelocateSession()

        with patch("app.services.material_move_operations.minio_client") as mock_minio:
            with patch(
                "app.services.material_move_operations.migrate_certificate_time_scopes_on_path_change",
                new=MagicMock(),
            ):
                moved_count = await _relocate_folder_subtree(
                    session,
                    source=source,
                    target_parent=SimpleNamespace(
                        id=10,
                        path="技术标/项目定制",
                        bid_type="技术标",
                        tier="project",
                        project_id=None,
                        customer_name=None,
                    ),
                    next_root_path="技术标/项目定制/PRJ-002",
                    raw_object_key=lambda path, name: f"{path}/{name}",
                    infer_material_tier_from_folder=lambda folder: "project",
                    rename=True,
                )

        self.assertEqual(moved_count, 1)
        self.assertTrue(session.committed)
        self.assertNotIn(PREVIEW_EXT_FIELD, moved_file.ext_fields)
        self.assertEqual(moved_file.ext_fields.get("other"), "keep")
        mock_minio.copy_object.assert_called_once()
