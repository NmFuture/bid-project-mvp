from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import docx_indexer, navigator_cli
from .checklist import load_checklist, load_shards
from .finalizer import SKILL_NAME, finalize, summary
from .paths import (
    document_map_path,
    load_manifest,
    nav_store_path,
    structured_result_path,
    submission_path,
    validation_report_path,
)
from .submission_store import shard_progress, submit
from .validator import validate


def print_json(payload: dict[str, Any]) -> int:
    output = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    sys.stdout.buffer.write(output.encode("utf-8"))
    return 0


def prepare(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    payload = docx_indexer.build_index(manifest_path, manifest)
    payload.update(
        {
            "targetSkill": SKILL_NAME,
            "checklistCount": len(load_checklist()),
            "shards": [
                {"key": shard["key"], "label": shard["label"], "rowCount": len(shard["rowNos"])}
                for shard in load_shards()
            ],
            "structuredResultPath": str(structured_result_path(manifest_path, manifest)),
            "submissionPath": str(submission_path(manifest_path, manifest)),
            "validationReportPath": str(validation_report_path(manifest_path, manifest)),
        }
    )
    return payload


def status(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    nav_path = nav_store_path(manifest_path, manifest)
    map_path = document_map_path(manifest_path, manifest)
    sub_path = submission_path(manifest_path, manifest)
    val_path = validation_report_path(manifest_path, manifest)
    submitted = {}
    if sub_path.is_file():
        try:
            submitted = json.loads(sub_path.read_text(encoding="utf-8")).get("targets") or {}
        except Exception:
            submitted = {}
    validation = {}
    if val_path.is_file():
        try:
            validation = json.loads(val_path.read_text(encoding="utf-8"))
        except Exception:
            validation = {}
    return {
        "schemaVersion": "bid-tech-agentic-status-v1",
        "targetSkill": SKILL_NAME,
        "navStorePath": str(nav_path),
        "documentMapPath": str(map_path),
        "submissionPath": str(sub_path),
        "validationReportPath": str(val_path),
        "checklistCount": len(load_checklist()),
        "prepared": nav_path.is_file() and map_path.is_file(),
        "submittedTargets": sorted(submitted.keys()),
        "submittedTargetCount": len(submitted),
        "validationStatus": validation.get("status") or "",
        "missingTargets": validation.get("missingTargets") or [],
        "validationErrors": validation.get("validationErrors") or [],
        **shard_progress(manifest_path, manifest),
    }


def _json_arg(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"json argument is invalid: {exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="s1parse")
    sub = parser.add_subparsers(dest="command")

    p_prepare = sub.add_parser("prepare")
    p_prepare.add_argument("manifest")

    p_overview = sub.add_parser("overview")
    p_overview.add_argument("manifest")
    p_overview.add_argument("--page", type=int, default=1)
    p_overview.add_argument("--page-size", type=int, default=30)

    p_search = sub.add_parser("search")
    p_search.add_argument("manifest")
    # 支持一次传多个 query，把 N 次 LLM 往返压成 1 次。
    p_search.add_argument("query", nargs="+")
    p_search.add_argument("--limit", type=int, default=20)

    p_checklist = sub.add_parser("checklist")
    p_checklist.add_argument("manifest")
    p_checklist.add_argument("--shard", required=True)
    p_checklist.add_argument("--no-hints", action="store_true")
    p_checklist.add_argument("--hint-limit", type=int, default=8)

    p_read = sub.add_parser("read")
    p_read.add_argument("manifest")
    p_read.add_argument("id")
    p_read.add_argument("--mode", choices=["summary", "full"], default="summary")
    p_read.add_argument("--max-chars", type=int, default=2000)

    p_table = sub.add_parser("table")
    p_table.add_argument("manifest")
    p_table.add_argument("table_id")
    p_table.add_argument("--rows", default="1-12")
    p_table.add_argument("--max-chars", type=int, default=4000)

    p_window = sub.add_parser("window")
    p_window.add_argument("manifest")
    p_window.add_argument("evidence_id")
    p_window.add_argument("--before", type=int, default=3)
    p_window.add_argument("--after", type=int, default=3)

    p_submit = sub.add_parser("submit")
    p_submit.add_argument("manifest")
    p_submit.add_argument("target_key")
    p_submit.add_argument("json_value", type=_json_arg)
    p_submit.add_argument("--shard", default="")

    p_status = sub.add_parser("status")
    p_status.add_argument("manifest")

    p_validate = sub.add_parser("validate")
    p_validate.add_argument("manifest")

    p_finalize = sub.add_parser("finalize")
    p_finalize.add_argument("manifest")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_usage()
        return 64
    manifest_path = Path(args.manifest).expanduser().resolve()
    manifest = load_manifest(manifest_path)
    command = args.command
    if command == "prepare":
        return print_json(prepare(manifest_path, manifest))
    if command == "overview":
        return print_json(navigator_cli.overview(manifest_path, manifest, page=args.page, page_size=args.page_size))
    if command == "search":
        queries = list(args.query)
        if len(queries) == 1:
            return print_json(navigator_cli.search(manifest_path, manifest, queries[0], limit=args.limit))
        return print_json(navigator_cli.search_many(manifest_path, manifest, queries, limit=args.limit))
    if command == "checklist":
        return print_json(
            navigator_cli.shard_checklist(
                manifest_path,
                manifest,
                args.shard,
                with_hints=not args.no_hints,
                hint_limit=args.hint_limit,
            )
        )
    if command == "read":
        return print_json(navigator_cli.read(manifest_path, manifest, args.id, mode=args.mode, max_chars=args.max_chars))
    if command == "table":
        return print_json(navigator_cli.table(manifest_path, manifest, args.table_id, rows_range=args.rows, max_chars=args.max_chars))
    if command == "window":
        return print_json(navigator_cli.window(manifest_path, manifest, args.evidence_id, before=args.before, after=args.after))
    if command == "submit":
        return print_json(
            submit(manifest_path, manifest, args.target_key, args.json_value, shard=args.shard)
        )
    if command == "status":
        return print_json(status(manifest_path, manifest))
    if command == "validate":
        return print_json(validate(manifest_path, manifest))
    if command == "finalize":
        result = finalize(manifest_path, manifest)
        return print_json(summary(result, structured_result_path(manifest_path, manifest)))
    parser.print_usage()
    return 64
