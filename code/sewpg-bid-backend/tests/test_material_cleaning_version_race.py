from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from docx import Document


class _StatusSession:
    def __init__(self) -> None:
        self.original = SimpleNamespace(
            id=7,
            version=2,
            ext_fields={"cleanStatus": "pending"},
            folder=None,
        )
        self.current = SimpleNamespace(id=7, version=3, ext_fields={"cleanStatus": "pending"}, folder=None)
        self.execute_count = 0
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def __aenter__(self) -> "_StatusSession":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, _statement: object) -> object:
        self.execute_count += 1
        if self.execute_count == 1:
            return SimpleNamespace(scalar_one_or_none=lambda: self.original)
        if self.execute_count == 2:
            return SimpleNamespace(rowcount=0)
        return SimpleNamespace(scalar_one_or_none=lambda: self.current)


class _RawFileSession:
    def __init__(self, item: SimpleNamespace) -> None:
        self.item = item

    async def __aenter__(self) -> "_RawFileSession":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, _statement: object) -> object:
        return SimpleNamespace(scalar_one_or_none=lambda: self.item)


class _UploadItem(SimpleNamespace):
    def to_dict(self) -> dict[str, object]:
        return {
            "id": f"RAW-{self.id:04d}",
            "version": self.version,
            "cleanStatus": self.ext_fields.get("cleanStatus"),
        }


class _UploadSession:
    def __init__(self, folder: SimpleNamespace, item: _UploadItem) -> None:
        self.folder = folder
        self.item = item
        self.execute_count = 0
        self.statements: list[str] = []
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def __aenter__(self) -> "_UploadSession":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, _statement: object) -> object:
        self.execute_count += 1
        self.statements.append(str(_statement))
        value = self.folder if self.execute_count == 1 else self.item
        return SimpleNamespace(scalar_one_or_none=lambda: value)


def _write_docx(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = Document()
    document.add_paragraph(text)
    document.save(path)


def test_versioned_raw_object_key_keeps_overwrite_source_immutable() -> None:
    from app.services.material_raw_object_operations import raw_version_object_key

    assert raw_version_object_key(7, 3, "授权书.doc") == "raw-versions/RAW-0007/v3/授权书.doc"


def test_cleaned_object_key_is_deterministic_per_source_version() -> None:
    from app.services.material_cleaning import cleaned_object_key

    expected = "cleaned/RAW-0007/v3/授权书.docx"
    assert cleaned_object_key(7, "授权书.doc", source_version=3) == expected
    assert cleaned_object_key(7, "授权书.doc", source_version=3) == expected


def test_enqueue_cleaning_job_binds_source_version_and_uses_versioned_lock() -> None:
    from app.services.material_raw_object_operations import enqueue_cleaning_job

    with patch(
        "app.services.job_queue.enqueue_generation_job",
        return_value=SimpleNamespace(queued=True, job_id="job-v3", locked=False, unavailable=False),
    ) as enqueue_mock:
        result = enqueue_cleaning_job(
            7,
            source_version=3,
            source_bucket="materials",
            source_key="raw-versions/RAW-0007/v3/授权书.doc",
        )

    assert result["queued"] is True
    enqueue_mock.assert_called_once_with(
        "material_cleaning",
        "RAW-0007:v3",
        {
            "fileId": "RAW-0007",
            "sourceVersion": 3,
            "sourceBucket": "materials",
            "sourceKey": "raw-versions/RAW-0007/v3/授权书.doc",
        },
    )


def test_overwrite_ext_fields_discards_previous_cleaned_artifact() -> None:
    from app.services.material_upload_metadata import build_raw_upload_existing_ext_fields

    current = {
        "tags": ["保留标签"],
        "cleanStatus": "cleaned",
        "cleanedMinioBucket": "materials",
        "cleanedMinioKey": "cleaned/RAW-0007/old.docx",
        "cleanedFileName": "授权书.docx",
        "cleanedSize": 123,
        "cleanedSourceVersion": 2,
        "cleanedSourceKey": "raw-versions/RAW-0007/v2/授权书.doc",
        "cleanReport": {"schemaVersion": "v1"},
        "deepParseStatus": "parsed",
        "deepParseProfile": {"sourceKey": "cleaned/RAW-0007/old.docx"},
    }
    upload = {
        "cleanStatus": "pending",
        "cleanMessage": "等待清洗。",
        "sourceMinioKey": "raw-versions/RAW-0007/v3/授权书.doc",
    }

    result = build_raw_upload_existing_ext_fields(current, upload, last_action="overwrite")

    assert result["tags"] == ["保留标签"]
    assert result["cleanStatus"] == "pending"
    assert result["sourceMinioKey"] == "raw-versions/RAW-0007/v3/授权书.doc"
    assert "cleanedMinioKey" not in result
    assert "cleanedSourceVersion" not in result
    assert "cleanReport" not in result
    assert "deepParseStatus" not in result
    assert "deepParseProfile" not in result


def test_clean_status_cas_rejects_write_when_version_changes() -> None:
    from app.services import material_cleaning

    session = _StatusSession()
    with patch.object(material_cleaning, "async_session", return_value=session):
        result = asyncio.run(
            material_cleaning.set_material_clean_status(
                "RAW-0007",
                "cleaned",
                "旧任务完成",
                source_version=2,
                extra={"cleanedMinioKey": "cleaned/RAW-0007/version-a.docx"},
            )
        )

    assert result == {
        "cleanStatus": "stale",
        "cleanMessage": "清洗任务对应的素材版本已过期。",
        "sourceVersion": 2,
        "currentVersion": 3,
    }
    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
    assert session.original.ext_fields == {"cleanStatus": "pending"}


def test_worker_rejects_stale_payload_before_processing() -> None:
    from app.services import material_cleaning

    item = SimpleNamespace(
        id=7,
        name="授权书.doc",
        minio_bucket="materials",
        minio_key="raw-versions/RAW-0007/v3/授权书.doc",
        version=3,
        ext_fields={"cleanStatus": "pending"},
        folder=None,
    )
    prepare_mock = AsyncMock()
    requeue_mock = AsyncMock(return_value={"queued": True})
    with (
        patch.object(material_cleaning, "async_session", return_value=_RawFileSession(item)),
        patch.object(material_cleaning, "_prepare_cleaning_source", new=prepare_mock),
        patch.object(material_cleaning, "_requeue_latest_cleaning", new=requeue_mock, create=True),
    ):
        result = asyncio.run(
            material_cleaning.clean_material_file(
                "RAW-0007",
                {
                    "sourceVersion": 2,
                    "sourceBucket": "materials",
                    "sourceKey": "raw-versions/RAW-0007/v2/授权书.doc",
                },
            )
        )

    assert result["cleanStatus"] == "stale"
    assert result["sourceVersion"] == 2
    assert result["currentVersion"] == 3
    prepare_mock.assert_not_awaited()
    requeue_mock.assert_awaited_once_with("RAW-0007", stale_version=2)


def test_worker_cancels_legacy_unversioned_job_after_overwrite() -> None:
    from app.services import material_cleaning

    item = SimpleNamespace(
        id=7,
        name="授权书.doc",
        minio_bucket="materials",
        minio_key="raw-versions/RAW-0007/v3/授权书.doc",
        version=3,
        ext_fields={"cleanStatus": "pending"},
        folder=None,
    )
    prepare_mock = AsyncMock()
    requeue_mock = AsyncMock(return_value={"queued": True})
    with (
        patch.object(material_cleaning, "async_session", return_value=_RawFileSession(item)),
        patch.object(material_cleaning, "_prepare_cleaning_source", new=prepare_mock),
        patch.object(material_cleaning, "_requeue_latest_cleaning", new=requeue_mock),
    ):
        result = asyncio.run(material_cleaning.clean_material_file("RAW-0007", {"fileId": "RAW-0007"}))

    assert result["cleanStatus"] == "stale"
    assert result["currentVersion"] == 3
    prepare_mock.assert_not_awaited()
    requeue_mock.assert_awaited_once_with("RAW-0007", stale_version=0)


def test_worker_uses_current_key_after_same_version_move() -> None:
    from app.services import material_cleaning

    current_key = "raw/技术标/项目定制/PRJ-1/新目录/授权书.doc"
    item = SimpleNamespace(
        id=7,
        name="授权书.doc",
        minio_bucket="materials",
        minio_key=current_key,
        version=2,
        ext_fields={"cleanStatus": "pending"},
        folder=None,
    )
    status_mock = AsyncMock(
        side_effect=[
            {"cleanStatus": "cleaning"},
            {"cleanStatus": "failed", "cleanMessage": "素材原件读取失败"},
        ]
    )
    prepare_mock = AsyncMock(side_effect=RuntimeError("停止在源文件读取"))
    requeue_mock = AsyncMock()
    with (
        tempfile.TemporaryDirectory() as tmp,
        patch.object(material_cleaning, "async_session", return_value=_RawFileSession(item)),
        patch.object(material_cleaning, "set_material_clean_status", new=status_mock),
        patch.object(material_cleaning, "_skill_driver_path", return_value=Path(tmp)),
        patch.object(material_cleaning, "_prepare_cleaning_source", new=prepare_mock),
        patch.object(material_cleaning, "_requeue_latest_cleaning", new=requeue_mock),
    ):
        result = asyncio.run(
            material_cleaning.clean_material_file(
                "RAW-0007",
                {
                    "sourceVersion": 2,
                    "sourceBucket": "materials",
                    "sourceKey": "raw/技术标/项目定制/PRJ-1/旧目录/授权书.doc",
                },
            )
        )

    assert result["cleanStatus"] == "failed"
    assert prepare_mock.await_args.kwargs["source_key"] == current_key
    requeue_mock.assert_not_awaited()


def test_stale_final_write_removes_artifact_and_requeues_latest() -> None:
    from app.services import material_cleaning

    item = SimpleNamespace(
        id=7,
        name="授权书.doc",
        minio_bucket="materials",
        minio_key="raw-versions/RAW-0007/v2/授权书.doc",
        version=2,
        ext_fields={"cleanStatus": "pending"},
        folder=None,
    )
    status_mock = AsyncMock(
        side_effect=[
            {"cleanStatus": "cleaning"},
            {
                "cleanStatus": "stale",
                "cleanMessage": "清洗任务对应的素材版本已过期。",
                "sourceVersion": 2,
                "currentVersion": 3,
            },
        ]
    )
    requeue_mock = AsyncMock(return_value={"queued": True})

    async def prepare_source(**kwargs: object) -> Path:
        source_dir = kwargs["source_dir"]
        assert isinstance(source_dir, Path)
        target = source_dir / "授权书.docx"
        _write_docx(target, "版本 A")
        return target

    def run_cleaner(args: list[str], **_kwargs: object) -> SimpleNamespace:
        output_dir = Path(args[args.index("--output-dir") + 1])
        _write_docx(output_dir / "授权书.docx", "版本 A 清洗稿")
        return SimpleNamespace(returncode=0, stdout="[OK] 授权书.docx (清洗完成)", stderr="")

    with (
        tempfile.TemporaryDirectory() as tmp,
        patch.object(material_cleaning, "async_session", return_value=_RawFileSession(item)),
        patch.object(material_cleaning, "set_material_clean_status", new=status_mock),
        patch.object(material_cleaning, "_prepare_cleaning_source", new=AsyncMock(side_effect=prepare_source)),
        patch.object(material_cleaning, "_skill_driver_path", return_value=Path(tmp)),
        patch.object(material_cleaning.subprocess, "run", side_effect=run_cleaner),
        patch.object(material_cleaning.minio_client, "upload_file") as upload_mock,
        patch.object(material_cleaning.minio_client, "remove_object") as remove_mock,
        patch.object(material_cleaning, "_requeue_latest_cleaning", new=requeue_mock, create=True),
    ):
        result = asyncio.run(
            material_cleaning.clean_material_file(
                "RAW-0007",
                {
                    "sourceVersion": 2,
                    "sourceBucket": "materials",
                    "sourceKey": "raw-versions/RAW-0007/v2/授权书.doc",
                },
            )
        )

    uploaded_bucket, uploaded_key = upload_mock.call_args.args[:2]
    assert result["cleanStatus"] == "stale"
    remove_mock.assert_called_once_with(uploaded_bucket, uploaded_key)
    requeue_mock.assert_awaited_once_with("RAW-0007", stale_version=2)
    assert all(call.kwargs["source_version"] == 2 for call in status_mock.await_args_list)


def test_stale_artifact_cleanup_retries_before_requeue() -> None:
    from app.services import material_cleaning

    requeue_mock = AsyncMock(return_value={"queued": True})
    with (
        patch.object(
            material_cleaning.minio_client,
            "remove_object",
            side_effect=[RuntimeError("temporary failure"), None],
        ) as remove_mock,
        patch.object(material_cleaning, "_requeue_latest_cleaning", new=requeue_mock),
    ):
        asyncio.run(
            material_cleaning._discard_stale_artifact(
                "RAW-0007",
                source_version=2,
                bucket="materials",
                key="cleaned/RAW-0007/v2/授权书.docx",
            )
        )

    assert remove_mock.call_count == 2
    requeue_mock.assert_awaited_once_with("RAW-0007", stale_version=2)


def test_cleaned_artifact_is_unavailable_when_source_version_is_stale() -> None:
    from app.services.material_cleaned_artifact import cleaned_artifact_is_current

    stale = {
        "cleanedMinioKey": "cleaned/RAW-0007/version-a.docx",
        "cleanedSourceVersion": 2,
    }
    current = {
        "cleanedMinioKey": "cleaned/RAW-0007/version-b.docx",
        "cleanedSourceVersion": 3,
    }

    assert cleaned_artifact_is_current(3, stale) is False
    assert cleaned_artifact_is_current(3, current) is True
    assert cleaned_artifact_is_current(3, {"cleanedMinioKey": "legacy.docx"}) is True
    assert cleaned_artifact_is_current(
        3,
        {"cleanedMinioKey": "invalid.docx", "cleanedSourceVersion": []},
    ) is False


def test_overwrite_upload_uses_versioned_source_and_enqueues_that_version() -> None:
    from app.services import material_upload_operations
    from app.services.material_raw_object_operations import raw_version_object_key

    folder = SimpleNamespace(
        id=11,
        path="技术标/项目定制/PRJ-1/授权文件",
        tier="project",
        bid_type="技术标",
        project_id="PRJ-1",
        sort_order=0,
        customer_name="",
    )
    existing = _UploadItem(
        id=7,
        name="授权书.doc",
        size_bytes=10,
        minio_bucket="materials",
        minio_key="raw/技术标/项目定制/PRJ-1/授权文件/授权书.doc",
        mime_type="application/msword",
        version=2,
        ext_fields={
            "cleanStatus": "cleaned",
            "cleanedMinioBucket": "materials",
            "cleanedMinioKey": "cleaned/RAW-0007/version-a.docx",
            "cleanedSourceVersion": 2,
        },
        folder=folder,
    )
    session = _UploadSession(folder, existing)
    enqueue_job = MagicMock(return_value={"queued": True, "jobId": "job-v3"})

    with (
        patch.object(material_upload_operations, "async_session", return_value=session),
        patch.object(material_upload_operations.minio_client, "put_object", return_value="etag") as put_mock,
        patch.object(material_upload_operations.minio_client, "remove_object"),
    ):
        result = asyncio.run(
            material_upload_operations.upload_raw_files(
                target_path=folder.path,
                bid_type="技术标",
                on_conflict="overwrite",
                files=[
                    {
                        "name": "授权书.doc",
                        "mimeType": "application/msword",
                        "data": b"version-b",
                    }
                ],
                ensure_runtime_tables=AsyncMock(),
                ensure_folder_path=AsyncMock(),
                clear_default_folder_deletion=AsyncMock(),
                ensure_nested_folder=AsyncMock(),
                archive_raw_file_version=AsyncMock(),
                remove_cleaned_object_from_ext=lambda _ext: None,
                raw_object_key=lambda path, name: f"raw/{path}/{name}",
                raw_version_object_key=raw_version_object_key,
                infer_material_tier_from_folder=lambda _folder: "project",
                enqueue_cleaning_job=enqueue_job,
            )
        )

    expected_key = "raw-versions/RAW-0007/v3/授权书.doc"
    assert result["items"][0]["version"] == 3
    assert existing.minio_key == expected_key
    assert "cleanedMinioKey" not in existing.ext_fields
    assert any("FOR UPDATE" in statement.upper() for statement in session.statements)
    put_mock.assert_called_once_with("bid-materials", expected_key, b"version-b", content_type="application/msword")
    enqueue_job.assert_called_once_with(
        file_id=7,
        source_version=3,
        source_bucket="bid-materials",
        source_key=expected_key,
    )


def test_stale_cleaning_job_is_reported_as_cancelled_instead_of_success() -> None:
    from app.workers.redis_worker import _material_cleaning_final_state

    assert _material_cleaning_final_state(
        {
            "cleanStatus": "stale",
            "cleanMessage": "清洗任务对应的素材版本已过期。",
        }
    ) == {
        "status": "cancelled",
        "summary": "清洗任务对应的素材版本已过期。",
    }


def test_overwrite_upload_cleans_fulltext_only_after_final_commit() -> None:
    from app.services import material_upload_operations
    from app.services.material_raw_object_operations import raw_version_object_key

    folder = SimpleNamespace(
        id=11,
        path="技术标/项目定制/PRJ-1/授权文件",
        tier="project",
        bid_type="技术标",
        project_id="PRJ-1",
        sort_order=0,
        customer_name="",
    )
    existing = _UploadItem(
        id=7,
        name="授权书.pdf",
        size_bytes=10,
        minio_bucket="bid-materials",
        minio_key="raw/技术标/项目定制/PRJ-1/授权文件/授权书.pdf",
        mime_type="application/pdf",
        version=2,
        ext_fields={
            "deepParseProfile": {
                "profile": {
                    "fulltextBucket": "other-bucket",
                    "fulltextKey": "parsed/RAW-9999/v9/fulltext.md",
                }
            },
        },
        folder=folder,
    )
    session = _UploadSession(folder, existing)
    events: list[str] = []

    async def commit() -> None:
        events.append("db-commit")

    def purge_fulltext(
        raw_file_id: int,
        source_version: int,
        *,
        max_source_version: int | None = None,
    ) -> None:
        assert (raw_file_id, source_version, max_source_version) == (7, 2, 2)
        events.append("fulltext-purge")

    session.commit.side_effect = commit
    with (
        patch.object(material_upload_operations, "async_session", return_value=session),
        patch.object(material_upload_operations.minio_client, "put_object", return_value="etag"),
        patch.object(material_upload_operations.minio_client, "remove_object"),
        patch.object(
            material_upload_operations,
            "purge_material_fulltext_objects",
            side_effect=purge_fulltext,
        ),
    ):
        asyncio.run(
            material_upload_operations.upload_raw_files(
                target_path=folder.path,
                bid_type="技术标",
                on_conflict="overwrite",
                files=[
                    {
                        "name": "授权书.pdf",
                        "mimeType": "application/pdf",
                        "data": b"version-b",
                    }
                ],
                ensure_runtime_tables=AsyncMock(),
                ensure_folder_path=AsyncMock(),
                clear_default_folder_deletion=AsyncMock(),
                ensure_nested_folder=AsyncMock(),
                archive_raw_file_version=AsyncMock(),
                remove_cleaned_object_from_ext=lambda _ext: None,
                raw_object_key=lambda path, name: f"raw/{path}/{name}",
                raw_version_object_key=raw_version_object_key,
                infer_material_tier_from_folder=lambda _folder: "project",
                enqueue_cleaning_job=MagicMock(return_value={"queued": True, "jobId": "job-v3"}),
            )
        )

    assert events == ["db-commit", "db-commit", "fulltext-purge"]


def test_overwrite_commit_failure_preserves_old_fulltext() -> None:
    from app.services import material_upload_operations
    from app.services.material_raw_object_operations import raw_version_object_key

    folder = SimpleNamespace(
        id=11,
        path="技术标/项目定制/PRJ-1/授权文件",
        tier="project",
        bid_type="技术标",
        project_id="PRJ-1",
        sort_order=0,
        customer_name="",
    )
    existing = _UploadItem(
        id=7,
        name="授权书.pdf",
        size_bytes=10,
        minio_bucket="bid-materials",
        minio_key="raw/技术标/项目定制/PRJ-1/授权文件/授权书.pdf",
        mime_type="application/pdf",
        version=2,
        ext_fields={},
        folder=folder,
    )
    session = _UploadSession(folder, existing)
    session.commit.side_effect = [None, RuntimeError("commit failed")]

    with (
        patch.object(material_upload_operations, "async_session", return_value=session),
        patch.object(material_upload_operations.minio_client, "put_object", return_value="etag"),
        patch.object(material_upload_operations.minio_client, "remove_object"),
        patch.object(material_upload_operations, "purge_material_fulltext_objects") as purge_fulltext,
    ):
        try:
            asyncio.run(
                material_upload_operations.upload_raw_files(
                    target_path=folder.path,
                    bid_type="技术标",
                    on_conflict="overwrite",
                    files=[
                        {
                            "name": "授权书.pdf",
                            "mimeType": "application/pdf",
                            "data": b"version-b",
                        }
                    ],
                    ensure_runtime_tables=AsyncMock(),
                    ensure_folder_path=AsyncMock(),
                    clear_default_folder_deletion=AsyncMock(),
                    ensure_nested_folder=AsyncMock(),
                    archive_raw_file_version=AsyncMock(),
                    remove_cleaned_object_from_ext=lambda _ext: None,
                    raw_object_key=lambda path, name: f"raw/{path}/{name}",
                    raw_version_object_key=raw_version_object_key,
                    infer_material_tier_from_folder=lambda _folder: "project",
                    enqueue_cleaning_job=MagicMock(return_value={"queued": True, "jobId": "job-v3"}),
                )
            )
        except RuntimeError as exc:
            assert str(exc) == "commit failed"
        else:  # pragma: no cover - regression guard
            raise AssertionError("upload should expose the commit failure")

    session.rollback.assert_awaited_once()
    purge_fulltext.assert_not_called()
