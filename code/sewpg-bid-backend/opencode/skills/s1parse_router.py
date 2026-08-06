#!/usr/bin/env python3
"""Route s1parse manifests to bid-type-specific parsing runners."""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path


CURRENT = Path(__file__).resolve()
SKILL_ROOT = CURRENT.parent

TECHNICAL_BID_TYPE = "技术标"
BUSINESS_BID_TYPE = "商务标"

RUNNERS = {
    TECHNICAL_BID_TYPE: SKILL_ROOT / "bid-tech-tender-structured-parser" / "scripts" / "run_from_manifest.py",
    BUSINESS_BID_TYPE: SKILL_ROOT / "bid-business-tender-structured-parser" / "scripts" / "run_from_manifest.py",
}

AGENTIC_COMMANDS = {
    "prepare",
    "overview",
    "search",
    "checklist",
    "read",
    "table",
    "window",
    "submit",
    "status",
    "validate",
    "finalize",
    "offline-fallback",
}

USAGE = (
    "usage: s1parse [prepare|overview|search|read|table|window|submit|status|validate|finalize] "
    "<manifest> [...]"
)


def _normalize_parse_profile(value: object) -> str:
    text = str(value or "").strip().lower()
    if text == "business":
        return BUSINESS_BID_TYPE
    if text == "technical":
        return TECHNICAL_BID_TYPE
    return ""


def _normalize_bid_type(value: object) -> str:
    text = str(value or "").strip()
    if "商务" in text or text.lower() == "business":
        return BUSINESS_BID_TYPE
    return TECHNICAL_BID_TYPE


def resolve_bid_type(manifest_path: Path) -> str:
    data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise RuntimeError(f"manifest must be a JSON object: {manifest_path}")
    return _normalize_parse_profile(data.get("parseProfile")) or _normalize_bid_type(data.get("bidType"))


def resolve_runner(manifest_path: Path) -> Path:
    bid_type = resolve_bid_type(manifest_path)
    runner = RUNNERS[bid_type]
    if not runner.exists():
        raise RuntimeError(f"{bid_type} S1 解析 runner 不存在：{runner}")
    return runner


def _split_args(argv: list[str]) -> tuple[str, Path, list[str]]:
    if len(argv) == 2:
        return "", Path(argv[1]).expanduser().resolve(), []
    if len(argv) >= 3:
        command = str(argv[1]).strip().lower()
        if command not in AGENTIC_COMMANDS:
            print(USAGE, file=sys.stderr)
            raise SystemExit(64)
        return command, Path(argv[2]).expanduser().resolve(), argv[3:]
    print(USAGE, file=sys.stderr)
    raise SystemExit(64)


def main() -> None:
    command, manifest_path, extra_args = _split_args(sys.argv)
    bid_type = resolve_bid_type(manifest_path)
    runner = resolve_runner(manifest_path)
    if command:
        sys.argv = [str(runner), command, str(manifest_path), *extra_args]
    else:
        sys.argv = [str(runner), str(manifest_path)]
    runpy.run_path(str(runner), run_name="__main__")


if __name__ == "__main__":
    main()
