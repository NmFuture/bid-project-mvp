from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from app.core.config import settings

try:  # pragma: no cover - exercised when the optional dependency is installed
    from redis import Redis
    from redis.exceptions import RedisError
except ImportError:  # pragma: no cover - keeps local tests usable before pip install
    Redis = None  # type: ignore[assignment]

    class RedisError(Exception):
        pass


logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_redis_client() -> Any | None:
    if not settings.redis_url or Redis is None:
        return None

    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=10,
    )


def redis_is_available() -> bool:
    client = get_redis_client()
    if client is None:
        return False
    try:
        return bool(client.ping())
    except RedisError as exc:
        logger.warning("Redis is not available: %s", exc)
        return False
