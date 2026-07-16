from __future__ import annotations

import argparse
import json
from pathlib import Path

from docling.datamodel.pipeline_options import LayoutOptions
from docling.models.stages.layout.layout_model import LayoutModel
from docling.models.stages.table_structure.table_structure_model import TableStructureModel


def download_docling_models(target_dir: Path, *, force: bool = False, progress: bool = True) -> dict[str, str]:
    target_dir.mkdir(parents=True, exist_ok=True)

    layout_model_config = LayoutOptions().model_spec
    layout_dir = target_dir / layout_model_config.model_repo_folder
    table_dir = target_dir / TableStructureModel._model_repo_folder

    layout_path = LayoutModel.download_models(
        local_dir=layout_dir,
        force=force,
        progress=progress,
        layout_model_config=layout_model_config,
    )
    table_path = TableStructureModel.download_models(
        local_dir=table_dir,
        force=force,
        progress=progress,
    )

    return {
        "targetDir": str(target_dir),
        "layoutPath": str(layout_path),
        "tablePath": str(table_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Download Docling layout and table models for offline runtime use.")
    parser.add_argument("target_dir", type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    result = download_docling_models(args.target_dir, force=args.force, progress=not args.quiet)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
