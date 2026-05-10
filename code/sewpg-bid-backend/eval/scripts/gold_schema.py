from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar


class DocType(str, Enum):
    APPENDIX = "appendix"
    BODY = "body"


class FieldType(str, Enum):
    NUMERIC = "numeric"
    ENUM = "enum"
    PHRASE = "phrase"
    PARAGRAPH = "paragraph"
    LIST = "list"
    NOT_FILLABLE = "not_fillable"


class DifficultyTier(str, Enum):
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"
    T4 = "T4"
    T5 = "T5"


EnumT = TypeVar("EnumT", bound=Enum)


GOLD_COLUMNS = (
    "project_id",
    "doc_type",
    "locator",
    "field_name",
    "human_answer",
    "field_type",
    "difficulty_tier",
    "evidence_source",
)

PREDICTION_COLUMNS = (
    "project_id",
    "doc_type",
    "locator",
    "field_name",
    "predicted_answer",
    "mark_yellow",
    "evidence_refs",
    "skill_name",
    "fill_path",
    "confidence",
)


@dataclass(frozen=True)
class FieldKey:
    project_id: str
    doc_type: DocType
    locator: str
    field_name: str


@dataclass(frozen=True)
class GoldRow:
    project_id: str
    doc_type: DocType
    locator: str
    field_name: str
    human_answer: str
    field_type: FieldType
    difficulty_tier: DifficultyTier
    evidence_source: str = ""

    @property
    def key(self) -> FieldKey:
        return FieldKey(
            project_id=self.project_id,
            doc_type=self.doc_type,
            locator=self.locator,
            field_name=self.field_name,
        )

    @classmethod
    def from_csv_row(cls, row: dict[str, Any], *, source: str = "csv") -> "GoldRow":
        missing = [column for column in GOLD_COLUMNS if column not in row]
        if missing:
            raise ValueError(f"{source}: missing columns: {', '.join(missing)}")

        project_id = _required_text(row, "project_id", source)
        locator = _required_text(row, "locator", source)
        field_name = _required_text(row, "field_name", source)
        doc_type = _enum_value(DocType, row.get("doc_type"), "doc_type", source)
        field_type = _enum_value(FieldType, row.get("field_type"), "field_type", source)
        tier = _enum_value(DifficultyTier, row.get("difficulty_tier"), "difficulty_tier", source)
        human_answer = str(row.get("human_answer") or "").strip()

        if tier is not DifficultyTier.T5 and field_type is not FieldType.NOT_FILLABLE and not human_answer:
            raise ValueError(f"{source}: non-T5 row must have human_answer for {project_id}/{locator}/{field_name}")
        if field_type is FieldType.NOT_FILLABLE and tier is not DifficultyTier.T5:
            raise ValueError(f"{source}: not_fillable rows must use difficulty_tier=T5 for {project_id}/{locator}/{field_name}")

        return cls(
            project_id=project_id,
            doc_type=doc_type,
            locator=locator,
            field_name=field_name,
            human_answer=human_answer,
            field_type=field_type,
            difficulty_tier=tier,
            evidence_source=str(row.get("evidence_source") or "").strip(),
        )


@dataclass(frozen=True)
class PredictionRow:
    project_id: str
    doc_type: DocType
    locator: str
    field_name: str
    predicted_answer: str
    mark_yellow: bool
    evidence_refs: str
    skill_name: str
    fill_path: str = ""
    confidence: float | None = None

    @property
    def key(self) -> FieldKey:
        return FieldKey(
            project_id=self.project_id,
            doc_type=self.doc_type,
            locator=self.locator,
            field_name=self.field_name,
        )

    @classmethod
    def from_csv_row(cls, row: dict[str, Any], *, source: str = "csv") -> "PredictionRow":
        missing = [column for column in PREDICTION_COLUMNS if column not in row]
        if missing:
            raise ValueError(f"{source}: missing columns: {', '.join(missing)}")

        confidence_text = str(row.get("confidence") or "").strip()
        confidence = None
        if confidence_text:
            try:
                confidence = float(confidence_text)
            except ValueError as exc:
                raise ValueError(f"{source}: confidence must be numeric") from exc
            if not 0 <= confidence <= 1:
                raise ValueError(f"{source}: confidence must be between 0 and 1")

        return cls(
            project_id=_required_text(row, "project_id", source),
            doc_type=_enum_value(DocType, row.get("doc_type"), "doc_type", source),
            locator=_required_text(row, "locator", source),
            field_name=_required_text(row, "field_name", source),
            predicted_answer=str(row.get("predicted_answer") or "").strip(),
            mark_yellow=_bool_value(row.get("mark_yellow"), "mark_yellow", source),
            evidence_refs=str(row.get("evidence_refs") or "").strip(),
            skill_name=_required_text(row, "skill_name", source),
            fill_path=str(row.get("fill_path") or "").strip(),
            confidence=confidence,
        )


def _required_text(row: dict[str, Any], key: str, source: str) -> str:
    value = str(row.get(key) or "").strip()
    if not value:
        raise ValueError(f"{source}: {key} is required")
    return value


def _enum_value(enum_type: type[EnumT], value: Any, key: str, source: str) -> EnumT:
    text = str(value or "").strip()
    try:
        return enum_type(text)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise ValueError(f"{source}: invalid {key}={text!r}; allowed: {allowed}") from exc


def _bool_value(value: Any, key: str, source: str) -> bool:
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    raise ValueError(f"{source}: invalid {key}={value!r}; allowed: true/false")
