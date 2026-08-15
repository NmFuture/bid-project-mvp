from __future__ import annotations

"""技术标填表规则（事实表字段清单）版本化。

清单全局共用、与项目无关：规则页上传一份，所有项目按同一张表去各自的招标文件与
素材里找自己的值。这里只管版本留痕：

- 每次上传生成一个不可变版本文件（数据卷 fact_spec_versions/_global/{ruleId}.json），
  记录 ruleId / version / 上传人 / 上传时间 / 文件 sha256 / specs 快照；
- 事实表构建 / AI 维护任务启动时把当前生效版本固化进产物（factSpecsRef），可事后审计。

历史上还有一层项目级绑定（gap_state["factSpecs"]，R06-B04-02 为隔离项目间污染而加），
清单改成全局唯一后已移除：项目不再各自持有清单快照。
"""

import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.bid_runtime_state import now_iso

# factSpecsRef.source：清单只有全局一层，保留字段名供已固化的产物与前端兼容读取
FACT_SPECS_SOURCE_GLOBAL = "global"


def _safe_project_id(project_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(project_id or "").strip()) or "project"


def fact_specs_ref(meta: dict[str, Any], *, spec_total: int | None = None) -> dict[str, Any]:
    """从清单元数据提取可审计字段（不含 specs 本体）。"""
    return {
        "source": FACT_SPECS_SOURCE_GLOBAL,
        "ruleId": str(meta.get("ruleId") or ""),
        "version": int(meta.get("version") or 0),
        "fileName": str(meta.get("fileName") or ""),
        "uploadedAt": str(meta.get("uploadedAt") or ""),
        "uploadedBy": str(meta.get("uploadedBy") or ""),
        "sha256": str(meta.get("sha256") or ""),
        "specTotal": len(meta.get("specs") or []) if spec_total is None else int(spec_total),
    }


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
    uploaded_at = now_iso()
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
