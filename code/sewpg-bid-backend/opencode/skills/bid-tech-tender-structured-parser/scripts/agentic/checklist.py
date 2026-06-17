from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any


CHECKLIST_VERSION = "excel-technical-2026-06-16"

DISPLAY_GROUPS = (
    "设备选型适配",
    "供货范围界定",
    "设计与制造标准",
    "施工与验收规范",
    "技术资料交付",
    "全生命周期质保",
    "涉网性能合规",
    "CMS / 一次调频 / 国产化 / 二次安防等",
)

DISPLAY_GROUP_ALIASES = {
    "设备选型适配": "设备选型适配",
    "供货范围界定": "供货范围界定",
    "设计与制造标准": "设计与制造标准",
    "施工与验收规范": "施工与验收规范",
    "技术资料交付": "技术资料交付",
    "投标技术资料要求": "技术资料交付",
    "资格与资质要求": "技术资料交付",
    "全生命周期质保": "全生命周期质保",
    "涉网性能合规": "涉网性能合规",
    "中央监控与远程监测系统": "CMS / 一次调频 / 国产化 / 二次安防等",
    "CMS振动监测系统": "CMS / 一次调频 / 国产化 / 二次安防等",
    "一次调频与惯量响应系统": "CMS / 一次调频 / 国产化 / 二次安防等",
    "国产自主可控软硬件": "CMS / 一次调频 / 国产化 / 二次安防等",
    "二次安防系统": "CMS / 一次调频 / 国产化 / 二次安防等",
}


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\u3000", " ")).strip()


def display_group(primary_category: str) -> str:
    return DISPLAY_GROUP_ALIASES.get(clean(primary_category), clean(primary_category) or "其他")


def _skill_path() -> Path:
    return Path(__file__).resolve().parents[2] / "SKILL.md"


def _parse_table_line(line: str) -> dict[str, Any] | None:
    if not line.startswith("|"):
        return None
    cells = [clean(cell) for cell in line.strip().strip("|").split("|")]
    if len(cells) < 4 or not cells[0].isdigit():
        return None
    row_no = int(cells[0])
    primary = cells[1]
    secondary = cells[2]
    content = cells[3]
    if not primary or not secondary or not content:
        return None
    return {
        "rowNo": row_no,
        "displayGroup": display_group(primary),
        "primaryCategory": primary,
        "secondaryCategory": secondary,
        "specificContent": content,
    }


@lru_cache(maxsize=1)
def load_checklist() -> list[dict[str, Any]]:
    content = _skill_path().read_text(encoding="utf-8")
    rows = [_parse_table_line(line) for line in content.splitlines()]
    checklist = [row for row in rows if row is not None]
    if len(checklist) != 58:
        raise RuntimeError(f"technical checklist must contain 58 rows, got {len(checklist)}")
    return checklist


def checklist_by_row_no() -> dict[int, dict[str, Any]]:
    return {int(item["rowNo"]): item for item in load_checklist()}
