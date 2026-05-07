#!/usr/bin/env python3
"""Build the business-bid material Wiki blueprint from a backend manifest."""

from __future__ import annotations

import json
import sys
from pathlib import Path


CURRENT = Path(__file__).resolve()
SCRIPT_ROOT = CURRENT.parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from business_wiki_blueprint import build_business_wiki_blueprint, load_json  # noqa: E402


def run_manifest(manifest_path: Path) -> dict[str, object]:
    manifest = load_json(manifest_path)
    work_dir = Path(str(manifest.get("workDir") or manifest_path.parent)).expanduser()
    work_dir.mkdir(parents=True, exist_ok=True)
    output_file = Path(str(manifest.get("outputFile") or work_dir / "wiki_blueprint.json")).expanduser()
    output_file.parent.mkdir(parents=True, exist_ok=True)

    inventory = manifest.get("materialInventory") if isinstance(manifest.get("materialInventory"), dict) else {}
    root_title = str(manifest.get("rootTitle") or "商务标Wiki（自动生成）")
    blueprint = build_business_wiki_blueprint(inventory, root_title=root_title)
    output_file.write_text(json.dumps(blueprint, ensure_ascii=False, indent=2), encoding="utf-8")

    nodes = blueprint.get("nodes") or []
    return {
        "schema_version": "bid-wiki-blueprint-v1",
        "skill": "bid-business-wiki-material-builder",
        "outputFile": str(output_file),
        "summary": blueprint.get("summary") or "",
        "rootTitle": blueprint.get("rootTitle") or root_title,
        "materialCount": len(inventory.get("items") or []),
        "nodeTitles": [str(node.get("title") or "") for node in nodes if isinstance(node, dict)],
    }


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: run_from_manifest.py <manifest>")
    response = run_manifest(Path(sys.argv[1]))
    print(json.dumps(response, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
