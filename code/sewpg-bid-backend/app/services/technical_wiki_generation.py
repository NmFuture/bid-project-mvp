"""技术标 Wiki 生成（纯「脚本 + skill」确定性链路，独立于商务标）。

技术标的 Wiki 目录树严格等于素材库三级目录结构（tier → folder → file），
无需 LLM 语义精修，也不依赖商务标那套 inventory / 多级回退逻辑。流程：

    取最新三级目录 JSON 索引
      → 写成 manifest
      → subprocess 跑 bid-tech-wiki-material-builder/scripts/run_from_manifest.py
      → 把确定性 blueprint 导入技术标素材库

供「重建 Wiki」主流程与后台预览任务（technical_wiki_preview）复用。
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

from app.core.config import BASE_DIR, settings
from app.services.bid_type import TECHNICAL_BID_TYPE
from app.services.technical_material_store import technical_material_store
from app.services.technical_material_index import (
    load_technical_material_index,
    rebuild_technical_material_index,
)
from app.services.wiki_blueprint_common import (
    load_wiki_blueprint_result,
    normalize_blueprint,
    run_local_wiki_skill,
)

TECHNICAL_WIKI_SKILL_NAME = "bid-tech-wiki-material-builder"
TECHNICAL_WIKI_RUNNER = (
    BASE_DIR / "opencode" / "skills" / TECHNICAL_WIKI_SKILL_NAME / "scripts" / "run_from_manifest.py"
)
TECHNICAL_WIKI_ROOT_TITLE = f"{TECHNICAL_BID_TYPE}Wiki（自动生成）"


def write_technical_index_manifest(index_payload: dict[str, Any]) -> Path:
    """把三级目录 JSON 索引写到共享构建目录，供 wikibuild 脚本镜像成 Wiki。"""
    shared_root = settings.parsed_dir / "_wiki_build"
    shared_root.mkdir(parents=True, exist_ok=True)
    target_dir = Path(tempfile.mkdtemp(prefix="bid-tech-wiki-", dir=shared_root))
    manifest_path = target_dir / "technical_material_index.json"
    manifest = {
        **index_payload,
        "rootTitle": TECHNICAL_WIKI_ROOT_TITLE,
        "workDir": str(target_dir),
        "outputFile": str(target_dir / "wiki_blueprint.json"),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


async def mirror_technical_index_to_wiki(
    index_payload: dict[str, Any],
    *,
    mode: str,
) -> dict[str, Any]:
    """把技术标三级目录索引 payload 确定性镜像成 Wiki blueprint 并导入（不走 LLM）。

    供「重建 Wiki」主流程与后台预览任务复用：后台任务补齐预览后用 mode="replace"
    重镜像一次，让带 AI 预览的文件卡片落到 Wiki 树上。
    """
    if not isinstance(index_payload, dict):
        index_payload = {}
    index_payload.setdefault("bidType", TECHNICAL_BID_TYPE)

    manifest_path = write_technical_index_manifest(index_payload)
    skill_result = await asyncio.to_thread(
        run_local_wiki_skill,
        manifest_path,
        skill_name=TECHNICAL_WIKI_SKILL_NAME,
        runner=TECHNICAL_WIKI_RUNNER,
    )
    blueprint = normalize_blueprint(load_wiki_blueprint_result(skill_result))
    blueprint["rootTitle"] = TECHNICAL_WIKI_ROOT_TITLE
    opencode_output = skill_result.get("opencodeOutput") or {}

    imported = await technical_material_store.import_generated_wiki_blueprint(
        root_title=blueprint["rootTitle"],
        root_markdown_content=blueprint.get("rootMarkdownContent") or "",
        nodes=blueprint["nodes"],
        mode=mode,
    )
    stats = index_payload.get("stats") if isinstance(index_payload.get("stats"), dict) else {}
    imported["generation"] = {
        "summary": blueprint["summary"],
        "bidType": TECHNICAL_BID_TYPE,
        "skill": TECHNICAL_WIKI_SKILL_NAME,
        "generator": "technical_index_mirror",
        "fallbackUsed": False,
        "materialIndex": {
            "tierCount": stats.get("tierCount"),
            "thirdLevelFolderCount": stats.get("thirdLevelFolderCount"),
            "fileCount": stats.get("fileCount"),
            "generatedAt": index_payload.get("generatedAt"),
        },
        "opencodeOutput": opencode_output,
    }
    return imported


async def generate_technical_wiki(
    *,
    mode: str = "create",
    reference_path: str = "",
    fallback_to_deterministic: bool = False,
) -> dict[str, Any]:
    """技术标 Wiki：确定性镜像三级目录 JSON 索引（tier→folder→file），不走 LLM。

    技术标的目录树就该严格等于素材库三级结构，无需语义精修；因此独立于商务标
    的 LLM/确定性回退链路，直接用 wikibuild 脚本把索引镜像成 blueprint 再导入。
    `reference_path` / `fallback_to_deterministic` 仅为兼容 route 透传，技术标忽略。
    """
    _ = (reference_path, fallback_to_deterministic)
    # 先实时重建索引拿最新结构；失败/为空时回退到已落盘的快照。
    # preview_mode="cached"：秒级注入已生成的 AI 预览，不调 LLM —— 重建 Wiki 立即返回。
    # 缺失预览的 docx 先降级为纯目录卡片，由后台 technical_wiki_preview 任务异步补齐。
    index_payload = await rebuild_technical_material_index(preview_mode="cached")
    if not isinstance(index_payload, dict) or not index_payload.get("tiers"):
        index_payload = load_technical_material_index()
    return await mirror_technical_index_to_wiki(index_payload, mode=mode)
