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
                "updatedAt": "2026-08-06T01:59:00Z",
                "progress": {"phase": "preview"},
            },
        ),
    ):
        result = material_wiki_jobs.latest_material_wiki_job_status(TECHNICAL_BID_TYPE)

    assert result == {
        "jobId": "wiki-job-1",
        "bidType": TECHNICAL_BID_TYPE,
        "status": "running",
        "progress": {"phase": "preview"},
        "message": "等待素材 Worker",
    }


def test_latest_wiki_status_includes_finished_at_for_terminal_job() -> None:
    """终态 Wiki 任务必须带出结束时间，供失败后进入页面的用户持续看到（R10-B07-05）。"""
    client = MagicMock()
    client.get.return_value = "wiki-job-9"
    with (
        patch.object(material_wiki_jobs, "get_redis_client", return_value=client),
        patch.object(
            material_wiki_jobs,
            "material_wiki_job_status",
            return_value={
                "status": "failed",
                "message": "生成超时",
                "updatedAt": "2026-08-06T02:00:00Z",
                "progress": {},
            },
        ),
    ):
        result = material_wiki_jobs.latest_material_wiki_job_status(TECHNICAL_BID_TYPE)

    assert result["status"] == "failed"
    assert result["error"] == "生成超时"
    assert result["finishedAt"] == "2026-08-06T02:00:00Z"


def test_latest_wiki_status_falls_back_to_scoped_generic_terminal_when_pointer_expired() -> None:
    """latest pointer 先过期时，仍以收尾时重置 TTL 的 scoped generic terminal 展示失败。"""
    client = MagicMock()
    client.get.return_value = None
    terminal = {
        "jobId": "wiki-job-long",
        "type": material_wiki_jobs.MATERIAL_WIKI_JOB_TYPE,
        "bidType": TECHNICAL_BID_TYPE,
        "status": "failed",
        "message": "长任务生成超时",
        "finishedAt": "2026-08-06T03:00:00Z",
    }
    with (
        patch.object(material_wiki_jobs, "get_redis_client", return_value=client),
        patch.object(
            material_wiki_jobs,
            "latest_terminal_job_of_type",
            return_value=terminal,
        ) as latest_terminal,
    ):
        result = material_wiki_jobs.latest_material_wiki_job_status(TECHNICAL_BID_TYPE)

    latest_terminal.assert_called_once_with(
        material_wiki_jobs.MATERIAL_WIKI_JOB_TYPE,
        TECHNICAL_BID_TYPE,
    )
    assert result == {
        "jobId": "wiki-job-long",
        "bidType": TECHNICAL_BID_TYPE,
        "status": "failed",
        "progress": {},
        "message": "长任务生成超时",
        "finishedAt": "2026-08-06T03:00:00Z",
        "error": "长任务生成超时",
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
