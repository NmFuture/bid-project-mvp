from __future__ import annotations

from datetime import datetime
from typing import Any


class PeripheralError(Exception):
    def __init__(
        self,
        status_code: int,
        detail: str,
        code: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.code = code
        self.extra = extra or {}

    def to_payload(self) -> dict[str, Any]:
        payload = {"detail": self.detail, "code": self.code}
        payload.update(self.extra)
        return payload


def now_day() -> str:
    return datetime.now().strftime("%Y%m%d")
