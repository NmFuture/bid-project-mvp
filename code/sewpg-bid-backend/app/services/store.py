from __future__ import annotations

import copy
import itertools
import re
from typing import Any

from app.core.config import settings
from app.services.bid_project_state import (
    create_project_state,
    delete_project_side_effects,
    normalize_project_identity_state,
    project_list_state,
    project_detail_state,
    project_stages_state,
    update_project_state,
    update_stage_state,
)
from app.services.bid_project_repository import ProjectStateRepository
from app.services.bid_runtime_state import ensure_project_runtime_states


class AppStore:
    def __init__(self, storage_backend: str | None = None) -> None:
        settings.ensure_dirs()
        self._storage_backend = (storage_backend or settings.project_store_backend or "postgres").strip().lower()
        self._repository = ProjectStateRepository(self._storage_backend)
        self._projects: dict[str, dict[str, Any]] = {}
        self._ensure_db()
        self._load_projects()
        self._counter = itertools.count(self._next_project_number())

    @staticmethod
    def _parse_project_number(project_id: str) -> int:
        match = re.fullmatch(r"PRJ-(\d{4,})", project_id)
        if not match:
            return 0
        return int(match.group(1))

    def _next_project_number(self) -> int:
        max_id = max((self._parse_project_number(project_id) for project_id in self._projects), default=0)
        return max_id + 1

    @property
    def _uses_postgres(self) -> bool:
        return self._repository.uses_postgres

    def _ensure_db(self) -> None:
        self._repository.ensure_db()

    def _load_projects(self) -> None:
        if not self._uses_postgres:
            return
        self._projects = self._repository.load_all(self._normalize_project_identity)

    def _load_project(self, project_id: str) -> dict[str, Any] | None:
        if not self._uses_postgres:
            return self._projects.get(project_id)
        project = self._repository.load_one(project_id, self._normalize_project_identity)
        if project is None:
            self._projects.pop(project_id, None)
            return None
        self._projects[project_id] = project
        return project

    def _persist_project(self, project: dict[str, Any]) -> None:
        self._repository.persist(project)

    def _delete_project_record(self, project_id: str) -> None:
        self._repository.delete(project_id)

    def reset_for_tests(self, *, clear_persistent: bool = False) -> None:
        self._projects = {}
        if clear_persistent:
            self._repository.clear()
        self._counter = itertools.count(1)

    @staticmethod
    def _normalize_project_identity(project: dict[str, Any]) -> dict[str, Any]:
        return normalize_project_identity_state(project)

    def _require(self, project_id: str) -> dict[str, Any]:
        project = self._load_project(project_id) or self._projects.get(project_id)
        if not project:
            raise KeyError(project_id)
        self._ensure_runtime_states(project)
        return project

    def _ensure_runtime_states(self, project: dict[str, Any]) -> dict[str, Any]:
        return ensure_project_runtime_states(project)

    def _detail(self, project: dict[str, Any]) -> dict[str, Any]:
        return project_detail_state(project)

    def list_projects(
        self,
        status: str = "",
        bid_type: str = "",
        date_range: str = "",
        page: int = 1,
        page_size: int = 12,
    ) -> dict[str, Any]:
        self._load_projects()
        return project_list_state(
            self._projects.values(),
            status=status,
            bid_type=bid_type,
            date_range=date_range,
            page=page,
            page_size=page_size,
        )

    def create_project(self, data: dict[str, Any]) -> dict[str, Any]:
        project_id = f"PRJ-{next(self._counter):04d}"
        project = create_project_state(project_id, data)
        self._normalize_project_identity(project)
        self._projects[project_id] = project
        self._persist_project(project)
        return self._detail(project)

    def get_project(self, project_id: str) -> dict[str, Any]:
        return self._detail(self._require(project_id))

    def get_project_runtime_state(self, project_id: str) -> dict[str, Any]:
        """Return the full persisted project payload for backend pipeline services."""
        return copy.deepcopy(self._require(project_id))

    def require_project_for_update(self, project_id: str) -> dict[str, Any]:
        """Return the mutable persisted project payload for service-layer state updates."""
        return self._require(project_id)

    def persist_project_state(self, project: dict[str, Any]) -> None:
        """Persist a project payload after a service-layer state mutation."""
        self._persist_project(project)

    def update_project(self, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
        project = self._require(project_id)
        update_project_state(project, project_id, data)
        self._normalize_project_identity(project)
        self._persist_project(project)
        return self._detail(project)

    def delete_project(self, project_id: str) -> None:
        project = self._require(project_id)
        delete_project_side_effects(project_id, project)
        self._projects.pop(project_id, None)
        self._delete_project_record(project_id)

    def get_stages(self, project_id: str) -> list[dict[str, Any]]:
        project = self._require(project_id)
        return project_stages_state(project)

    def update_stage(self, project_id: str, stage: int, data: dict[str, Any]) -> dict[str, Any]:
        project = self._require(project_id)
        payload = update_stage_state(project, stage, data)
        self._persist_project(project)
        return payload

store = AppStore()
