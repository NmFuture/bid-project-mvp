from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import async_session
from app.models.materials import RawFile
from app.services.bid_type import GENERAL_BID_TYPE, TECHNICAL_BID_TYPE
from app.services.identity import classify_material_path
from app.services.minio_client import minio_client
from app.services.turbine_models import (
    extract_turbine_model_options_from_xlsx_bytes,
    turbine_model_from_material_name,
)


logger = logging.getLogger(__name__)


async def list_technical_turbine_model_options() -> dict[str, Any]:
    options: list[dict[str, Any]] = []
    fallback_hints: list[dict[str, Any]] = []

    async with async_session() as session:
        stmt = select(RawFile).options(selectinload(RawFile.folder))
        result = await session.execute(stmt)
        items = result.scalars().all()
        for item in items:
            item_bid_type = _raw_file_bid_type(item)
            if item_bid_type not in {TECHNICAL_BID_TYPE, GENERAL_BID_TYPE}:
                continue

            file_id = f"RAW-{item.id:04d}"
            folder_path = item.folder.path if item.folder else ""
            name = str(item.name or "")
            if _looks_like_turbine_parameter_sheet(name, folder_path):
                try:
                    data = minio_client.get_object(str(item.minio_bucket), str(item.minio_key))
                    options.extend(
                        extract_turbine_model_options_from_xlsx_bytes(
                            data,
                            source_file_id=file_id,
                            source_file_name=name,
                            folder_path=folder_path,
                        )
                    )
                except Exception as exc:
                    logger.warning("Failed to extract turbine model options from %s: %s", file_id, exc)

            hint = turbine_model_from_material_name(name, source_file_id=file_id, folder_path=folder_path)
            if hint:
                fallback_hints.append(
                    {
                        **hint,
                        "id": f"{hint['model']}-{file_id}",
                        "label": hint["model"],
                        "evidence": [{"sourceFileId": file_id, "sourceFileName": name, "folderPath": folder_path}],
                    }
                )

    deduped = _dedupe_turbine_options(options)
    if not deduped:
        deduped = _dedupe_turbine_options(fallback_hints)
    return {
        "items": deduped,
        "total": len(deduped),
        "source": "material_library",
        "bidType": TECHNICAL_BID_TYPE,
    }


def _raw_file_bid_type(item: RawFile) -> str:
    ext = item.ext_fields or {}
    explicit = str(ext.get("bidType") or "").strip()
    if explicit:
        return explicit

    folder = item.folder
    folder_bid_type = str(getattr(folder, "bid_type", "") or "").strip()
    if folder_bid_type:
        return folder_bid_type

    folder_path = str(getattr(folder, "path", "") or "").strip() if folder else ""
    if not folder_path:
        return ""
    location = classify_material_path(folder_path, GENERAL_BID_TYPE)
    return str(location.get("bidType") or "").strip()


def _looks_like_turbine_parameter_sheet(file_name: str, folder_path: str) -> bool:
    text = f"{folder_path}/{file_name}"
    return file_name.lower().endswith((".xlsx", ".xlsm", ".xls")) and (
        "投标机型参数" in text
        or "机型投标参数" in text
        or "机组主参数" in text
    )


def _dedupe_turbine_options(options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for option in options:
        model = str(option.get("model") or "").strip()
        if not model:
            continue
        key = "|".join(
            [
                model,
                str(option.get("platform") or ""),
                str(option.get("layout") or ""),
            ]
        )
        existing = merged.get(key)
        if existing is None:
            merged[key] = dict(option)
            continue
        evidence = list(existing.get("evidence") or [])
        for item in option.get("evidence") or []:
            if item not in evidence:
                evidence.append(item)
        aliases = list(existing.get("aliases") or [])
        for alias in option.get("aliases") or []:
            if alias not in aliases:
                aliases.append(alias)
        existing["evidence"] = evidence
        existing["aliases"] = aliases
    return sorted(
        merged.values(),
        key=lambda item: (
            str(item.get("platform") or ""),
            str(item.get("model") or ""),
            str(item.get("layout") or ""),
        ),
    )
