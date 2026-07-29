from __future__ import annotations

from unittest.mock import AsyncMock, patch

from app.services.bid_type import BUSINESS_BID_TYPE, TECHNICAL_BID_TYPE
from app.services.job_queue import EnqueueResult
from app.services.job_queue import JobStatusUnavailable
from app.services.peripheral import PeripheralError
from app.services import material_wiki_jobs


def test_enqueue_wiki_generation_uses_material_job_type() -> None:
    with patch.object(
        material_wiki_jobs,
        "enqueue_generation_job",
        return_value=EnqueueResult(queued=True, job_id="wiki-job-1"),
    ) as enqueue:
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
