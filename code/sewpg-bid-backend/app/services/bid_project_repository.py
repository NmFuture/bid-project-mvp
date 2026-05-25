from __future__ import annotations

import json
from contextlib import closing
from typing import Any, Callable

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.core.config import settings


ProjectNormalizer = Callable[[dict[str, Any]], dict[str, Any]]


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

    def persist(self, project: dict[str, Any]) -> None:
        if not self.uses_postgres:
            return
        self.ensure_db()
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO projects (id, payload, updated_at)
                VALUES (%s, %s, %s)
                ON CONFLICT(id) DO UPDATE SET
                    payload=excluded.payload,
                    updated_at=excluded.updated_at
                """,
                (project["id"], Jsonb(project), project["updatedAt"]),
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
