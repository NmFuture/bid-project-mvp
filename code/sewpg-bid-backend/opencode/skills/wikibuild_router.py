#!/usr/bin/env python3
"""Route wikibuild manifests to the correct bid-type-specific runner."""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path


CURRENT = Path(__file__).resolve()
SKILL_ROOT = CURRENT.parent

RUNNERS = {
    "技术标": SKILL_ROOT / "bid-tech-wiki-material-builder" / "scripts" / "run_from_manifest.py",
    "商务标": SKILL_ROOT / "bid-business-wiki-material-builder" / "scripts" / "run_from_manifest.py",
}


def normalize_bid_type(value: object) -> str:
    text = str(value or "").strip()
    return text if text in RUNNERS else "技术标"


def resolve_runner(manifest_path: Path) -> Path:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"manifest must be a JSON object: {manifest_path}")
    bid_type = normalize_bid_type(data.get("targetBidType"))
    runner = RUNNERS[bid_type]
    if not runner.exists():
        raise RuntimeError(f"{bid_type} Wiki runner 不存在: {runner}")
    return runner


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: wikibuild_router.py <manifest>")
    manifest_path = Path(sys.argv[1]).expanduser().resolve()
    runner = resolve_runner(manifest_path)
    sys.argv = [str(runner), str(manifest_path)]
    runpy.run_path(str(runner), run_name="__main__")


if __name__ == "__main__":
    main()
