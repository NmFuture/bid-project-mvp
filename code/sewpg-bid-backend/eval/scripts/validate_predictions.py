from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from load_predictions import load_prediction_paths


def validate_prediction_paths(paths: list[Path]) -> list[str]:
    rows = load_prediction_paths(paths)
    errors: list[str] = []
    key_counts = Counter(row.key for row in rows)
    for key, count in key_counts.items():
        if count > 1:
            errors.append(
                "duplicate key: "
                f"{key.project_id}/{key.doc_type.value}/{key.locator}/{key.field_name} ({count} rows)"
            )
    if not rows:
        errors.append("no prediction rows loaded")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate prediction CSV files.")
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()

    errors = validate_prediction_paths(args.paths)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("prediction validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
