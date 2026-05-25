from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.models import async_session
from app.models.materials import RawFile, RawFolder
from app.services.material_raw_tree import build_raw_tree_payload


def _now_display() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


async def raw_tree_operation(
    *,
    bid_type: str,
    ensure_runtime_tables: Any,
    ensure_raw_material_roots: Any,
    session_factory: Any = async_session,
) -> dict[str, Any]:
    async with session_factory() as session:
        await ensure_runtime_tables(session)
        root_folders = await ensure_raw_material_roots(session)
        await session.commit()

        folders_result = await session.execute(select(RawFolder).order_by(RawFolder.sort_order, RawFolder.id))
        all_folders = folders_result.scalars().all()

        files_result = await session.execute(select(RawFile))
        all_files = files_result.scalars().all()

        return build_raw_tree_payload(
            root_folders=list(root_folders),
            all_folders=list(all_folders),
            all_files=list(all_files),
            bid_type=bid_type,
            updated_at=_now_display(),
        )
