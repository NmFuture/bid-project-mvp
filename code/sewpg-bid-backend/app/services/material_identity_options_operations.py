from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select, text

from app.models import async_session
from app.models.materials import RawFile, RawFolder
from app.services.material_identity_options import build_material_identity_options

logger = logging.getLogger(__name__)


async def identity_options_operation(
    *,
    bid_type: str,
    ensure_runtime_tables: Any,
    ensure_raw_material_roots: Any,
    session_factory: Any = async_session,
    include_project_store: bool = True,
    folder_name_as_project_name: bool = False,
) -> dict[str, Any]:
    async with session_factory() as session:
        await ensure_runtime_tables(session)
        await ensure_raw_material_roots(session)
        await session.commit()
        folders = (await session.execute(select(RawFolder))).scalars().all()
        files = (await session.execute(select(RawFile))).scalars().all()

        project_rows: list[Any] = []
        if include_project_store:
            try:
                project_rows = (
                    (await session.execute(text("SELECT id, payload FROM projects")))
                    .mappings()
                    .all()
                )
            except Exception as exc:  # pragma: no cover - keeps material options usable before project store init.
                logger.debug("Skip project-store identity options: %s", exc)
                project_rows = []

    return build_material_identity_options(
        folders=list(folders),
        files=list(files),
        project_rows=list(project_rows),
        bid_type=bid_type,
        include_project_store=include_project_store,
        folder_name_as_project_name=folder_name_as_project_name,
    )
