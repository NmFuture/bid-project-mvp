from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock, patch

from app.services.bid_type import BUSINESS_BID_TYPE, TECHNICAL_BID_TYPE
from app.services.job_queue import EnqueueResult
from app.services.job_queue import JobStatusUnavailable
from app.services.peripheral import PeripheralError
from app.services import material_wiki_jobs


def test_enqueue_wiki_generation_uses_material_job_type() -> None:
    with (
        patch.object(
            material_wiki_jobs,
            "enqueue_generation_job",
            return_value=EnqueueResult(queued=True, job_id="wiki-job-1"),
        ) as enqueue,
        patch.object(material_wiki_jobs, "_remember_latest_job") as remember,
    ):
        result = material_wiki_jobs.enqueue_material_wiki_generation(
            TECHNICAL_BID_TYPE,
            mode="refresh",
            reference_path="ref",
            fallback_to_deterministic=True,
        )

    assert result == {"jobId": "wiki-job-1", "status": "queued", "reused": False}
    enqueue.assert_called_once_with(
        material_wiki_jobs.MATERIAL_WIKI_JOB_TYPE,
        "wiki:technical",
        {
            "bidType": TECHNICAL_BID_TYPE,
            "mode": "refresh",
            "referencePath": "ref",
            "fallbackToDeterministic": True,
        },
    )
    remember.assert_called_once_with(TECHNICAL_BID_TYPE, "wiki-job-1")


def test_execute_wiki_generation_selects_business_generator() -> None:
    generated = {"generation": {"summary": "商务标 Wiki 已重建"}}
    generator = AsyncMock(return_value=generated)

    with patch("app.services.business_wiki_generation.generate_business_wiki", generator):
        result = material_wiki_jobs.execute_material_wiki_generation(
            {
                "bidType": BUSINESS_BID_TYPE,
                "mode": "replace",
                "referencePath": "ref",
                "fallbackToDeterministic": False,
            }
        )

    assert result == {"status": "success", "summary": "商务标 Wiki 已重建"}
    generator.assert_awaited_once_with(
        mode="replace",
        reference_path="ref",
        fallback_to_deterministic=False,
    )


def test_wiki_job_status_reports_queue_unavailable_instead_of_not_found() -> None:
    with patch.object(material_wiki_jobs, "get_job_status", side_effect=JobStatusUnavailable):
        try:
            material_wiki_jobs.material_wiki_job_status("wiki-job-1", TECHNICAL_BID_TYPE)
        except PeripheralError as exc:
            assert exc.status_code == 503
            assert exc.code == "MATERIAL_QUEUE_UNAVAILABLE"
        else:
            raise AssertionError("Redis outage must return a retryable service error")


def test_latest_wiki_status_maps_queued_job_to_legacy_running_contract() -> None:
    client = MagicMock()
    client.get.return_value = "wiki-job-1"
    with (
        patch.object(material_wiki_jobs, "get_redis_client", return_value=client),
        patch.object(
            material_wiki_jobs,
            "material_wiki_job_status",
            return_value={
                "status": "queued",
                "message": "等待素材 Worker",
                "progress": {"phase": "preview"},
            },
        ),
    ):
        result = material_wiki_jobs.latest_material_wiki_job_status(TECHNICAL_BID_TYPE)

    assert result == {
        "jobId": "wiki-job-1",
        "status": "running",
        "progress": {"phase": "preview"},
        "message": "等待素材 Worker",
    }


def test_execute_technical_wiki_forwards_progress_callback() -> None:
    generator = AsyncMock(return_value={"generation": {"summary": "技术标 Wiki 已更新"}})
    progress = Mock()

    with patch("app.services.technical_wiki_generation.generate_technical_wiki", generator):
        result = material_wiki_jobs.execute_material_wiki_generation(
            {"bidType": TECHNICAL_BID_TYPE, "mode": "refresh"},
            progress_callback=progress,
        )

    assert result == {"status": "success", "summary": "技术标 Wiki 已更新"}
    generator.assert_awaited_once_with(
        mode="refresh",
        reference_path="",
        fallback_to_deterministic=False,
        on_progress=progress,
    )
