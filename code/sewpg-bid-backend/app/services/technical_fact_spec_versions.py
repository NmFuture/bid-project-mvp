from __future__ import annotations

"""技术标填表规则（事实表字段清单）版本化与项目绑定。

背景（R06-B04-02）：历史上规则只有系统唯一一份公共清单，项目间相互污染、
无法审计正式标书用了哪版规则。现在：

- 每次项目上传生成一个不可变版本文件（数据卷 fact_spec_versions/{projectId}/{ruleId}.json），
  记录 ruleId / projectId / version / 上传人 / 上传时间 / 文件 sha256 / specs 快照；
- 项目绑定写在项目 gap_state["factSpecs"]（随项目持久化，重启不丢），内含 specs 快照，
  运行链路只读快照，其他项目上传新版本不影响本项目；
- 项目未绑定规则时按 resolve_project_specs 回落系统默认清单
  （设置页 override 优先于仓库默认，系统默认规则独立管理）；
- 事实表构建 / AI 维护任务启动时把绑定元数据固化进产物（factSpecsRef），可事后审计。
"""

import hashlib
import json
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.technical_fact_field_specs import load_specs, normalize_spec_source_kind

# gap_state["factSpecs"] 的来源标识：项目专属绑定 / 系统默认回落
FACT_SPECS_SOURCE_PROJECT = "project"
FACT_SPECS_SOURCE_DEFAULT = "default"


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_project_id(project_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(project_id or "").strip()) or "project"


def fact_specs_binding(gap_state: dict[str, Any]) -> dict[str, Any]:
    """项目当前的规则绑定（gap_state["factSpecs"]），无绑定返回 {}。"""
    binding = gap_state.get("factSpecs") if isinstance(gap_state.get("factSpecs"), dict) else {}
    return binding if isinstance(binding.get("specs"), list) and binding.get("specs") else {}


def resolve_project_specs(gap_state: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """取项目生效规则：有绑定返回项目快照，否则回落系统默认清单。

    返回 (specs, meta)；meta 含 source（project/default）及绑定元数据，
    可直接固化进任务产物做审计。
    """
    binding = fact_specs_binding(gap_state)
    if binding:
        # 历史绑定快照里「/」被归成 template，按原始 referenceFile 重算，避免重传才生效
        specs = [
            normalize_spec_source_kind(spec) for spec in binding["specs"] if isinstance(spec, dict)
        ]
        return specs, fact_specs_ref(binding, source=FACT_SPECS_SOURCE_PROJECT)
    return list(load_specs()), {"source": FACT_SPECS_SOURCE_DEFAULT}


def fact_specs_ref(binding: dict[str, Any], *, source: str | None = None) -> dict[str, Any]:
    """从绑定提取可审计元数据（不含 specs 本体）。"""
    ref = {
        "source": source or (FACT_SPECS_SOURCE_PROJECT if binding else FACT_SPECS_SOURCE_DEFAULT),
        "ruleId": str(binding.get("ruleId") or ""),
        "version": int(binding.get("version") or 0),
        "fileName": str(binding.get("fileName") or ""),
        "uploadedAt": str(binding.get("uploadedAt") or ""),
        "uploadedBy": str(binding.get("uploadedBy") or ""),
        "sha256": str(binding.get("sha256") or ""),
        "specTotal": len(binding.get("specs") or []),
    }
    return ref


def save_fact_spec_version(
    project_id: str,
    specs: list[dict[str, Any]],
    *,
    file_name: str,
    uploaded_by: str,
    content: bytes,
    previous_version: int = 0,
) -> dict[str, Any]:
    """把一次上传固化为不可变版本文件，返回绑定元数据（含 specs，可直接写 gap_state）。

    版本号按项目自增；ruleId 全局唯一，版本文件原子写入后不改动。
    """
    version = int(previous_version or 0) + 1
    rule_id = f"fsr-{uuid.uuid4().hex[:12]}"
    uploaded_at = _now_iso()
    digest = hashlib.sha256(content).hexdigest()
    record = {
        "ruleId": rule_id,
        "projectId": str(project_id or ""),
        "version": version,
        "fileName": str(file_name or ""),
        "uploadedAt": uploaded_at,
        "uploadedBy": str(uploaded_by or ""),
        "sha256": digest,
        "specTotal": len(specs),
        "specs": specs,
    }
    project_dir = Path(settings.fact_specs_versions_dir) / _safe_project_id(project_id)
    project_dir.mkdir(parents=True, exist_ok=True)
    version_path = project_dir / f"v{version:04d}-{rule_id}.json"
    tmp_path = version_path.with_name(version_path.name + ".tmp")
    tmp_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_path, version_path)
    return {
        "ruleId": rule_id,
        "version": version,
        "fileName": record["fileName"],
        "uploadedAt": uploaded_at,
        "uploadedBy": record["uploadedBy"],
        "sha256": digest,
        "specs": specs,
    }


def load_fact_spec_version(project_id: str, rule_id: str) -> dict[str, Any] | None:
    """按 ruleId 读历史版本文件（审计/追溯用）；不存在或损坏返回 None。"""
    project_dir = Path(settings.fact_specs_versions_dir) / _safe_project_id(project_id)
    if not project_dir.is_dir():
        return None
    for path in project_dir.glob(f"*-{rule_id}.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None
    return None
