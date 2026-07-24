from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Iterable

from gold_schema import PredictionRow


def load_prediction_csv(path: Path) -> list[PredictionRow]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            PredictionRow.from_csv_row(row, source=f"{path}:{index}")
            for index, row in enumerate(reader, start=2)
        ]


def load_prediction_paths(paths: Iterable[Path]) -> list[PredictionRow]:
    rows: list[PredictionRow] = []
    for path in paths:
        rows.extend(load_prediction_csv(path))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Load prediction CSV files and print the row count.")
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()

    rows = load_prediction_paths(args.paths)
    print(f"loaded {len(rows)} prediction rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
