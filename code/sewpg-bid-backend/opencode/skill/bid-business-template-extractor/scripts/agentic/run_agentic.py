from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import doc_browser
from .finalizer import finalize, summary
from .paths import extraction_result_path, load_manifest
from .submission_store import submit
from .validator import validate


def print_json(payload: dict[str, Any]) -> int:
    sys.stdout.buffer.write((json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
    return 0


def _json_arg(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"json argument is invalid: {exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="btplnav")
    sub = parser.add_subparsers(dest="command")

    p_prepare = sub.add_parser("prepare")
    p_prepare.add_argument("manifest")

    p_overview = sub.add_parser("overview")
    p_overview.add_argument("manifest")
    p_overview.add_argument("--page", type=int, default=1)
    p_overview.add_argument("--page-size", type=int, default=30)

    p_search = sub.add_parser("search")
    p_search.add_argument("manifest")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=20)

    p_window = sub.add_parser("window")
    p_window.add_argument("manifest")
    p_window.add_argument("document_id")
    p_window.add_argument("block_id", type=int)
    p_window.add_argument("--before", type=int, default=4)
    p_window.add_argument("--after", type=int, default=8)

    p_read = sub.add_parser("read")
    p_read.add_argument("manifest")
    p_read.add_argument("document_id")
    p_read.add_argument("start_block_id", type=int)
    p_read.add_argument("end_block_id", type=int)
    p_read.add_argument("--max-chars", type=int, default=4000)

    p_submit = sub.add_parser("submit")
    p_submit.add_argument("manifest")
    p_submit.add_argument("target_key")
    p_submit.add_argument("json_value", type=_json_arg)

    p_validate = sub.add_parser("validate")
    p_validate.add_argument("manifest")

    p_status = sub.add_parser("status")
    p_status.add_argument("manifest")

    p_finalize = sub.add_parser("finalize")
    p_finalize.add_argument("manifest")

    return parser


def _status(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    from . import paths

    validation_path = paths.validation_report_path(manifest_path, manifest)
    validation = paths.read_json(validation_path) if validation_path.is_file() else {}
    return {
        "schemaVersion": "bid-business-template-status-v1",
        "prepared": paths.nav_path(manifest_path, manifest).is_file(),
        "navPath": str(paths.nav_path(manifest_path, manifest)),
        "submissionPath": str(paths.submission_path(manifest_path, manifest)),
        "validationReportPath": str(validation_path),
        "outputFile": str(paths.extraction_result_path(manifest_path, manifest)),
        "validationStatus": validation.get("status") if isinstance(validation, dict) else "",
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_usage()
        return 64
    manifest_path = Path(args.manifest).expanduser().resolve()
    manifest = load_manifest(manifest_path)
    if args.command == "prepare":
        return print_json(doc_browser.prepare(manifest_path, manifest))
    if args.command == "overview":
        return print_json(doc_browser.overview(manifest_path, manifest, page=args.page, page_size=args.page_size))
    if args.command == "search":
        return print_json(doc_browser.search(manifest_path, manifest, args.query, limit=args.limit))
    if args.command == "window":
        return print_json(
            doc_browser.window(
                manifest_path,
                manifest,
                args.document_id,
                args.block_id,
                before=args.before,
                after=args.after,
            )
        )
    if args.command == "read":
        return print_json(
            doc_browser.read(
                manifest_path,
                manifest,
                args.document_id,
                args.start_block_id,
                args.end_block_id,
                max_chars=args.max_chars,
            )
        )
    if args.command == "submit":
        return print_json(submit(manifest_path, manifest, args.target_key, args.json_value))
    if args.command == "validate":
        return print_json(validate(manifest_path, manifest))
    if args.command == "status":
        return print_json(_status(manifest_path, manifest))
    if args.command == "finalize":
        result = finalize(manifest_path, manifest)
        return print_json(summary(result, extraction_result_path(manifest_path, manifest)))
    parser.print_usage()
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
