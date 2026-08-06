from __future__ import annotations

import logging
import re

from app.core.config import settings
from app.services.minio_client import minio_client

logger = logging.getLogger(__name__)


def fulltext_object_prefix(raw_file_id: int) -> str:
    return f"parsed/RAW-{int(raw_file_id):04d}/"


def fulltext_object_key(raw_file_id: int, source_version: int) -> str:
    return f"{fulltext_object_prefix(raw_file_id)}v{int(source_version or 1)}/fulltext.md"


def purge_material_fulltext_objects(
    raw_file_id: int,
    source_version: int,
    *,
    max_source_version: int | None = None,
) -> int:
    """Best-effort cleanup of one material's canonical fulltext objects."""

    bucket = str(settings.minio_buckets["materials"])
    prefix = fulltext_object_prefix(raw_file_id)
    keys = {fulltext_object_key(raw_file_id, source_version)}
    try:
        for listed_key in minio_client.list_object_keys(bucket, prefix):
            key = str(listed_key or "")
            match = re.fullmatch(rf"{re.escape(prefix)}v(\d+)/fulltext\.md", key)
            if match:
                if max_source_version is None or int(match.group(1)) <= max_source_version:
                    keys.add(key)
                continue
            if key:
                logger.warning("Ignore fulltext object outside expected version scope %s: %s", prefix, key)
    except Exception as exc:  # pragma: no cover - listing failure must not overturn committed DB changes
        logger.warning("Failed to list material fulltext objects %s/%s: %s", bucket, prefix, exc)

    removed = 0
    for key in sorted(keys):
        try:
            minio_client.remove_object(bucket, key)
            removed += 1
        except Exception as exc:  # pragma: no cover - clean remaining objects after one failure
            logger.warning("Failed to remove material fulltext object %s/%s: %s", bucket, key, exc)
    return removed
