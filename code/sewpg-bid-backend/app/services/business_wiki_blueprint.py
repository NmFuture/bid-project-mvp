from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


CURRENT = Path(__file__).resolve()
SOURCE = (
    CURRENT.parents[2]
    / "opencode"
    / "skills"
    / "bid-business-wiki-material-builder"
    / "scripts"
    / "business_wiki_blueprint.py"
)

if not SOURCE.exists():
    raise RuntimeError(f"商务标 Wiki 蓝图脚本不存在: {SOURCE}")

_SPEC = importlib.util.spec_from_file_location("business_wiki_blueprint_skill", SOURCE)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"无法加载商务标 Wiki 蓝图脚本: {SOURCE}")

_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("business_wiki_blueprint_skill", _MODULE)
_SPEC.loader.exec_module(_MODULE)

load_json = _MODULE.load_json
build_business_wiki_blueprint = _MODULE.build_business_wiki_blueprint
