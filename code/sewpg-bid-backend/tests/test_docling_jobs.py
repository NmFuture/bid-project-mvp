from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from app.core.config import settings
from app.services.docling_engine import DOCLING_LOCKED_VERSION, DOCLING_PIPELINE_OPTIONS_VERSION
from app.services.docling_jobs import _cached_result_ready, execute_docling_batch
from app.services.job_queue import EnqueueResult


def _write_cached_result(project_dir: Path, run_id: str) -> tuple[str, str]:
    document_id = "TEN-1"
    source_sha256 = "a" * 64
    quality_path = project_dir / "document_parse" / "docling" / document_id / "parse_quality.json"
    quality_path.parent.mkdir(parents=True, exist_ok=True)
    quality_path.write_text(
        json.dumps(
            {
                "status": "completed",
                "sourceSha256": source_sha256,
                "runId": run_id,
                "doclingVersion": DOCLING_LOCKED_VERSION,
                "pipelineOptionsVersion": DOCLING_PIPELINE_OPTIONS_VERSION,
            }
        ),
        encoding="utf-8",
    )
    (project_dir / f"{document_id}_document_nav.json").write_text("{}", encoding="utf-8")
    return document_id, source_sha256


def test_cached_docling_result_is_reused_only_for_same_run(tmp_path: Path) -> None:
    document_id, source_sha256 = _write_cached_result(tmp_path, "run-1")

    assert _cached_result_ready(tmp_path, document_id, source_sha256, "run-1") is True
    assert _cached_result_ready(tmp_path, document_id, source_sha256, "run-2") is False


def test_docling_batch_parses_shared_pdf_and_queues_continuation(tmp_path: Path) -> None:
    uploads_dir = tmp_path / "uploads"
    parsed_dir = tmp_path / "parsed"
    documents_dir = tmp_path / "documents"
    uploads_dir.mkdir()
    parsed_dir.mkdir()
    documents_dir.mkdir()
    pdf_path = uploads_dir / "tender.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nmock")
    source_sha256 = hashlib.sha256(pdf_path.read_bytes()).hexdigest()

    old_dirs = settings.uploads_dir, settings.parsed_dir, settings.documents_dir
    settings.uploads_dir, settings.parsed_dir, settings.documents_dir = uploads_dir, parsed_dir, documents_dir

    class FakeEngine:
        def __init__(self, *, fallback: str) -> None:
            self.fallback = fallback

        def parse_pdf(self, *, project_id: str, document: dict, output_dir: Path) -> dict:
            quality_path = output_dir / "document_parse" / "docling" / document["id"] / "parse_quality.json"
            quality_path.parent.mkdir(parents=True, exist_ok=True)
            quality_path.write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "sourceSha256": document["sourceSha256"],
                        "runId": document["runId"],
                        "doclingVersion": DOCLING_LOCKED_VERSION,
                        "pipelineOptionsVersion": DOCLING_PIPELINE_OPTIONS_VERSION,
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / f"{document['id']}_document_nav.json").write_text("{}", encoding="utf-8")
            return {"status": "completed"}

    job = {
        "id": "run-1:docling",
        "type": "s1_docling_batch",
        "projectId": "project-1",
        "parentJobId": "run-1",
        "data": {
            "__bidType": "技术标",
            "tenderFiles": [{"id": "TEN-1", "name": "tender.pdf", "path": str(pdf_path)}],
            "templateFiles": [],
        },
    }
    try:
        with patch("app.services.docling_jobs.DoclingParseEngine", FakeEngine), patch(
            "app.services.docling_jobs.is_job_cancel_requested", return_value=False
        ), patch(
            "app.services.docling_jobs.enqueue_internal_job",
            return_value=EnqueueResult(queued=True, job_id="run-1:continue"),
        ) as enqueue_mock:
            outcome = execute_docling_batch(job)
    finally:
        settings.uploads_dir, settings.parsed_dir, settings.documents_dir = old_dirs

    assert outcome["status"] == "succeeded"
    continuation_data = enqueue_mock.call_args.args[2]
    assert continuation_data["__doclingPrepared"] is True
    assert continuation_data["__runId"] == "run-1"
    assert continuation_data["tenderFiles"][0]["sha256"] == source_sha256
    assert continuation_data["tenderFiles"][0]["runId"] == "run-1"
