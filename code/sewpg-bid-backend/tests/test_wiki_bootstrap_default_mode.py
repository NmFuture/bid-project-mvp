from __future__ import annotations

import asyncio
from unittest.mock import patch

from app.api.routes import business as business_routes
from app.api.routes import technical as technical_routes

_ENQUEUED = {"jobId": "wiki-job-1", "status": "queued", "reused": False}


def test_technical_wiki_bootstrap_defaults_to_refresh_mode() -> None:
    with patch.object(
        technical_routes, "enqueue_material_wiki_generation", return_value=_ENQUEUED
    ) as enqueue:
        asyncio.run(technical_routes.technical_wiki_bootstrap({}))

    assert enqueue.call_args.kwargs["mode"] == "refresh"


def test_business_wiki_bootstrap_defaults_to_refresh_mode() -> None:
    with patch.object(
        business_routes, "enqueue_material_wiki_generation", return_value=_ENQUEUED
    ) as enqueue:
        asyncio.run(business_routes.business_wiki_bootstrap({}))

    assert enqueue.call_args.kwargs["mode"] == "refresh"


def test_wiki_bootstrap_keeps_explicit_mode() -> None:
    with patch.object(
        technical_routes, "enqueue_material_wiki_generation", return_value=_ENQUEUED
    ) as enqueue:
        asyncio.run(technical_routes.technical_wiki_bootstrap({"mode": "create"}))

    assert enqueue.call_args.kwargs["mode"] == "create"
