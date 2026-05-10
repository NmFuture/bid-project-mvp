from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Iterable

from gold_schema import GoldRow


def load_gold_csv(path: Path) -> list[GoldRow]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            GoldRow.from_csv_row(row, source=f"{path}:{index}")
            for index, row in enumerate(reader, start=2)
        ]


def load_gold_paths(paths: Iterable[Path]) -> list[GoldRow]:
    rows: list[GoldRow] = []
    for path in paths:
        rows.extend(load_gold_csv(path))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Load gold CSV files and print the row count.")
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()

    rows = load_gold_paths(args.paths)
    print(f"loaded {len(rows)} gold rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
