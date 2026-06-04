#!/usr/bin/env python3
"""Route s1parse manifests to bid-type-specific parsing runners."""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path


CURRENT = Path(__file__).resolve()
SKILL_ROOT = CURRENT.parent

RUNNERS = {
    "技术标": SKILL_ROOT / "bid-tech-tender-structured-parser" / "scripts" / "run_from_manifest.py",
    "商务标": SKILL_ROOT / "bid-business-tender-structured-parser" / "scripts" / "run_from_manifest.py",
}
BUSINESS_STAGES = {
    "prepare",
    "finalize",
    "offline-fallback",
    "tasks",
    "status",
    "task",
    "validate-decision",
    "decision-all",
    "decision-set",
    "qualification-item",
}
BUSINESS_TASK_HELPERS = {"task", "validate-decision", "decision-all", "decision-set", "qualification-item"}


def _normalize_parse_profile(value: object) -> str:
    text = str(value or "").strip().lower()
    if text == "business":
        return "商务标"
    if text == "technical":
        return "技术标"
    return ""


def _normalize_bid_type(value: object) -> str:
    text = str(value or "").strip()
    if "商务" in text:
        return "商务标"
    return "技术标"


def resolve_bid_type(manifest_path: Path) -> str:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"manifest must be a JSON object: {manifest_path}")
    return _normalize_parse_profile(data.get("parseProfile")) or _normalize_bid_type(data.get("bidType"))


def resolve_runner(manifest_path: Path) -> Path:
    bid_type = resolve_bid_type(manifest_path)
    runner = RUNNERS[bid_type]
    if not runner.exists():
        raise RuntimeError(f"{bid_type} S1 解析 runner 不存在: {runner}")
    return runner


def main() -> None:
    if len(sys.argv) not in {2, 3, 4, 7, 9, 10}:
        print("usage: s1parse_router.py [prepare|finalize|offline-fallback|tasks|status|task|validate-decision|decision-all|decision-set|qualification-item] <manifest> [taskId] [...]", file=sys.stderr)
        raise SystemExit(64)

    stage = ""
    task_id = ""
    if len(sys.argv) == 2:
        manifest_path = Path(sys.argv[1]).expanduser().resolve()
    else:
        stage = str(sys.argv[1]).strip().lower()
        manifest_path = Path(sys.argv[2]).expanduser().resolve()
        if stage not in BUSINESS_STAGES:
            print("usage: s1parse_router.py [prepare|finalize|offline-fallback|tasks|status|task|validate-decision|decision-all|decision-set|qualification-item] <manifest> [taskId] [...]", file=sys.stderr)
            raise SystemExit(64)
        if len(sys.argv) == 4:
            task_id = str(sys.argv[3])
        elif len(sys.argv) > 4:
            task_id = str(sys.argv[3])
    if stage in BUSINESS_TASK_HELPERS and not task_id:
        print("usage: s1parse_router.py [task|validate-decision|decision-all|decision-set|qualification-item] <manifest> <taskId> [...]", file=sys.stderr)
        raise SystemExit(64)
    if task_id and stage not in BUSINESS_TASK_HELPERS:
        print("taskId and extra arguments are only supported for task helper commands", file=sys.stderr)
        raise SystemExit(64)

    bid_type = resolve_bid_type(manifest_path)
    if stage and bid_type != "商务标":
        print("stage argument is only supported for business s1parse manifests", file=sys.stderr)
        raise SystemExit(64)

    runner = resolve_runner(manifest_path)
    sys.argv = [str(runner), stage, str(manifest_path), *sys.argv[3:]] if task_id else [str(runner), stage, str(manifest_path)] if stage else [str(runner), str(manifest_path)]
    runpy.run_path(str(runner), run_name="__main__")


if __name__ == "__main__":
    main()
