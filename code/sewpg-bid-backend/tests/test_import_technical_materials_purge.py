from __future__ import annotations

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from sqlalchemy import Delete, Select

from app.models.materials import RawFile, RawFileVersion, RawFolder
from scripts import import_technical_materials as script


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalars(self):
        return self

    def all(self):
        return list(self._value)


class _PurgeSession:
    """按 select 的实体类型返回预置数据；delete 语句只记录不执行。"""

    def __init__(self, folders, files, versions):
        self._folders = folders
        self._files = files
        self._versions = versions
        self.deleted_tables = []

    async def execute(self, statement, *_args, **_kwargs):
        if isinstance(statement, Select):
            entity = statement.column_descriptions[0].get("entity")
            if entity is RawFolder:
                return _ScalarResult(self._folders)
            if entity is RawFile:
                return _ScalarResult(self._files)
            if entity is RawFileVersion:
                return _ScalarResult(self._versions)
            raise AssertionError(f"unexpected select: {statement}")
        if isinstance(statement, Delete):
            self.deleted_tables.append(statement.table.name)
            return _ScalarResult([])
        raise AssertionError(f"unexpected statement: {statement}")

    async def commit(self):
        return None


class _SessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _build_purge_fixture():
    folder = SimpleNamespace(id=11, path="技术标/标准文件")
    raw_file = SimpleNamespace(
        id=101,
        minio_bucket="bid-materials",
        minio_key="raw/技术标/标准文件/sample.docx",
        ext_fields={
            "cleanedMinioBucket": "bid-materials",
            "cleanedMinioKey": "cleaned/RAW-0101/v1/sample.docx",
        },
    )
    version = SimpleNamespace(file_id=101, minio_key="raw-versions/RAW-0101/v1/sample.docx")
    return _PurgeSession([folder], [raw_file], [version])


class PurgeTechnicalMaterialStoreTests(IsolatedAsyncioTestCase):
    async def test_purge_removes_raw_cleaned_and_version_objects(self) -> None:
        """purge 必须同时清掉原始对象、cleanedMinioKey 清洗产物和 raw-versions/ 历史版本。"""
        session = _build_purge_fixture()
        with (
            patch.object(script, "async_session", return_value=_SessionContext(session)),
            patch.object(script, "ensure_material_runtime_tables", new=AsyncMock()),
            patch("app.services.material_raw_object_operations.minio_client") as mock_minio,
        ):
            await script._purge_technical_material_store()

        removed = {(call.args[0], call.args[1]) for call in mock_minio.remove_object.call_args_list}
        self.assertEqual(
            removed,
            {
                ("bid-materials", "raw/技术标/标准文件/sample.docx"),
                ("bid-materials", "cleaned/RAW-0101/v1/sample.docx"),
                ("bid-materials", "raw-versions/RAW-0101/v1/sample.docx"),
            },
        )
        # 三类表记录都要删掉：版本、文件、目录。
        self.assertIn("raw_file_versions", session.deleted_tables)
        self.assertIn("raw_files", session.deleted_tables)
        self.assertIn("raw_folders", session.deleted_tables)

    async def test_purge_tolerates_missing_minio_objects(self) -> None:
        """单个对象缺失只告警，不阻断后续记录清理。"""
        session = _build_purge_fixture()
        with (
            patch.object(script, "async_session", return_value=_SessionContext(session)),
            patch.object(script, "ensure_material_runtime_tables", new=AsyncMock()),
            patch("app.services.material_raw_object_operations.minio_client") as mock_minio,
        ):
            mock_minio.remove_object.side_effect = Exception("NoSuchKey")
            await script._purge_technical_material_store()

        self.assertEqual(mock_minio.remove_object.call_count, 3)
        self.assertIn("raw_files", session.deleted_tables)
