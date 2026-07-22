from __future__ import annotations

import asyncio
import os
import unittest
from collections import defaultdict
from contextvars import ContextVar
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.core.config import settings
from app.models import async_session
from app.models.materials import RawFile, RawFolder
from app.services.material_raw_folder_lock import (
    lock_raw_folder_path as acquire_raw_folder_path_lock,
    raw_folder_path_lock_key,
)
from app.services.material_raw_folder_operations import RawFolderOperations
from app.services.material_runtime_tables import ensure_material_runtime_tables
from app.services.material_store import material_store
from app.services.material_upload_operations import (
    _normalize_relative_directory,
    _sorted_directory_prefixes,
)
from app.services.minio_client import minio_client


class RawUploadDirectoryPlanningTests(unittest.TestCase):
    def test_all_prefixes_use_one_stable_global_order(self) -> None:
        self.assertEqual(
            _sorted_directory_prefixes({"B", "A/deep", "A", "B/deep"}),
            ["A", "B", "A/deep", "B/deep"],
        )

    def test_relative_directory_segments_are_normalized_before_mapping(self) -> None:
        self.assertEqual(_normalize_relative_directory(" A:B / C?D /.../"), "A-B/C-D")
        self.assertEqual(_normalize_relative_directory(".hidden/file"), "hidden/file")


@unittest.skipUnless(os.getenv("BID_RUN_INTEGRATION") == "1", "requires PostgreSQL")
@pytest.mark.integration
class MaterialRawFolderConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.operations = RawFolderOperations(ensure_runtime_tables=ensure_material_runtime_tables)
        self.base_name = f"advisory-lock-{uuid4().hex}"
        self.base_path = f"技术标/标准文件/{self.base_name}"

        async with async_session() as session:
            await ensure_material_runtime_tables(session)
            root = await self.operations.ensure_folder_path(
                session,
                "技术标",
                None,
                "standard",
                "技术标",
                None,
                1,
            )
            standard_root = await self.operations.ensure_folder_path(
                session,
                "标准文件",
                root.id,
                "standard",
                "技术标",
                None,
                1,
                customer_name="平台标准",
            )
            base_folder = await self.operations.ensure_folder_path(
                session,
                self.base_name,
                standard_root.id,
                "standard",
                "技术标",
                None,
                0,
                customer_name="平台标准",
            )
            await session.commit()
            self.base_id = int(base_folder.id)

        self.addAsyncCleanup(self._delete_base_folder)

    async def _delete_base_folder(self) -> None:
        async with async_session() as session:
            await session.execute(delete(RawFolder).where(RawFolder.path == self.base_path))
            await session.commit()

    async def test_concurrent_ensure_same_path_creates_one_folder(self) -> None:
        child_name = "same-path"
        child_path = f"{self.base_path}/{child_name}"
        lock_barrier = asyncio.Barrier(2)
        lock_calls = 0

        async def synchronized_lock(session, folder_path: str) -> None:
            nonlocal lock_calls
            if folder_path == child_path:
                lock_calls += 1
                await lock_barrier.wait()
            await acquire_raw_folder_path_lock(session, folder_path)

        async def ensure_child() -> int:
            async with async_session() as session:
                folder = await self.operations.ensure_folder_path(
                    session,
                    child_name,
                    self.base_id,
                    "standard",
                    "技术标",
                    None,
                    0,
                    customer_name="平台标准",
                )
                await session.commit()
                return int(folder.id)

        with patch(
            "app.services.material_raw_folder_operations.lock_raw_folder_path",
            new=synchronized_lock,
        ):
            folder_ids = await asyncio.wait_for(
                asyncio.gather(ensure_child(), ensure_child()),
                timeout=8,
            )

        async with async_session() as session:
            count = await session.scalar(select(func.count(RawFolder.id)).where(RawFolder.path == child_path))

        self.assertEqual(lock_calls, 2)
        self.assertEqual(folder_ids[0], folder_ids[1])
        self.assertEqual(count, 1)

    async def test_inverse_batch_directory_order_does_not_deadlock(self) -> None:
        request_name: ContextVar[str] = ContextVar("request_name", default="")
        lock_paths: dict[str, list[str]] = defaultdict(list)
        first_lock_barrier = asyncio.Barrier(2)

        async def synchronized_lock(session, folder_path: str) -> None:
            current_request = request_name.get()
            if folder_path.startswith(f"{self.base_path}/"):
                lock_paths[current_request].append(folder_path)
                if len(lock_paths[current_request]) == 1:
                    await first_lock_barrier.wait()
            await acquire_raw_folder_path_lock(session, folder_path)

        async def upload(request_id: str, files: list[dict[str, object]]) -> dict[str, object]:
            token = request_name.set(request_id)
            try:
                return await material_store.raw_upload(
                    target_path=self.base_path,
                    bid_type="技术标",
                    files=files,
                )
            finally:
                request_name.reset(token)

        request_a = [
            {"name": "a.pdf", "relativePath": "B/a.pdf", "data": b"%PDF-a"},
            {"name": "b.pdf", "relativePath": "A/deep/b.pdf", "data": b"%PDF-b"},
        ]
        request_b = [
            {"name": "c.pdf", "relativePath": "A/c.pdf", "data": b"%PDF-c"},
            {"name": "d.pdf", "relativePath": "B/deep/d.pdf", "data": b"%PDF-d"},
        ]

        with (
            patch(
                "app.services.material_raw_folder_operations.lock_raw_folder_path",
                new=synchronized_lock,
            ),
            patch.object(minio_client, "put_object", side_effect=lambda _bucket, key, _data, **_kwargs: key),
            patch.object(minio_client, "remove_object"),
        ):
            results = await asyncio.wait_for(
                asyncio.gather(
                    upload("request-a", request_a),
                    upload("request-b", request_b),
                ),
                timeout=8,
            )

        expected_paths = {
            f"{self.base_path}/A",
            f"{self.base_path}/B",
            f"{self.base_path}/A/deep",
            f"{self.base_path}/B/deep",
        }
        async with async_session() as session:
            folder_rows = (
                await session.execute(select(RawFolder.path).where(RawFolder.path.in_(expected_paths)))
            ).scalars().all()
            file_count = await session.scalar(
                select(func.count(RawFile.id))
                .join(RawFolder)
                .where(RawFolder.path.startswith(f"{self.base_path}/"))
            )

        self.assertEqual([len(result["items"]) for result in results], [2, 2])
        self.assertEqual(set(folder_rows), expected_paths)
        self.assertEqual(len(folder_rows), len(expected_paths))
        self.assertEqual(file_count, 4)
        self.assertEqual(lock_paths["request-a"][0], f"{self.base_path}/A")
        self.assertEqual(lock_paths["request-b"][0], f"{self.base_path}/A")

    async def test_minio_upload_starts_after_folder_lock_is_released(self) -> None:
        import psycopg

        folder_path = f"{self.base_path}/release-check"
        lock_available: list[bool] = []
        database_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)

        def inspect_lock(_bucket: str, key: str, _data: bytes, **_kwargs) -> str:
            with psycopg.connect(database_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_try_advisory_xact_lock(hashtext(%s))",
                        (raw_folder_path_lock_key(folder_path),),
                    )
                    lock_available.append(bool(cursor.fetchone()[0]))
            return key

        with (
            patch.object(minio_client, "put_object", side_effect=inspect_lock),
            patch.object(minio_client, "remove_object"),
        ):
            result = await material_store.raw_upload(
                target_path=self.base_path,
                bid_type="技术标",
                files=[
                    {
                        "name": "release.pdf",
                        "relativePath": "release-check/release.pdf",
                        "data": b"%PDF-release",
                    }
                ],
            )

        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(lock_available, [True])

    async def test_missing_scoped_target_keeps_implicit_directory_creation(self) -> None:
        target_path = f"{self.base_path}/new-target"
        expected_folder_path = f"{target_path}/nested"

        with (
            patch.object(minio_client, "put_object", side_effect=lambda _bucket, key, _data, **_kwargs: key),
            patch.object(minio_client, "remove_object"),
        ):
            result = await material_store.raw_upload(
                target_path=target_path,
                bid_type="技术标",
                files=[
                    {
                        "name": "nested.pdf",
                        "relativePath": "nested/nested.pdf",
                        "data": b"%PDF-nested",
                    }
                ],
            )

        async with async_session() as session:
            folder_count = await session.scalar(
                select(func.count(RawFolder.id)).where(RawFolder.path == expected_folder_path)
            )

        self.assertEqual(result["items"][0]["folderPath"], expected_folder_path)
        self.assertEqual(folder_count, 1)
