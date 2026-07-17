"""技术标 Wiki 生成（纯「脚本 + skill」确定性链路，独立于商务标）。

技术标的 Wiki 目录树严格等于素材库三级目录结构（tier → folder → file），
无需 LLM 语义精修，也不依赖商务标那套 inventory / 多级回退逻辑。流程：

    读取唯一三级目录 JSON 索引
      → 写成 manifest
      → subprocess 跑 bid-tech-wiki-material-builder/scripts/run_from_manifest.py
      → 把确定性 blueprint 导入技术标素材库

供「刷新 Wiki」与「重建 Wiki」复用。
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
from app.services.technical_material_index import load_technical_material_index
from app.services.bid_runtime_state import write_json_file_atomic
from app.services.technical_material_index import TECHNICAL_MATERIAL_INDEX_PATH
from app.services.technical_wiki_preview_generation import enrich_technical_wiki_previews
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
    preview_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把技术标三级目录索引 payload 确定性镜像成 Wiki blueprint 并导入（不走 LLM）。

    `mode="refresh"` 增量同步自动生成根树，`mode="replace"` 全量替换自动生成根树。
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
        "summary": _summary_with_preview(blueprint["summary"], preview_stats),
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
        "preview": preview_stats or {"enabled": False},
        "opencodeOutput": opencode_output,
    }
    return imported


def _summary_with_preview(summary: str, preview_stats: dict[str, Any] | None) -> str:
    if not preview_stats or not preview_stats.get("enabled"):
        return summary
    completed = int(preview_stats.get("completed") or 0)
    cached = int(preview_stats.get("cached") or 0)
    fallback = int(preview_stats.get("fallback") or 0)
    retryable = int(preview_stats.get("retryable") or 0)
    local_only = max(0, fallback - retryable)
    failed = int(preview_stats.get("failed") or 0)
    return (
        f"{summary} 内容预览：AI 成功 {completed} 个（缓存 {cached} 个），"
        f"待重试 {retryable} 个，本地 TLDR {local_only} 个，失败 {failed} 个。"
    )


async def generate_technical_wiki(
    *,
    mode: str = "create",
    reference_path: str = "",
    fallback_to_deterministic: bool = False,
) -> dict[str, Any]:
    """技术标 Wiki：确定性镜像三级目录 JSON 索引（tier→folder→file），不走 LLM。

    技术标的目录树严格以已落盘的 `technical_material_index.json` 为唯一凭证，
    不在 Wiki 生成入口重新从 DB 拼结构。刷新/重建只决定导入策略，不改变索引来源。
    `reference_path` / `fallback_to_deterministic` 仅为兼容 route 透传，技术标忽略。
    """
    _ = (reference_path, fallback_to_deterministic)
    index_payload = load_technical_material_index()
    if not isinstance(index_payload, dict) or not isinstance(index_payload.get("tiers"), list):
        raise RuntimeError("技术标 Wiki 缺少有效 technical_material_index.json，请先刷新原始素材 JSON 索引。")
    preview_stats = await enrich_technical_wiki_previews(index_payload)
    write_json_file_atomic(TECHNICAL_MATERIAL_INDEX_PATH, index_payload)
    return await mirror_technical_index_to_wiki(index_payload, mode=mode, preview_stats=preview_stats)
