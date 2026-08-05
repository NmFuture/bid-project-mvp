from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


os.environ.setdefault("APP_STORE_BACKEND", "memory")

# 未打桩的解析链路会调真实 opencode（默认 127.0.0.1:4096）。本机跑着开发环境时，
# 测试会真的建一个 agent 会话并一直等它跑完，表现为整个用例挂死。
# 默认指向一个空闲端口让调用快速失败；确需连真实服务的场景显式设置该变量即可。
os.environ.setdefault("OPENCODE_BASE_URL", "http://127.0.0.1:4099")


def _isolate_test_database_url() -> str:
    """强制把测试的 DATABASE_URL 指向独立的 *_test 库。

    `APP_STORE_BACKEND=memory` 只隔离了项目状态，素材目录（raw_folders/raw_files）
    始终写真实 Postgres。直连开发库时，测试项目会拿到与真实项目相同的 PRJ-xxxx ID，
    把素材目录建到真实项目名下，测试结束也不会回收。
    """

    url = (
        os.getenv("DATABASE_URL")
        or "postgresql+asyncpg://biduser:bidpass@localhost:5432/bidplatform"
    )
    parts = urlsplit(url)
    name = parts.path.lstrip("/")
    if name and not name.endswith("_test"):
        url = urlunsplit(parts._replace(path=f"/{name}_test"))
    os.environ["DATABASE_URL"] = url
    return url


TEST_DATABASE_URL = _isolate_test_database_url()

import pytest


async def _ensure_test_database() -> None:
    try:
        import asyncpg
    except ModuleNotFoundError:
        return

    parts = urlsplit(TEST_DATABASE_URL)
    db_name = parts.path.lstrip("/")
    if not db_name.endswith("_test"):
        raise RuntimeError(f"拒绝在非 *_test 库上建表：{db_name}")

    admin_dsn = urlunsplit(parts._replace(scheme="postgresql", path="/postgres"))
    try:
        conn = await asyncpg.connect(admin_dsn)
    except Exception as exc:  # Postgres 不可用时留给真正用到库的用例报错
        print(f"[conftest] 跳过测试库准备，无法连接 Postgres：{exc}")
        return
    try:
        if await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", db_name):
            return
        await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()

    init_sql = Path(__file__).resolve().parents[2] / "initdb" / "01-init.sql"
    conn = await asyncpg.connect(urlunsplit(parts._replace(scheme="postgresql")))
    try:
        await conn.execute(init_sql.read_text(encoding="utf-8"))
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
def _provision_test_database():
    import asyncio

    asyncio.run(_ensure_test_database())
    yield


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
