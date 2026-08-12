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
