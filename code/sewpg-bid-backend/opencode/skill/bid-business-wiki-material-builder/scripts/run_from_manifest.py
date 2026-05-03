#!/usr/bin/env python3
"""Business Wiki builder delegates to the shared minimal Wiki script."""

from __future__ import annotations

import runpy
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "bid-tech-wiki-material-builder" / "scripts" / "run_from_manifest.py"

runpy.run_path(str(SCRIPT), run_name="__main__")
