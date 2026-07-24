from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class KnowledgeLockStatus(str, Enum):
    LOCKED_BY_USER = "locked_by_user"
    SYSTEM_HIGH_CONF = "system_high_conf"
    UNCONFIRMED = "unconfirmed"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class KnowledgeSource:
    doc: str
    quote: str = ""
    confidence: float = 0.0
    location: str = ""
    source_type: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KnowledgeSource":
        return cls(
            doc=str(data.get("doc") or data.get("sourceFile") or ""),
            quote=str(data.get("quote") or data.get("evidence") or ""),
            confidence=_clamp_confidence(data.get("confidence")),
            location=str(data.get("location") or data.get("evidenceLocation") or ""),
            source_type=str(data.get("source_type") or data.get("type") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KnowledgeCard:
    field: str
    value: str
    variants: dict[str, str] = field(default_factory=dict)
    sources: list[KnowledgeSource] = field(default_factory=list)
    lock_status: KnowledgeLockStatus = KnowledgeLockStatus.UNCONFIRMED

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KnowledgeCard":
        return cls(
            field=str(data.get("field") or ""),
            value=str(data.get("value") or ""),
            variants={
                str(key): str(value)
                for key, value in (data.get("variants") if isinstance(data.get("variants"), dict) else {}).items()
            },
            sources=[
                KnowledgeSource.from_dict(item)
                for item in (data.get("sources") if isinstance(data.get("sources"), list) else [])
                if isinstance(item, dict)
            ],
            lock_status=KnowledgeLockStatus(str(data.get("lock_status") or KnowledgeLockStatus.UNCONFIRMED.value)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "value": self.value,
            "variants": dict(self.variants),
            "sources": [source.to_dict() for source in self.sources],
            "lock_status": self.lock_status.value,
        }

    def is_locked(self) -> bool:
        return self.lock_status in {KnowledgeLockStatus.LOCKED_BY_USER, KnowledgeLockStatus.SYSTEM_HIGH_CONF}


def card_from_fact_field(field: dict[str, Any]) -> KnowledgeCard:
    sources = [
        KnowledgeSource.from_dict(item)
        for item in (field.get("sourceRefs") if isinstance(field.get("sourceRefs"), list) else [])
        if isinstance(item, dict)
    ]
    status = str(field.get("status") or "")
    confidence = _clamp_confidence(field.get("confidence"))
    if status == "confirmed":
        lock_status = KnowledgeLockStatus.LOCKED_BY_USER
    elif status == "conflict":
        lock_status = KnowledgeLockStatus.CONFLICT
    elif confidence >= 0.9:
        lock_status = KnowledgeLockStatus.SYSTEM_HIGH_CONF
    else:
        lock_status = KnowledgeLockStatus.UNCONFIRMED
    return KnowledgeCard(
        field=str(field.get("label") or field.get("field") or ""),
        value=str(field.get("value") or ""),
        variants={},
        sources=sources,
        lock_status=lock_status,
    )


def _clamp_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))
