from __future__ import annotations

from typing import Any

from sqlalchemy import text


def raw_folder_path_lock_key(folder_path: str) -> str:
    normalized = "/".join(
        segment
        for segment in str(folder_path or "").replace("\\", "/").split("/")
        if segment
    )
    return f"raw-folder-path:{normalized}"


async def lock_raw_folder_path(session: Any, folder_path: str) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
        {"lock_key": raw_folder_path_lock_key(folder_path)},
    )
