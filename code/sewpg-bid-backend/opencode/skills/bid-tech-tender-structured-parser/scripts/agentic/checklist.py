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


# \u6280\u672f\u89e3\u8bfb\u5206\u7247\uff1a\u5e76\u53d1\u89e3\u6790\u65f6\u6bcf\u4e2a\u5206\u7247\u7531\u4e00\u4e2a\u72ec\u7acb opencode \u4f1a\u8bdd\u8d1f\u8d23\u3002
# \u5206\u7247\u6309\u300c\u8bc1\u636e\u6765\u6e90\u91cd\u53e0 + \u884c\u6570\u5747\u8861\u300d\u5212\u5206\uff0c\u4e0e DISPLAY_GROUPS \u65e0\u5173\u2014\u2014\u540e\u8005\u53ea\u662f\u524d\u7aef\u5c55\u793a\u805a\u5408\u3002
# \u4f8b\u5982 IEC \u5b89\u5168\u7b49\u7ea7\u3001SSDA\u3001\u8f7d\u8377\u62a5\u544a\u7684\u8bc1\u636e\u540c\u65f6\u652f\u6491\u7b2c 9/16/29/38 \u884c\uff0c\u5fc5\u987b\u843d\u5728\u540c\u4e00\u5206\u7247\uff0c
# \u5426\u5219\u6bcf\u4e2a\u5206\u7247\u90fd\u4f1a\u91cd\u590d\u68c0\u7d22\u540c\u4e00\u6279\u7ae0\u8282\uff0c\u5e76\u53ef\u80fd\u7ed9\u51fa\u4e92\u76f8\u77db\u76fe\u7684\u7ed3\u8bba\u3002
# rowNos \u5fc5\u987b\u5b8c\u6574\u8986\u76d6 checklist.md \u4e14\u4e92\u4e0d\u91cd\u53e0\uff0cload_shards() \u4f1a\u5f3a\u6821\u9a8c\u3002
SHARDS: tuple[dict[str, Any], ...] = (
    {
        "key": "selection_supply",
        "label": "\u9009\u578b\u4e0e\u4f9b\u8d27",
        "rowNos": (3, 4, 5, 6, 7, 8, 17, 42, 43),
    },
    {
        "key": "design_certification",
        "label": "\u8bbe\u8ba1\u5236\u9020\u4e0e\u8ba4\u8bc1",
        "rowNos": (9, 10, 11, 12, 13, 14, 16, 29, 38),
    },
    {
        "key": "components_environment",
        "label": "\u6838\u5fc3\u90e8\u4ef6\u4e0e\u73af\u5883",
        "rowNos": (23, 24, 25, 26, 27, 28, 39, 40, 41),
    },
    {
        "key": "warranty_performance",
        "label": "\u8d28\u4fdd\u4e0e\u8003\u6838",
        "rowNos": (18, 19, 20, 30, 31, 32, 33, 34, 35, 36, 37),
    },
    {
        "key": "grid_documents",
        "label": "\u6d89\u7f51\u4e0e\u6280\u672f\u8d44\u6599",
        "rowNos": (15, 21, 22, 44, 45, 52, 53, 54),
    },
    {
        "key": "monitoring_security",
        "label": "\u76d1\u63a7\u4e0e\u5b89\u9632\u56fd\u4ea7\u5316",
        "rowNos": (46, 47, 48, 49, 50, 51, 55, 56, 57, 58, 59, 60),
    },
)


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\u3000", " ")).strip()


def display_group(primary_category: str) -> str:
    return DISPLAY_GROUP_ALIASES.get(clean(primary_category), clean(primary_category) or "其他")


def _checklist_path() -> Path:
    # 清单数据文件：references/checklist.md（勿在 SKILL.md 内维护清单表）
    return Path(__file__).resolve().parents[2] / "references" / "checklist.md"


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
    content = _checklist_path().read_text(encoding="utf-8")
    rows = [_parse_table_line(line) for line in content.splitlines()]
    checklist = [row for row in rows if row is not None]
    if len(checklist) != 58:
        raise RuntimeError(f"technical checklist must contain 58 rows, got {len(checklist)}")
    return checklist


def checklist_by_row_no() -> dict[int, dict[str, Any]]:
    return {int(item["rowNo"]): item for item in load_checklist()}


@lru_cache(maxsize=1)
def load_shards() -> tuple[dict[str, Any], ...]:
    """返回分片配置，并强校验分片对清单行的覆盖是完整且无重叠的。

    清单改动（增删行）而未同步分片配置时，这里直接 RuntimeError 中断，
    避免整片清单行被静默漏解析。
    """
    checklist_rows = {int(item["rowNo"]) for item in load_checklist()}
    keys: list[str] = []
    seen: dict[int, str] = {}
    for shard in SHARDS:
        key = clean(shard.get("key"))
        if not key:
            raise RuntimeError("checklist shard must define a non-empty key")
        if key in keys:
            raise RuntimeError(f"duplicated checklist shard key: {key}")
        keys.append(key)
        row_nos = tuple(int(row_no) for row_no in shard.get("rowNos") or ())
        if not row_nos:
            raise RuntimeError(f"checklist shard has no rowNos: {key}")
        for row_no in row_nos:
            if row_no in seen:
                raise RuntimeError(
                    f"checklist row {row_no} is claimed by both shard {seen[row_no]} and {key}"
                )
            seen[row_no] = key
    covered = set(seen)
    if covered != checklist_rows:
        missing = sorted(checklist_rows - covered)
        unknown = sorted(covered - checklist_rows)
        raise RuntimeError(
            f"checklist shards must cover every checklist row exactly once; missing={missing}, unknown={unknown}"
        )
    return tuple(
        {
            "key": clean(shard["key"]),
            "label": clean(shard.get("label")) or clean(shard["key"]),
            "rowNos": tuple(int(row_no) for row_no in shard["rowNos"]),
        }
        for shard in SHARDS
    )


def shard_keys() -> tuple[str, ...]:
    return tuple(str(shard["key"]) for shard in load_shards())


def shard_by_key(shard_key: str) -> dict[str, Any]:
    key = clean(shard_key)
    for shard in load_shards():
        if shard["key"] == key:
            return shard
    raise RuntimeError(f"unknown checklist shard: {shard_key or '(empty)'}; expected one of {', '.join(shard_keys())}")


def shard_of_row(row_no: int) -> str:
    for shard in load_shards():
        if int(row_no) in shard["rowNos"]:
            return str(shard["key"])
    raise RuntimeError(f"checklist row is not assigned to any shard: {row_no}")


def checklist_for_shard(shard_key: str) -> list[dict[str, Any]]:
    shard = shard_by_key(shard_key)
    by_row_no = checklist_by_row_no()
    return [by_row_no[row_no] for row_no in shard["rowNos"]]
