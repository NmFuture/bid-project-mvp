from __future__ import annotations

import sys
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
SKILL_DIR = CURRENT_DIR.parent
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from scripts.agentic.run_agentic import main as agentic_main  # noqa: E402


AGENTIC_COMMANDS = {"prepare", "overview", "search", "read", "window", "submit", "validate", "status", "finalize"}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in AGENTIC_COMMANDS:
        print(
            "usage: run_from_manifest.py "
            "[prepare|overview|search|read|window|submit|validate|status|finalize] <manifest> [...]",
            file=sys.stderr,
        )
        return 64
    return agentic_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
