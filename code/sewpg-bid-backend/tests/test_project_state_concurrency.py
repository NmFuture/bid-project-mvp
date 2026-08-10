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
def test_field_scoped_write_leaves_other_pages_alone() -> None:
    """按字段写回的核心断言：改自己那页的操作，不会顶掉别人这期间写入的别的页。

    整份覆盖时，「只想改进度条」的写入会把手里过期的 gap_state 一起拍回库里，
    后台填写刚落库的产物就此消失——这是「AI 填了、组装却没有」的机制来源。
    """
    repository = ProjectStateRepository("postgres")
    repository.ensure_db()
    pid = "PRJ-FIELD-SCOPE"
    raw = lambda payload: payload
    base = {
        "id": pid,
        "bidType": BID_TYPE,
        "updatedAt": "2026-08-10T00:00:00Z",
        "gap_state": {"artifacts": []},
        "fill_state": {"status": "idle"},
    }
    try:
        repository.persist(base)
        # 两个进程在同一时刻各读一份
        tech = repository.load_one(pid, raw)
        generation = repository.load_one(pid, raw)

        # 技术标把 AI 填写产物写进缺口页
        tech["gap_state"]["artifacts"].append("投标关键数据一览表_AI填写.docx")
        repository.persist(tech, expected_rev=project_revision(tech))

        # 生成模块拿着过期快照回写，但只交自己那页
        generation["fill_state"]["status"] = "running"
        generation["updatedAt"] = "2026-08-10T00:00:05Z"
        repository.persist_fields(generation, ("fill_state", "updatedAt"))

        final = repository.load_one(pid, raw)
        assert final["gap_state"]["artifacts"] == ["投标关键数据一览表_AI填写.docx"]
        assert final["fill_state"]["status"] == "running"
    finally:
        repository.delete(pid)


@pytest.mark.integration
def test_field_scoped_write_skips_unlisted_changes() -> None:
    """漏列的字段不会落库——这是按字段写回最需要盯住的失败模式。"""
    repository = ProjectStateRepository("postgres")
    repository.ensure_db()
    pid = "PRJ-FIELD-MISS"
    raw = lambda payload: payload
    try:
        repository.persist({"id": pid, "bidType": BID_TYPE, "updatedAt": "2026-08-10T00:00:00Z",
                            "fill_state": {"status": "idle"}, "gap_state": {"note": "原值"}})
        project = repository.load_one(pid, raw)
        project["fill_state"]["status"] = "running"
        project["gap_state"]["note"] = "改了但没声明"
        repository.persist_fields(project, ("fill_state", "updatedAt"))

        final = repository.load_one(pid, raw)
        assert final["fill_state"]["status"] == "running"
        assert final["gap_state"]["note"] == "原值"
    finally:
        repository.delete(pid)


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
