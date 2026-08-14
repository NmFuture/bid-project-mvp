from __future__ import annotations

import json
from contextlib import closing
from typing import Any, Callable

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.core.config import settings


ProjectNormalizer = Callable[[dict[str, Any]], dict[str, Any]]

# 项目状态整份 JSONB 覆盖写，读与写之间往往隔着数十秒的慢操作（AI 填写、素材下载），
# worker 与 API 是独立进程，无条件覆盖会让后写的一方整份盖掉先写方的改动。
# `_rev` 是 payload 内的乐观锁版本号：读时带出，写时校验，不匹配即拒绝写入。
PROJECT_REVISION_KEY = "_rev"

# 项目编号序列。编号一旦发出就不再回收：删项目不回退，进程重启也不重新推导，
# 避免新项目拿到旧编号后落进同名的磁盘工作区、读到上一轮的状态文件。
PROJECT_ID_SEQUENCE = "project_id_seq"


class ProjectConcurrentUpdateError(RuntimeError):
    """CAS 失败：读取快照后已有其他进程写入同一项目。"""

    def __init__(self, project_id: str) -> None:
        super().__init__(f"项目 {project_id} 已被其他操作更新，请基于最新状态重试。")
        self.project_id = project_id


def project_revision(project: dict[str, Any]) -> int:
    try:
        return int(project.get(PROJECT_REVISION_KEY) or 0)
    except (TypeError, ValueError):
        return 0


class ProjectStateRepository:
    """Persistence adapter for the project JSONB state table."""

    def __init__(self, storage_backend: str) -> None:
        self._storage_backend = storage_backend

    @property
    def uses_postgres(self) -> bool:
        return self._storage_backend == "postgres"

    @staticmethod
    def _postgres_dsn() -> str:
        return settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1).replace(
            "postgresql+psycopg://",
            "postgresql://",
            1,
        )

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self._postgres_dsn(), row_factory=dict_row)

    def ensure_db(self) -> None:
        if not self.uses_postgres:
            return
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id VARCHAR(50) PRIMARY KEY,
                    payload JSONB NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.commit()

    def ensure_project_id_sequence(self) -> None:
        """建项目编号序列，并把它对齐到不低于库里已有的最大编号。

        序列只前进不后退：`setval` 取「已有最大编号」与「序列当前值」的较大者，
        因此重复调用幂等，也不会因为删掉高编号项目而回退。调用方只在进程启动时
        执行一次（`AppStore._ensure_db`），不要放进 `ensure_db`——后者每次读写
        项目都会跑，多一次全表扫描不划算。
        """
        if not self.uses_postgres:
            return
        with closing(self._connect()) as connection:
            connection.execute(f"CREATE SEQUENCE IF NOT EXISTS {PROJECT_ID_SEQUENCE}")
            # is_called=false 时 last_value 就是下一个要发的号，为 true 时下一个是 last_value+1。
            # 不读这个标志直接 setval 会把「还没发出的 1」当成「已发出的 1」，每次初始化白吃一个号。
            state = connection.execute(
                f"SELECT last_value, is_called FROM {PROJECT_ID_SEQUENCE}"
            ).fetchone() or {}
            last_value = int(state.get("last_value") or 0)
            next_value = last_value + 1 if bool(state.get("is_called")) else last_value

            row = connection.execute(
                """
                SELECT COALESCE(
                    MAX(CASE WHEN id ~ '^PRJ-[0-9]+$' THEN substring(id from 5)::bigint END),
                    0
                ) AS max_existing
                FROM projects
                """
            ).fetchone() or {}
            max_existing = int(row.get("max_existing") or 0)

            # 只在序列会发出已被占用的编号时才前进，正常启动不动序列。
            if max_existing >= next_value:
                connection.execute(
                    f"SELECT setval('{PROJECT_ID_SEQUENCE}', %s, true)", (max_existing,)
                )
            connection.commit()

    def next_project_number(self) -> int:
        """取下一个项目编号。

        编号来自独立序列，不参考 `projects` 表的当前内容，因此删除项目（乃至清空
        整张表）都不会让编号回收复用。
        """
        with closing(self._connect()) as connection:
            row = connection.execute(f"SELECT nextval('{PROJECT_ID_SEQUENCE}') AS value").fetchone()
            connection.commit()
        return int((row or {}).get("value") or 0)

    def reset_project_id_sequence(self) -> None:
        """仅供测试重置：把序列拨回从 1 重新发号。"""
        if not self.uses_postgres:
            return
        with closing(self._connect()) as connection:
            connection.execute(f"CREATE SEQUENCE IF NOT EXISTS {PROJECT_ID_SEQUENCE}")
            connection.execute(f"SELECT setval('{PROJECT_ID_SEQUENCE}', 1, false)")
            connection.commit()

    @staticmethod
    def _decode_payload(payload: Any) -> dict[str, Any]:
        return payload if isinstance(payload, dict) else json.loads(str(payload))

    def load_all(self, normalize_project: ProjectNormalizer) -> dict[str, dict[str, Any]]:
        if not self.uses_postgres:
            return {}
        self.ensure_db()
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT id, payload FROM projects").fetchall()
        return {str(row["id"]): normalize_project(self._decode_payload(row["payload"])) for row in rows}

    def load_one(self, project_id: str, normalize_project: ProjectNormalizer) -> dict[str, Any] | None:
        if not self.uses_postgres:
            return None
        self.ensure_db()
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT id, payload FROM projects WHERE id = %s", (project_id,)).fetchone()
        if row is None:
            return None
        return normalize_project(self._decode_payload(row["payload"]))

    def persist(self, project: dict[str, Any], *, expected_rev: int | None = None) -> None:
        """写回项目状态。

        `expected_rev` 为 None 时保持无条件覆盖（建项目等无并发语义的路径）；
        传入版本号时走 CAS：只有库里仍是该版本才写，否则抛
        ``ProjectConcurrentUpdateError`` 交由调用方基于最新状态重放。
        """
        if not self.uses_postgres:
            # 内存后端下 require/persist 操作的是同一个 dict 实例，不存在丢更新。
            return
        self.ensure_db()
        next_rev = project_revision(project) + 1
        payload = dict(project)
        payload[PROJECT_REVISION_KEY] = next_rev
        with closing(self._connect()) as connection:
            if expected_rev is None:
                connection.execute(
                    """
                    INSERT INTO projects (id, payload, updated_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT(id) DO UPDATE SET
                        payload=excluded.payload,
                        updated_at=excluded.updated_at
                    """,
                    (project["id"], Jsonb(payload), project["updatedAt"]),
                )
            else:
                cursor = connection.execute(
                    """
                    UPDATE projects SET payload=%s, updated_at=%s
                    WHERE id=%s AND COALESCE((payload->>'_rev')::bigint, 0) = %s
                    """,
                    (Jsonb(payload), project["updatedAt"], project["id"], expected_rev),
                )
                if cursor.rowcount == 0:
                    existing = connection.execute(
                        "SELECT 1 FROM projects WHERE id = %s", (project["id"],)
                    ).fetchone()
                    if existing is not None:
                        connection.rollback()
                        raise ProjectConcurrentUpdateError(str(project["id"]))
                    connection.execute(
                        "INSERT INTO projects (id, payload, updated_at) VALUES (%s, %s, %s)",
                        (project["id"], Jsonb(payload), project["updatedAt"]),
                    )
            connection.commit()
        project[PROJECT_REVISION_KEY] = next_rev

    def persist_fields(self, project: dict[str, Any], fields: tuple[str, ...]) -> None:
        """只写回指定的顶层字段，库里其余字段原样保留。

        项目状态是一份大 JSONB，整份覆盖写会让「只改进度条」的操作把别人这期间写入的
        业务数据一起顶回旧值。按字段写回后，改不同字段的操作彼此不再相干，也不必重试。
        同一字段仍可能被多方并发修改，那种情况要另外用 `_rev` 兜。
        """
        if not self.uses_postgres:
            # 内存后端下 require/persist 操作的是同一个 dict 实例，不存在覆盖问题。
            return
        patch = {key: project[key] for key in fields if key in project}
        if not patch:
            return
        self.ensure_db()
        with closing(self._connect()) as connection:
            connection.execute(
                "UPDATE projects SET payload = payload || %s, updated_at = %s WHERE id = %s",
                (Jsonb(patch), project["updatedAt"], project["id"]),
            )
            connection.commit()

    def delete(self, project_id: str) -> None:
        if not self.uses_postgres:
            return
        self.ensure_db()
        with closing(self._connect()) as connection:
            connection.execute("DELETE FROM projects WHERE id = %s", (project_id,))
            connection.commit()

    def clear(self) -> None:
        if not self.uses_postgres:
            return
        self.ensure_db()
        with closing(self._connect()) as connection:
            connection.execute("DELETE FROM projects")
            connection.commit()
