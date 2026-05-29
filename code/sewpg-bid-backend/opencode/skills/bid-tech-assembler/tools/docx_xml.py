#!/usr/bin/env python3
import argparse
from pathlib import Path
from zipfile import ZipFile


def cmd_list(docx_path: Path) -> int:
    with ZipFile(docx_path) as zf:
        for name in sorted(zf.namelist()):
            print(name)
    return 0


def cmd_show(docx_path: Path, part_name: str) -> int:
    with ZipFile(docx_path) as zf:
        data = zf.read(part_name)
    try:
        print(data.decode("utf-8"))
    except UnicodeDecodeError:
        print(data.decode("utf-8", errors="replace"))
    return 0


def cmd_extract(docx_path: Path, part_name: str, output_path: Path) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(docx_path) as zf:
        data = zf.read(part_name)
    output_path.write_bytes(data)
    print(output_path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect or extract OOXML parts from a DOCX file.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List all package parts in the DOCX.")
    list_parser.add_argument("docx_path", type=Path)

    show_parser = subparsers.add_parser("show", help="Print one package part to stdout.")
    show_parser.add_argument("docx_path", type=Path)
    show_parser.add_argument("part_name")

    extract_parser = subparsers.add_parser("extract", help="Extract one package part to a file.")
    extract_parser.add_argument("docx_path", type=Path)
    extract_parser.add_argument("part_name")
    extract_parser.add_argument("-o", "--output", required=True, type=Path)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "list":
        return cmd_list(args.docx_path)
    if args.command == "show":
        return cmd_show(args.docx_path, args.part_name)
    if args.command == "extract":
        return cmd_extract(args.docx_path, args.part_name, args.output)

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
