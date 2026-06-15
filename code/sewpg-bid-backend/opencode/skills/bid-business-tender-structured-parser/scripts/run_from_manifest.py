from __future__ import annotations

import sys
from pathlib import Path

CURRENT = Path(__file__).resolve()
SCRIPT_DIR = CURRENT.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from agentic.run_agentic import main


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 1:
        args = ["prepare", args[0]]
    raise SystemExit(main(args))
