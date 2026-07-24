from __future__ import annotations

import os


os.environ.setdefault("APP_STORE_BACKEND", "memory")

import pytest


@pytest.fixture(autouse=True)
def _reset_business_bidder_profile():
    from app.services import business_bidder_profile

    business_bidder_profile._memory_profile.clear()
    yield
    business_bidder_profile._memory_profile.clear()


@pytest.fixture(autouse=True)
def _s1_parse_inline_scheduler():
    """S1 解析异步化后的测试模式：解析任务内联同步执行，关闭重试退避与进度落库节流。

    保持 upload-and-run / parse-results/run 的旧同步响应契约；需要测异步行为本身的
    用例（test_parse_async_jobs.py）在测试内自行覆盖这些补丁。
    """
    from unittest.mock import patch

    from app.core.config import settings as app_settings
    from app.services import bid_parse_service

    def _inline_schedule(project_id, data):
        bid_parse_service._run_s1_parse_job(project_id, data)
        return "inline", ""

    old_attempts = app_settings.s1_parse_job_max_attempts
    old_interval = app_settings.parse_progress_persist_interval_sec
    app_settings.s1_parse_job_max_attempts = 1
    app_settings.parse_progress_persist_interval_sec = 0.0
    try:
        with patch(
            "app.services.bid_parse_service._schedule_s1_parse_job",
            side_effect=_inline_schedule,
        ):
            yield
    finally:
        app_settings.s1_parse_job_max_attempts = old_attempts
        app_settings.parse_progress_persist_interval_sec = old_interval
