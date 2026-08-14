from __future__ import annotations

"""技术标事实表填表规则的全局（系统默认）清单管理。

设置页与素材库「规则」tab 共用同一份系统默认规则：
- 解析后的 specs 原子写 fact_specs_override_path 并清缓存，运行链路立即生效；
- 原始 xlsx 与元数据 sidecar 存档到 documents_dir/_config/，供下载与来源展示；
- 每次上传固化一个不可变版本（fact_spec_versions/_global/），保持审计链。
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.technical_fact_field_specs import (
    clear_specs_cache,
    load_specs,
    normalize_spec_source_kind,
)
from app.services.technical_fact_spec_versions import fact_specs_ref, save_fact_spec_version

# 全局清单的版本挂在固定 projectId「_global」下，与项目级版本同目录结构
GLOBAL_FACT_SPECS_PROJECT_ID = "_global"
GLOBAL_FACT_SPECS_ARCHIVE_NAME = "technical_fact_specs.xlsx"
GLOBAL_FACT_SPECS_META_NAME = "technical_fact_specs.meta.json"


def global_fact_specs_archive_path() -> Path:
    return Path(settings.documents_dir) / "_config" / GLOBAL_FACT_SPECS_ARCHIVE_NAME


def global_fact_specs_meta_path() -> Path:
    return Path(settings.documents_dir) / "_config" / GLOBAL_FACT_SPECS_META_NAME


def _atomic_write_text(path: Path, text: str) -> None:
    # 先写临时文件再原子替换，避免半截文件被运行时读到
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, path)


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_bytes(content)
    os.replace(tmp_path, path)


def apply_fact_specs_override(specs: list[dict[str, Any]]) -> dict[str, Any]:
    """原子写系统默认清单 override 并清缓存，返回统计摘要（设置页/规则 tab 共用）。"""
    override_path = Path(settings.fact_specs_override_path)
    _atomic_write_text(override_path, json.dumps(specs, ensure_ascii=False, indent=2) + "\n")
    clear_specs_cache()
    return {
        "specTotal": len(specs),
        "fillableTotal": sum(1 for spec in specs if spec.get("valueRequired")),
        "template": sum(1 for spec in specs if spec.get("sourceKind") == "template"),
        "override": True,
    }


def load_global_fact_specs_meta() -> dict[str, Any] | None:
    """读全局清单元数据 sidecar；不存在或损坏返回 None。"""
    try:
        payload = json.loads(global_fact_specs_meta_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def resolve_fact_specs() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """当前生效的全局清单，返回 (specs, ref)；尚未上传清单时 specs 为空列表。

    清单与项目无关：所有项目拿同一份 specs，各自去自己的招标文件与素材里找值。
    ref 固化进事实表与任务产物，事后可审计正式标书用的是哪一版清单。
    """
    specs = [normalize_spec_source_kind(spec) for spec in load_specs()]
    return specs, fact_specs_ref(load_global_fact_specs_meta() or {}, spec_total=len(specs))


def _global_previous_version() -> int:
    """_global 目录下已有版本文件数即当前版本号（版本号按目录自增）。"""
    version_dir = Path(settings.fact_specs_versions_dir) / GLOBAL_FACT_SPECS_PROJECT_ID
    if not version_dir.is_dir():
        return 0
    return sum(1 for path in version_dir.glob("v*-fsr-*.json") if path.is_file())


def save_global_fact_specs(
    specs: list[dict[str, Any]],
    *,
    file_name: str,
    uploaded_by: str,
    content: bytes,
) -> dict[str, Any]:
    """全局清单上传落盘：override 生效 + 原表存档 + 元数据 sidecar + _global 不可变版本。"""
    summary = apply_fact_specs_override(specs)
    binding = save_fact_spec_version(
        GLOBAL_FACT_SPECS_PROJECT_ID,
        specs,
        file_name=file_name,
        uploaded_by=uploaded_by,
        content=content,
        previous_version=_global_previous_version(),
    )
    _atomic_write_bytes(global_fact_specs_archive_path(), content)
    meta = {
        # ruleId/version 随 sidecar 一起存：事实表靠它判断清单是否换版（换版要从头重建）
        "ruleId": binding["ruleId"],
        "version": binding["version"],
        "fileName": file_name,
        "uploadedAt": binding["uploadedAt"],
        "uploadedBy": uploaded_by,
        "sha256": hashlib.sha256(content).hexdigest(),
        "specTotal": len(specs),
    }
    _atomic_write_text(
        global_fact_specs_meta_path(), json.dumps(meta, ensure_ascii=False, indent=2) + "\n"
    )
    return {**summary, "fileName": file_name, "uploadedAt": binding["uploadedAt"]}
