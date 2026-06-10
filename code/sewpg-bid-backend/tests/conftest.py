from __future__ import annotations

import os


os.environ.setdefault("APP_STORE_BACKEND", "memory")

import pytest


@pytest.fixture(autouse=True)
def _reset_business_bidder_profile():
    from app.services import business_bidder_profile

    business_bidder_profile._memory_profile.clear()
    yield
    business_bidder_profile._memory_profile.clear()
