from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from load_gold import load_gold_paths


def validate_gold_paths(paths: list[Path]) -> list[str]:
    rows = load_gold_paths(paths)
    errors: list[str] = []
    key_counts = Counter(row.key for row in rows)
    for key, count in key_counts.items():
        if count > 1:
            errors.append(
                "duplicate key: "
                f"{key.project_id}/{key.doc_type.value}/{key.locator}/{key.field_name} ({count} rows)"
            )
    if not rows:
        errors.append("no gold rows loaded")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate gold CSV files.")
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()

    errors = validate_gold_paths(args.paths)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("gold validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
