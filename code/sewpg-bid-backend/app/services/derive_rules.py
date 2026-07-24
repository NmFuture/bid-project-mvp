from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DerivedFact:
    field: str
    value: str
    unit: str
    rule: str
    sources: list[str]


def derive_core_facts(facts: dict[str, Any]) -> list[DerivedFact]:
    result: list[DerivedFact] = []
    single_mw = _number(facts.get("单机容量"))
    count = _number(facts.get("机组台数"))
    total_mw = _number(facts.get("总装机容量"))

    if single_mw and count and not total_mw:
        result.append(
            DerivedFact(
                field="总装机容量",
                value=f"{single_mw * count:g}",
                unit="MW",
                rule="single_capacity_mw * turbine_count",
                sources=["单机容量", "机组台数"],
            )
        )
    if total_mw and single_mw and not count:
        derived_count = total_mw / single_mw
        rounded = round(derived_count)
        if abs(derived_count - rounded) < 0.01:
            result.append(
                DerivedFact(
                    field="机组台数",
                    value=str(rounded),
                    unit="台",
                    rule="total_capacity_mw / single_capacity_mw",
                    sources=["总装机容量", "单机容量"],
                )
            )

    energy_mwh = _number(facts.get("保证发电量"))
    if energy_mwh and total_mw and not _number(facts.get("保证有效小时数")):
        result.append(
            DerivedFact(
                field="保证有效小时数",
                value=f"{energy_mwh / total_mw:g}",
                unit="h",
                rule="energy_mwh / total_capacity_mw",
                sources=["保证发电量", "总装机容量"],
            )
        )
    return result


def check_numeric_closure(facts: dict[str, Any], *, tolerance_ratio: float = 0.01) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    single_mw = _number(facts.get("单机容量"))
    count = _number(facts.get("机组台数"))
    total_mw = _number(facts.get("总装机容量"))
    if single_mw and count and total_mw:
        expected = single_mw * count
        tolerance = max(0.01, expected * tolerance_ratio)
        if abs(expected - total_mw) > tolerance:
            issues.append(
                {
                    "check": "capacity_closure",
                    "severity": "high",
                    "message": f"单机容量 x 机组台数 = {expected:g}MW, 与总装机容量 {total_mw:g}MW 不一致",
                    "expected": expected,
                    "actual": total_mw,
                }
            )
    return issues


def _number(value: Any) -> float | None:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(value or ""))
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None
