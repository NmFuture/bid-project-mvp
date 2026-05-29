from __future__ import annotations

from typing import Any

from sqlalchemy import desc, or_, select
from sqlalchemy.orm import selectinload

from app.models import async_session
from app.models.materials import RawFile, RawFolder
from app.services.material_raw_file_filter import build_raw_files_payload


async def raw_files_operation(
    *,
    bid_type: str,
    folder_path: str = "",
    project_id: str = "",
    customer_name: str = "",
    material_tier: str = "",
    clean_status: str = "",
    business_material_kind: str = "",
    tag: str = "",
    keyword: str = "",
    recursive: bool = True,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    async with async_session() as session:
        stmt = select(RawFile).options(selectinload(RawFile.folder))
        normalized_folder_path = str(folder_path or "").strip().strip("/")
        if normalized_folder_path:
            if recursive:
                stmt = stmt.join(RawFolder).where(
                    or_(
                        RawFolder.path == normalized_folder_path,
                        RawFolder.path.like(f"{normalized_folder_path}/%"),
                    )
                )
            else:
                stmt = stmt.join(RawFolder).where(RawFolder.path == normalized_folder_path)
        stmt = stmt.order_by(desc(RawFile.updated_at))
        result = await session.execute(stmt)
        items = result.scalars().all()

        return build_raw_files_payload(
            list(items),
            project_id=project_id,
            customer_name=customer_name,
            bid_type=bid_type,
            material_tier=material_tier,
            clean_status=clean_status,
            business_material_kind=business_material_kind,
            tag=tag,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
