from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.core.config import settings


def test_purge_fulltext_removes_only_canonical_material_history() -> None:
    from app.services import material_fulltext_artifacts

    bucket = str(settings.minio_buckets["materials"])
    with (
        patch.object(
            material_fulltext_artifacts.minio_client,
            "list_object_keys",
            return_value=[
                "parsed/RAW-0007/v1/fulltext.md",
                "parsed/RAW-0007/v3/fulltext.md",
                "parsed/RAW-0008/v1/fulltext.md",
            ],
        ) as list_mock,
        patch.object(material_fulltext_artifacts.minio_client, "remove_object") as remove_mock,
    ):
        removed_count = material_fulltext_artifacts.purge_material_fulltext_objects(
            7,
            3,
        )

    list_mock.assert_called_once_with(bucket, "parsed/RAW-0007/")
    assert removed_count == 2
    assert {call.args for call in remove_mock.call_args_list} == {
        (bucket, "parsed/RAW-0007/v1/fulltext.md"),
        (bucket, "parsed/RAW-0007/v3/fulltext.md"),
    }


def test_purge_fulltext_listing_failure_still_removes_current_version() -> None:
    from app.services import material_fulltext_artifacts

    bucket = str(settings.minio_buckets["materials"])
    with (
        patch.object(
            material_fulltext_artifacts.minio_client,
            "list_object_keys",
            side_effect=RuntimeError("minio unavailable"),
        ),
        patch.object(material_fulltext_artifacts.minio_client, "remove_object") as remove_mock,
    ):
        removed_count = material_fulltext_artifacts.purge_material_fulltext_objects(
            7,
            3,
        )

    assert removed_count == 1
    remove_mock.assert_called_once_with(bucket, "parsed/RAW-0007/v3/fulltext.md")


def test_purge_fulltext_continues_after_one_removal_failure() -> None:
    from app.services import material_fulltext_artifacts

    attempted: list[str] = []

    def remove_object(_bucket: str, key: str) -> None:
        attempted.append(key)
        if "/v2/" in key:
            raise RuntimeError("temporary remove failure")

    with (
        patch.object(
            material_fulltext_artifacts.minio_client,
            "list_object_keys",
            return_value=[
                "parsed/RAW-0007/v1/fulltext.md",
                "parsed/RAW-0007/v2/fulltext.md",
            ],
        ),
        patch.object(material_fulltext_artifacts.minio_client, "remove_object", side_effect=remove_object),
    ):
        removed_count = material_fulltext_artifacts.purge_material_fulltext_objects(
            7,
            2,
        )

    assert attempted == [
        "parsed/RAW-0007/v1/fulltext.md",
        "parsed/RAW-0007/v2/fulltext.md",
    ]
    assert removed_count == 1


def test_cleanup_does_not_depend_on_current_file_extension() -> None:
    from app.services import material_fulltext_artifacts

    with (
        patch.object(
            material_fulltext_artifacts.minio_client,
            "list_object_keys",
            return_value=["parsed/RAW-0007/v1/fulltext.md"],
        ) as list_mock,
        patch.object(material_fulltext_artifacts.minio_client, "remove_object") as remove_mock,
    ):
        removed_count = material_fulltext_artifacts.purge_material_fulltext_objects(
            7,
            3,
        )

    assert removed_count == 2
    list_mock.assert_called_once()
    assert remove_mock.call_count == 2


def test_overwrite_cleanup_does_not_remove_newer_version() -> None:
    from app.services import material_fulltext_artifacts

    with (
        patch.object(
            material_fulltext_artifacts.minio_client,
            "list_object_keys",
            return_value=[
                "parsed/RAW-0007/v1/fulltext.md",
                "parsed/RAW-0007/v2/fulltext.md",
                "parsed/RAW-0007/v3/fulltext.md",
            ],
        ),
        patch.object(material_fulltext_artifacts.minio_client, "remove_object") as remove_mock,
    ):
        material_fulltext_artifacts.purge_material_fulltext_objects(
            7,
            2,
            max_source_version=2,
        )

    removed_keys = {call.args[1] for call in remove_mock.call_args_list}
    assert removed_keys == {
        "parsed/RAW-0007/v1/fulltext.md",
        "parsed/RAW-0007/v2/fulltext.md",
    }


class _DeleteSession:
    def __init__(self, item: SimpleNamespace, events: list[str]) -> None:
        self.item = item
        self.events = events

    async def __aenter__(self) -> "_DeleteSession":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, _statement: object) -> object:
        return SimpleNamespace(scalar_one_or_none=lambda: self.item)

    async def delete(self, _item: object) -> None:
        self.events.append("db-delete")

    async def commit(self) -> None:
        self.events.append("db-commit")

    async def refresh(self, _item: object, **_kwargs: object) -> None:
        return None


class _FolderDeleteSession(_DeleteSession):
    def __init__(
        self,
        folder: SimpleNamespace,
        item: SimpleNamespace,
        events: list[str],
        *,
        fail_commit: bool = False,
    ) -> None:
        super().__init__(item, events)
        self.folder = folder
        self.execute_count = 0
        self.fail_commit = fail_commit

    async def execute(self, _statement: object) -> object:
        self.execute_count += 1
        if self.execute_count == 1:
            return SimpleNamespace(scalar_one_or_none=lambda: self.folder)
        values = [self.folder] if self.execute_count == 2 else [self.item]
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: values))

    async def commit(self) -> None:
        self.events.append("db-commit")
        if self.fail_commit:
            raise RuntimeError("commit failed")


def test_delete_raw_file_cleans_fulltext_only_after_commit() -> None:
    from app.services import material_raw_lifecycle_operations

    events: list[str] = []
    item = SimpleNamespace(
        id=7,
        version=3,
        name="授权书.pdf",
        folder=SimpleNamespace(bid_type="技术标"),
        to_dict=lambda: {"id": "RAW-0007"},
    )

    async def purge_raw(_session: object, _item: object) -> None:
        events.append("raw-purge")

    def purge_fulltext(raw_file_id: int, source_version: int) -> None:
        assert (raw_file_id, source_version) == (7, 3)
        events.append("fulltext-purge")

    with (
        patch.object(
            material_raw_lifecycle_operations,
            "async_session",
            return_value=_DeleteSession(item, events),
        ),
        patch.object(material_raw_lifecycle_operations, "raw_file_matches_bid_type", return_value=True),
        patch.object(
            material_raw_lifecycle_operations,
            "purge_material_fulltext_objects",
            side_effect=purge_fulltext,
        ),
    ):
        result = asyncio.run(
            material_raw_lifecycle_operations.delete_raw_file(
                file_id="RAW-0007",
                bid_type="技术标",
                ensure_runtime_tables=AsyncMock(),
                purge_raw_file_objects=purge_raw,
            )
        )

    assert result["item"] == {"id": "RAW-0007"}
    assert events == ["raw-purge", "db-delete", "db-commit", "fulltext-purge"]


def test_delete_raw_folder_cleans_fulltext_only_after_commit() -> None:
    from app.services import material_raw_lifecycle_operations

    events: list[str] = []
    folder = SimpleNamespace(
        id=11,
        path="技术标/项目定制/PRJ-1",
        project_id="PRJ-1",
        bid_type="技术标",
        tier="project",
    )
    item = SimpleNamespace(id=7, version=3, name="已改名素材.docx")
    session = _FolderDeleteSession(folder, item, events)

    async def purge_raw(_session: object, _item: object) -> None:
        events.append("raw-purge")

    async def raw_tree() -> dict[str, object]:
        return {"tree": []}

    with (
        patch.object(material_raw_lifecycle_operations, "async_session", return_value=session),
        patch.object(material_raw_lifecycle_operations, "raw_folder_matches_bid_type", return_value=True),
        patch.object(material_raw_lifecycle_operations, "is_raw_material_protected_folder_path", return_value=False),
        patch.object(
            material_raw_lifecycle_operations,
            "purge_material_fulltext_objects",
            side_effect=lambda *_args: events.append("fulltext-purge"),
        ),
    ):
        result = asyncio.run(
            material_raw_lifecycle_operations.delete_raw_folder(
                path=folder.path,
                bid_type="技术标",
                ensure_runtime_tables=AsyncMock(),
                purge_raw_file_objects=purge_raw,
                mark_default_folder_deleted=AsyncMock(),
                raw_tree=raw_tree,
            )
        )

    assert result["deletedFileCount"] == 1
    assert events[-2:] == ["db-commit", "fulltext-purge"]


def test_delete_raw_folder_commit_failure_preserves_fulltext() -> None:
    from app.services import material_raw_lifecycle_operations

    events: list[str] = []
    folder = SimpleNamespace(
        id=11,
        path="技术标/项目定制/PRJ-1",
        project_id="PRJ-1",
        bid_type="技术标",
        tier="project",
    )
    item = SimpleNamespace(id=7, version=3, name="授权书.pdf")
    session = _FolderDeleteSession(folder, item, events, fail_commit=True)

    with (
        patch.object(material_raw_lifecycle_operations, "async_session", return_value=session),
        patch.object(material_raw_lifecycle_operations, "raw_folder_matches_bid_type", return_value=True),
        patch.object(material_raw_lifecycle_operations, "is_raw_material_protected_folder_path", return_value=False),
        patch.object(material_raw_lifecycle_operations, "purge_material_fulltext_objects") as purge_fulltext,
    ):
        try:
            asyncio.run(
                material_raw_lifecycle_operations.delete_raw_folder(
                    path=folder.path,
                    bid_type="技术标",
                    ensure_runtime_tables=AsyncMock(),
                    purge_raw_file_objects=AsyncMock(),
                    mark_default_folder_deleted=AsyncMock(),
                    raw_tree=AsyncMock(return_value={"tree": []}),
                )
            )
        except RuntimeError as exc:
            assert str(exc) == "commit failed"
        else:  # pragma: no cover - regression guard
            raise AssertionError("folder deletion should expose the commit failure")

    purge_fulltext.assert_not_called()


class _MoveSession:
    def __init__(
        self,
        item: SimpleNamespace,
        destination: SimpleNamespace,
        existing: SimpleNamespace,
        events: list[str],
    ) -> None:
        self.values = [item, destination, existing]
        self.execute_count = 0
        self.events = events

    async def __aenter__(self) -> "_MoveSession":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, _statement: object) -> object:
        value = self.values[min(self.execute_count, len(self.values) - 1)]
        self.execute_count += 1
        return SimpleNamespace(scalar_one_or_none=lambda: value)

    async def delete(self, _item: object) -> None:
        self.events.append("db-delete")

    async def commit(self) -> None:
        self.events.append("db-commit")

    async def refresh(self, _item: object, **_kwargs: object) -> None:
        return None


def test_move_overwrite_cleans_replaced_file_fulltext_after_commit() -> None:
    from app.services import material_move_operations

    events: list[str] = []
    source_folder = SimpleNamespace(path="技术标/标准文件/旧", bid_type="技术标")
    destination = SimpleNamespace(
        id=22,
        path="技术标/标准文件/新",
        bid_type="技术标",
        project_id=None,
        customer_name="",
    )
    item = SimpleNamespace(
        id=7,
        name="授权书.pdf",
        version=1,
        minio_bucket="bid-materials",
        minio_key="raw/source.pdf",
        folder_id=11,
        folder=source_folder,
        ext_fields={},
        to_dict=lambda: {"id": "RAW-0007"},
    )
    existing = SimpleNamespace(id=8, name="授权书.pdf", version=4)
    move_session = _MoveSession(item, destination, existing, events)
    verify_session = _DeleteSession(item, events)

    async def purge_raw(_session: object, _item: object) -> None:
        events.append("raw-purge")

    def purge_fulltext(raw_file_id: int, source_version: int) -> None:
        assert (raw_file_id, source_version) == (8, 4)
        events.append("fulltext-purge")

    with (
        patch.object(
            material_move_operations,
            "async_session",
            side_effect=[move_session, verify_session],
        ),
        patch.object(material_move_operations, "raw_file_matches_bid_type", return_value=True),
        patch.object(material_move_operations, "raw_folder_matches_bid_type", return_value=True),
        patch.object(
            material_move_operations,
            "build_raw_move_file_ext_fields",
            side_effect=lambda ext, **_kwargs: ext,
        ),
        patch.object(
            material_move_operations,
            "purge_material_fulltext_objects",
            side_effect=purge_fulltext,
        ),
    ):
        result = asyncio.run(
            material_move_operations.move_raw_file(
                file_id="RAW-0007",
                target_path=destination.path,
                bid_type="技术标",
                on_conflict="overwrite",
                ensure_runtime_tables=AsyncMock(),
                raw_object_key=lambda _path, _name: "raw/source.pdf",
                purge_raw_file_objects=purge_raw,
                infer_material_tier_from_folder=lambda _folder: "standard",
            )
        )

    assert result["item"] == {"id": "RAW-0007"}
    assert events[:4] == ["raw-purge", "db-delete", "db-commit", "fulltext-purge"]
