#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from fontTools.ttLib import TTCollection


def family_names(font) -> set[str]:
    return {
        record.toUnicode()
        for record in font["name"].names
        if record.nameID in {1, 16}
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="从 Noto CJK TTC 中抽取单个 SC 字体")
    parser.add_argument("source")
    parser.add_argument("family")
    parser.add_argument("output")
    args = parser.parse_args()

    collection = TTCollection(args.source, recalcTimestamp=False)
    matches = [font for font in collection.fonts if args.family in family_names(font)]
    if len(matches) != 1:
        raise RuntimeError(f"{args.source}: expected one {args.family} face, found {len(matches)}")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    matches[0].save(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
