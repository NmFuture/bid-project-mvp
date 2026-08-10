"""项目状态并发写：CAS 拒绝陈旧写入、mutate 冲突后基于最新状态重放、失败回滚。

后台填写 worker 与页面请求是两个进程，读到写之间隔着 AI 填写、素材下载等慢操作。
整份 payload 无条件覆盖时，后写的一方会把先写方的产物记录整份抹掉——这里锁住修复后的语义。
"""
from __future__ import annotations

from contextlib import closing
from unittest import mock

import pytest
from psycopg.types.json import Jsonb

from app.services import workspace_project_access as access
from app.services.bid_project_repository import (
    ProjectConcurrentUpdateError,
    ProjectStateRepository,
    project_revision,
)

BID_TYPE = "technical"


def _project(rev: int = 0) -> dict:
    return {"id": "PRJ-CAS", "bidType": BID_TYPE, "updatedAt": "2026-08-09T00:00:00Z", "_rev": rev}


def _errors():
    return (lambda pid: KeyError(pid), lambda pid: TypeError(pid))


def _mutate(project_id, mutate, **kwargs):
    not_found, wrong_type = _errors()
    return access.mutate_workspace_project(
        project_id,
        mutate,
        bid_type=BID_TYPE,
        not_found_error=not_found,
        wrong_type_error=wrong_type,
        **kwargs,
    )


def test_mutation_replays_on_the_latest_state_after_conflict() -> None:
    # 每次重读都拿到更新过的版本号，模拟别的进程在这期间写过
    reads = [_project(rev) for rev in (7, 8, 9)]
    seen_revs: list[int] = []
    persist_calls: list[int] = []

    def persist(project, expected_rev):
        persist_calls.append(expected_rev)
        if len(persist_calls) < 3:
            raise ProjectConcurrentUpdateError(project["id"])

    with mock.patch.object(access, "require_workspace_project_for_update", side_effect=lambda *a, **k: reads.pop(0)), \
         mock.patch.object(access.store, "persist_project_state_checked", side_effect=persist):
        result = _mutate("PRJ-CAS", lambda project: seen_revs.append(project_revision(project)) or "ok")

    assert result == "ok"
    # 改动被重放三次，每次都作用在重新读到的最新状态上，而不是第一次那份陈旧快照
    assert seen_revs == [7, 8, 9]
    assert persist_calls == [7, 8, 9]


def test_mutation_gives_up_after_retries_are_exhausted() -> None:
    def persist(project, expected_rev):
        raise ProjectConcurrentUpdateError(project["id"])

    with mock.patch.object(access, "require_workspace_project_for_update", side_effect=lambda *a, **k: _project(1)), \
         mock.patch.object(access.store, "persist_project_state_checked", side_effect=persist):
        with pytest.raises(ProjectConcurrentUpdateError):
            _mutate("PRJ-CAS", lambda project: project.update({"touched": True}), retries=3)


def test_failed_mutation_restores_the_shared_project_dict() -> None:
    # 内存后端下 require 返回 store 内的同一个 dict：半成品改动不能留在进程内存里
    project = _project(3)

    with mock.patch.object(access, "require_workspace_project_for_update", side_effect=lambda *a, **k: project), \
         mock.patch.object(access.store, "persist_project_state_checked"):
        def boom(current: dict) -> None:
            current["gap_state"] = {"half": "written"}
            raise RuntimeError("mutation failed")

        with pytest.raises(RuntimeError):
            _mutate("PRJ-CAS", boom)

    assert project == _project(3)


def test_failed_persist_restores_the_shared_project_dict() -> None:
    project = _project(3)

    with mock.patch.object(access, "require_workspace_project_for_update", side_effect=lambda *a, **k: project), \
         mock.patch.object(access.store, "persist_project_state_checked", side_effect=OSError("db down")):
        with pytest.raises(OSError):
            _mutate("PRJ-CAS", lambda current: current.update({"gap_state": {"half": "written"}}))

    assert project == _project(3)


def test_persist_when_false_skips_the_write_entirely() -> None:
    # 轮询接口顺带做的自愈修复没命中时不该白写一次，否则版本号空转、并发冲突凭空变多
    with mock.patch.object(access, "require_workspace_project_for_update", side_effect=lambda *a, **k: _project(2)), \
         mock.patch.object(access.store, "persist_project_state_checked") as persist_mock:
        result = _mutate("PRJ-CAS", lambda project: (False, "payload"), persist_when=lambda outcome: outcome[0])

    assert result == (False, "payload")
    persist_mock.assert_not_called()


@pytest.mark.integration
def test_repository_cas_accepts_rows_written_before_versioning() -> None:
    # 存量项目的 payload 里没有 _rev 字段，第一次 CAS 写入必须照常通过，否则升级即全线写失败
    repository = ProjectStateRepository("postgres")
    repository.ensure_db()
    legacy = {"id": "PRJ-LEGACY", "bidType": BID_TYPE, "updatedAt": "2026-08-09T00:00:00Z"}
    try:
        # 直接塞一行不带 _rev 的 payload，模拟升级前落库的存量项目
        with closing(repository._connect()) as connection:
            connection.execute(
                "INSERT INTO projects (id, payload, updated_at) VALUES (%s, %s, %s)",
                (legacy["id"], Jsonb(legacy), legacy["updatedAt"]),
            )
            connection.commit()

        repository.persist(legacy, expected_rev=0)

        assert project_revision(legacy) == 1
        reloaded = repository.load_one(legacy["id"], lambda payload: payload)
        assert project_revision(reloaded) == 1
    finally:
        repository.delete(legacy["id"])


@pytest.mark.integration
def test_repository_cas_rejects_a_stale_write() -> None:
    repository = ProjectStateRepository("postgres")
    repository.ensure_db()
    project = _project(0)
    try:
        repository.persist(project)
        assert project_revision(project) == 1

        stale = dict(project)
        stale["_rev"] = 0  # 另一进程手里的旧快照
        repository.persist(project, expected_rev=project_revision(project))
        with pytest.raises(ProjectConcurrentUpdateError):
            repository.persist(stale, expected_rev=0)
    finally:
        repository.delete(project["id"])
