"""S7 素材来源回归：普通 matchedMaterials 优先组装原始 Word，不优先用清洗版。

背景（1.9 层级误升格）：素材清洗版可能把正文短句误升为 Heading，S7 只认
原始 docx 的真实 Heading/outlineLvl/TOC；原始文件缺失或不是 docx 时才回退
清洗稿。
"""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, call, patch

from fastapi import HTTPException

from app.services import tech_assembly
from app.services import technical_gap_actions
from app.services import technical_gap_service as technical_gap_service_module

DOCX_PAYLOAD = {
    "bucket": "raw",
    "key": "original.docx",
    "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "fileName": "原始.docx",
}
CLEANED_PAYLOAD = {
    "bucket": "raw",
    "key": "cleaned.docx",
    "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "fileName": "清洗版.docx",
}
DOC_PAYLOAD = {
    "bucket": "raw",
    "key": "original.doc",
    "mimeType": "application/msword",
    "fileName": "原始.doc",
}


class CopyMaterialToLibraryTests(unittest.TestCase):
    def test_prefers_original_word_over_cleaned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.docx"
            with patch.object(
                tech_assembly.technical_material_store,
                "raw_download_content",
                new=AsyncMock(return_value=dict(DOCX_PAYLOAD)),
            ) as raw_mock, patch.object(
                tech_assembly.technical_material_store,
                "raw_download_cleaned_content",
                new=AsyncMock(return_value=dict(CLEANED_PAYLOAD)),
            ) as cleaned_mock, patch.object(
                tech_assembly.minio_client, "download_file"
            ) as download_mock:
                tech_assembly._copy_material_to_library("RAW-0001", "", target)

            raw_mock.assert_awaited_once()
            cleaned_mock.assert_not_awaited()
            download_mock.assert_called_once_with("raw", "original.docx", target)

    def test_falls_back_to_cleaned_when_original_not_docx(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.docx"
            with patch.object(
                tech_assembly.technical_material_store,
                "raw_download_content",
                new=AsyncMock(return_value=dict(DOC_PAYLOAD)),
            ), patch.object(
                tech_assembly.technical_material_store,
                "raw_download_cleaned_content",
                new=AsyncMock(return_value=dict(CLEANED_PAYLOAD)),
            ) as cleaned_mock, patch.object(
                tech_assembly.minio_client, "download_file"
            ) as download_mock:
                tech_assembly._copy_material_to_library("RAW-0001", "", target)

            cleaned_mock.assert_awaited_once()
            download_mock.assert_called_once_with("raw", "cleaned.docx", target)

    def test_falls_back_to_cleaned_when_original_download_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.docx"
            temp_target = target.with_suffix(f"{target.suffix}.download")

            def download_file(bucket: str, key: str, output: Path) -> None:
                if key == "original.docx":
                    temp_target.write_bytes(b"partial-raw")
                    raise RuntimeError("raw object missing")
                self.assertFalse(output.exists())
                self.assertFalse(temp_target.exists())
                output.write_bytes(b"cleaned-docx")

            with patch.object(
                tech_assembly.technical_material_store,
                "raw_download_content",
                new=AsyncMock(return_value=dict(DOCX_PAYLOAD)),
            ), patch.object(
                tech_assembly.technical_material_store,
                "raw_download_cleaned_content",
                new=AsyncMock(return_value=dict(CLEANED_PAYLOAD)),
            ) as cleaned_mock, patch.object(
                tech_assembly.minio_client,
                "download_file",
                side_effect=download_file,
            ) as download_mock:
                tech_assembly._copy_material_to_library("RAW-0001", "", target)

            cleaned_mock.assert_awaited_once()
            self.assertEqual(
                download_mock.call_args_list,
                [
                    call("raw", "original.docx", target),
                    call("raw", "cleaned.docx", target),
                ],
            )
            self.assertEqual(target.read_bytes(), b"cleaned-docx")
            self.assertFalse(temp_target.exists())

    def test_preserves_both_download_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.docx"
            temp_target = target.with_suffix(f"{target.suffix}.download")
            raw_error = RuntimeError("raw object missing")
            cleaned_error = RuntimeError("cleaned object missing")

            def download_file(bucket: str, key: str, output: Path) -> None:
                temp_target.write_bytes(f"partial-{key}".encode())
                raise raw_error if key == "original.docx" else cleaned_error

            with patch.object(
                tech_assembly.technical_material_store,
                "raw_download_content",
                new=AsyncMock(return_value=dict(DOCX_PAYLOAD)),
            ), patch.object(
                tech_assembly.technical_material_store,
                "raw_download_cleaned_content",
                new=AsyncMock(return_value=dict(CLEANED_PAYLOAD)),
            ), patch.object(
                tech_assembly.minio_client,
                "download_file",
                side_effect=download_file,
            ):
                with self.assertRaises(ExceptionGroup) as raised:
                    tech_assembly._copy_material_to_library("RAW-0001", "", target)

            self.assertEqual(raised.exception.exceptions, (raw_error, cleaned_error))
            self.assertFalse(target.exists())
            self.assertFalse(temp_target.exists())


class DownloadableGapMaterialPayloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_prefers_original_word_over_cleaned(self) -> None:
        with patch.object(
            technical_gap_actions.technical_material_store,
            "raw_download_content",
            new=AsyncMock(return_value=dict(DOCX_PAYLOAD)),
        ), patch.object(
            technical_gap_actions.technical_material_store,
            "raw_download_cleaned_content",
            new=AsyncMock(return_value=dict(CLEANED_PAYLOAD)),
        ) as cleaned_mock:
            payload, source_kind = await technical_gap_actions._downloadable_technical_material_payload("RAW-0001")

        self.assertEqual(source_kind, "raw")
        self.assertEqual(payload["key"], "original.docx")
        cleaned_mock.assert_not_awaited()

    async def test_falls_back_to_cleaned_when_original_not_docx(self) -> None:
        with patch.object(
            technical_gap_actions.technical_material_store,
            "raw_download_content",
            new=AsyncMock(return_value=dict(DOC_PAYLOAD)),
        ), patch.object(
            technical_gap_actions.technical_material_store,
            "raw_download_cleaned_content",
            new=AsyncMock(return_value=dict(CLEANED_PAYLOAD)),
        ):
            payload, source_kind = await technical_gap_actions._downloadable_technical_material_payload("RAW-0001")

        self.assertEqual(source_kind, "cleaned")
        self.assertEqual(payload["key"], "cleaned.docx")

    async def test_prepare_falls_back_to_cleaned_when_original_download_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)

            def download_file(bucket: str, key: str, target: Path) -> None:
                if key == "original.docx":
                    target.with_suffix(f"{target.suffix}.download").write_bytes(b"partial-raw")
                    raise RuntimeError("raw object missing")
                self.assertFalse(target.exists())
                self.assertFalse(target.with_suffix(f"{target.suffix}.download").exists())
                target.write_bytes(b"cleaned-docx")

            with patch.object(
                technical_gap_actions,
                "_project_dir",
                return_value=project_dir,
            ), patch.object(
                technical_gap_actions.technical_material_store,
                "raw_download_content",
                new=AsyncMock(return_value=dict(DOCX_PAYLOAD)),
            ), patch.object(
                technical_gap_actions.technical_material_store,
                "raw_download_cleaned_content",
                new=AsyncMock(return_value=dict(CLEANED_PAYLOAD)),
            ) as cleaned_mock, patch.object(
                technical_gap_actions.minio_client,
                "download_file",
                side_effect=download_file,
            ) as download_mock:
                prepared = await technical_gap_actions.prepare_technical_existing_gap_material_files(
                    {"id": "PRJ-0001"},
                    "GAP-0001",
                    {"materials": [{"id": "RAW-0001"}]},
                )

            cleaned_mock.assert_awaited_once()
            self.assertEqual(
                [item.args[1] for item in download_mock.call_args_list],
                ["original.docx", "cleaned.docx"],
            )
            self.assertEqual(prepared[0]["sourceKind"], "cleaned")
            prepared_path = Path(prepared[0]["path"])
            self.assertEqual(prepared_path.read_bytes(), b"cleaned-docx")
            self.assertFalse(prepared_path.with_suffix(f"{prepared_path.suffix}.download").exists())

    async def test_prepare_preserves_both_download_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw_error = RuntimeError("raw object missing")
            cleaned_error = RuntimeError("cleaned object missing")

            def failed_download(bucket: str, key: str, target: Path) -> None:
                target.with_suffix(f"{target.suffix}.download").write_bytes(key.encode())
                raise raw_error if key == "original.docx" else cleaned_error

            with patch.object(
                technical_gap_actions,
                "_project_dir",
                return_value=Path(tmp),
            ), patch.object(
                technical_gap_actions.technical_material_store,
                "raw_download_content",
                new=AsyncMock(return_value=dict(DOCX_PAYLOAD)),
            ), patch.object(
                technical_gap_actions.technical_material_store,
                "raw_download_cleaned_content",
                new=AsyncMock(return_value=dict(CLEANED_PAYLOAD)),
            ), patch.object(
                technical_gap_actions.minio_client,
                "download_file",
                side_effect=failed_download,
            ):
                with self.assertRaises(ExceptionGroup) as raised:
                    await technical_gap_actions.prepare_technical_existing_gap_material_files(
                        {"id": "PRJ-0001"},
                        "GAP-0001",
                        {"materials": [{"id": "RAW-0001"}]},
                    )

            self.assertEqual(raised.exception.exceptions, (raw_error, cleaned_error))
            work_root = Path(tmp) / "s4_gap_workdir" / "selected_material" / "GAP-0001"
            self.assertEqual(list(work_root.rglob("*")), [])

    async def test_prepare_rolls_back_only_current_batch_when_later_material_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            work_root = project_dir / "s4_gap_workdir" / "selected_material" / "GAP-0001"
            historical_file = work_root / "batch-historical" / "existing.docx"
            historical_file.parent.mkdir(parents=True)
            historical_file.write_bytes(b"existing")

            first_payload = {**DOCX_PAYLOAD, "key": "first.docx"}
            second_payload = {**DOCX_PAYLOAD, "key": "second.docx"}

            def download_file(bucket: str, key: str, target: Path) -> None:
                if key == "first.docx":
                    target.write_bytes(b"first")
                    return
                target.with_suffix(f"{target.suffix}.download").write_bytes(b"partial-second")
                raise RuntimeError("second object missing")

            with patch.object(
                technical_gap_actions,
                "_project_dir",
                return_value=project_dir,
            ), patch.object(
                technical_gap_actions,
                "_downloadable_technical_material_payload",
                new=AsyncMock(side_effect=[(first_payload, "cleaned"), (second_payload, "cleaned")]),
            ), patch.object(
                technical_gap_actions.minio_client,
                "download_file",
                side_effect=download_file,
            ):
                with self.assertRaisesRegex(RuntimeError, "second object missing"):
                    await technical_gap_actions.prepare_technical_existing_gap_material_files(
                        {"id": "PRJ-0001"},
                        "GAP-0001",
                        {"materials": [{"id": "RAW-0001"}, {"id": "RAW-0002"}]},
                    )

            self.assertEqual(historical_file.read_bytes(), b"existing")
            self.assertEqual(
                [path.relative_to(work_root) for path in work_root.rglob("*")],
                [Path("batch-historical"), Path("batch-historical/existing.docx")],
            )


class SelectGapMaterialTransactionTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _prepared_batch(root: Path) -> tuple[list[dict[str, str]], Path, Path]:
        work_root = root / "s4_gap_workdir" / "selected_material" / "GAP-0001"
        historical_file = work_root / "batch-historical" / "existing.docx"
        historical_file.parent.mkdir(parents=True)
        historical_file.write_bytes(b"existing")
        batch_dir = work_root / "batch-current"
        prepared_path = batch_dir / "01-selected.docx"
        batch_dir.mkdir()
        prepared_path.write_bytes(b"selected")
        return (
            [
                {
                    "materialId": "RAW-0001",
                    "fileName": prepared_path.name,
                    "path": str(prepared_path),
                    "batchDir": str(batch_dir),
                }
            ],
            batch_dir,
            historical_file,
        )

    async def test_select_material_cleans_current_batch_on_each_commit_failure(self) -> None:
        for failing_step in ("register", "refresh", "persist"):
            with self.subTest(failing_step=failing_step), tempfile.TemporaryDirectory() as tmp:
                prepared, batch_dir, historical_file = self._prepared_batch(Path(tmp))
                project = {"id": "PRJ-0001", "gap_state": {"recognitionStatus": "completed"}}
                original_project = copy.deepcopy(project)
                result = {"artifact": {"id": "ART-1"}}
                service = technical_gap_service_module.TechnicalGapService()

                def register_material(*args: object, **kwargs: object) -> dict[str, object]:
                    project["gap_state"]["mutation"] = "register"
                    if failing_step == "register":
                        raise RuntimeError("register failed")
                    return result

                def refresh_integrity(*args: object, **kwargs: object) -> None:
                    project["gap_state"]["mutation"] = "refresh"
                    if failing_step == "refresh":
                        raise RuntimeError("refresh failed")

                def persist_project(*args: object, **kwargs: object) -> None:
                    project["gap_state"]["mutation"] = "persist"
                    if failing_step == "persist":
                        raise RuntimeError("persist failed")

                register_mock = Mock(side_effect=register_material)
                refresh_mock = Mock(side_effect=refresh_integrity)
                persist_mock = Mock(side_effect=persist_project)

                with patch.object(
                    technical_gap_service_module,
                    "require_technical_gap_project_for_update",
                    return_value=project,
                ), patch.object(
                    technical_gap_service_module,
                    "ensure_technical_gap_state",
                    side_effect=lambda value: value["gap_state"],
                ), patch.object(
                    technical_gap_service_module,
                    "prepare_technical_existing_gap_material_files",
                    new=AsyncMock(return_value=prepared),
                ), patch.object(
                    technical_gap_service_module,
                    "register_technical_existing_gap_material",
                    register_mock,
                ), patch.object(
                    service,
                    "_url_scope",
                    return_value={},
                ), patch.object(
                    service,
                    "_refresh_gap_integrity",
                    refresh_mock,
                ), patch.object(
                    technical_gap_service_module,
                    "persist_technical_gap_project",
                    persist_mock,
                ):
                    with self.assertRaises(HTTPException) as raised:
                        await service.select_material("PRJ-0001", "GAP-0001", object())

                self.assertEqual(raised.exception.status_code, 400)
                self.assertEqual(project, original_project)
                self.assertFalse(batch_dir.exists())
                self.assertEqual(historical_file.read_bytes(), b"existing")

    async def test_select_material_keeps_current_batch_after_persist_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prepared, batch_dir, historical_file = self._prepared_batch(Path(tmp))
            project = {"id": "PRJ-0001", "gap_state": {"recognitionStatus": "completed"}}
            result = {"artifact": {"id": "ART-1"}}
            service = technical_gap_service_module.TechnicalGapService()

            with patch.object(
                technical_gap_service_module,
                "require_technical_gap_project_for_update",
                return_value=project,
            ), patch.object(
                technical_gap_service_module,
                "ensure_technical_gap_state",
                side_effect=lambda value: value["gap_state"],
            ), patch.object(
                technical_gap_service_module,
                "prepare_technical_existing_gap_material_files",
                new=AsyncMock(return_value=prepared),
            ), patch.object(
                technical_gap_service_module,
                "register_technical_existing_gap_material",
                return_value=result,
            ), patch.object(
                service,
                "_url_scope",
                return_value={},
            ), patch.object(
                service,
                "_refresh_gap_integrity",
            ), patch.object(
                technical_gap_service_module,
                "persist_technical_gap_project",
            ) as persist_mock:
                payload = await service.select_material("PRJ-0001", "GAP-0001", object())

            self.assertEqual(payload, result)
            persist_mock.assert_called_once_with(project)
            self.assertTrue(batch_dir.exists())
            self.assertEqual(historical_file.read_bytes(), b"existing")


if __name__ == "__main__":
    unittest.main()
