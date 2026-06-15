from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.models import async_session
from app.models.materials import SystemConfig
from app.services.file_utils import run_awaitable_sync

BUSINESS_BIDDER_FACTS_CONFIG_KEY = "business_bidder_facts"

# 非 postgres（memory）模式下的进程内档案，测试环境不触碰真实数据库
_memory_profile: dict[str, str] = {}


def _use_database() -> bool:
    return str(settings.project_store_backend or "").lower() == "postgres"


def _clean_values(values: Any) -> dict[str, str]:
    if not isinstance(values, dict):
        return {}
    cleaned: dict[str, str] = {}
    for key, value in values.items():
        label = str(key or "").strip()
        text = str(value or "").strip()
        if label and text:
            cleaned[label] = text
    return cleaned


async def load_business_bidder_facts() -> dict[str, str]:
    if not _use_database():
        return dict(_memory_profile)
    async with async_session() as session:
        row = (
            await session.execute(
                select(SystemConfig).where(SystemConfig.key == BUSINESS_BIDDER_FACTS_CONFIG_KEY)
            )
        ).scalar_one_or_none()
    return _clean_values(row.value if row is not None else {})


async def store_business_bidder_facts(values: dict[str, Any], *, updated_by: str = "") -> dict[str, str]:
    payload = _clean_values(values)
    if not payload:
        return {}
    if not _use_database():
        _memory_profile.update(payload)
        return dict(_memory_profile)
    async with async_session() as session:
        row = (
            await session.execute(
                select(SystemConfig).where(SystemConfig.key == BUSINESS_BIDDER_FACTS_CONFIG_KEY)
            )
        ).scalar_one_or_none()
        if row is None:
            row = SystemConfig(key=BUSINESS_BIDDER_FACTS_CONFIG_KEY, value=payload, sensitive=False, updated_by=updated_by)
            session.add(row)
        else:
            merged = _clean_values(row.value)
            merged.update(payload)
            row.value = merged
            if updated_by:
                row.updated_by = updated_by
        await session.commit()
        return _clean_values(row.value)


def load_business_bidder_facts_sync() -> dict[str, str]:
    try:
        return run_awaitable_sync(load_business_bidder_facts())
    except Exception:
        return {}
