from __future__ import annotations

import argparse
import re
from pathlib import Path


DEFAULT_PATTERNS = (
    r"PRJ-\d{4}",
    r"human_answer",
    r"eval/gold",
)


def lint_skill_hardcode(skill_dir: Path, patterns: tuple[str, ...] = DEFAULT_PATTERNS) -> list[str]:
    errors: list[str] = []
    compiled = [(pattern, re.compile(pattern)) for pattern in patterns]
    for path in _text_files(skill_dir):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            for pattern, regex in compiled:
                if regex.search(line):
                    errors.append(f"{path}:{line_no}: forbidden hardcode pattern {pattern!r}")
    return errors


def _text_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    ignored_suffixes = {".docx", ".xlsx", ".png", ".jpg", ".jpeg", ".pdf", ".zip", ".pyc"}
    return [
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() not in ignored_suffixes
        and "__pycache__" not in path.parts
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint skill code for evaluation or sample-answer hardcoding.")
    parser.add_argument("--skill-dir", type=Path, default=Path(__file__).resolve().parents[2] / "opencode" / "skill")
    args = parser.parse_args()

    errors = lint_skill_hardcode(args.skill_dir)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("skill hardcode lint passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
