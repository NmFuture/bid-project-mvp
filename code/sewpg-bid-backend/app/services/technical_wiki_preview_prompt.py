"""桥接：把 bid-tech-wiki-material-builder skill 的预览 prompt 模块 import 进后端。

照搬 business_wiki_blueprint.py 的 importlib 范式：skill 侧
`scripts/technical_wiki_preview.py` 是纯 stdlib 模块，这里用 spec_from_file_location
加载它并 re-export 常量与函数，供 technical_material_index.py 复用，避免预览的
prompt/schema/解析规则再裸写在后端业务代码里。

命名注意：与已存在的后台任务模块 `technical_wiki_preview.py`（worker 调）区分，
本桥接命名为 `technical_wiki_preview_prompt`。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


CURRENT = Path(__file__).resolve()
SOURCE = (
    CURRENT.parents[2]
    / "opencode"
    / "skills"
    / "bid-tech-wiki-material-builder"
    / "scripts"
    / "technical_wiki_preview.py"
)

if not SOURCE.exists():
    raise RuntimeError(f"技术标 Wiki 预览 prompt 脚本不存在: {SOURCE}")

_SPEC = importlib.util.spec_from_file_location("technical_wiki_preview_skill", SOURCE)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"无法加载技术标 Wiki 预览 prompt 脚本: {SOURCE}")

_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("technical_wiki_preview_skill", _MODULE)
_SPEC.loader.exec_module(_MODULE)

PREVIEW_SCHEMA_VERSION = _MODULE.PREVIEW_SCHEMA_VERSION
PREVIEW_BATCH_SIZE = _MODULE.PREVIEW_BATCH_SIZE
format_heading_tree = _MODULE.format_heading_tree
build_preview_prompt = _MODULE.build_preview_prompt
parse_preview_reply = _MODULE.parse_preview_reply
build_batch_preview_prompt = _MODULE.build_batch_preview_prompt
parse_batch_preview_reply = _MODULE.parse_batch_preview_reply
