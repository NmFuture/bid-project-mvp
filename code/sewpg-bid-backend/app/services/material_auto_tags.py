"""技术标素材库「自动打标签」派生规则。

不依赖 Excel 清单：标签完全由文件所在目录路径推导（机型 / 类别 / 子类），
与业主给的机型标签示例（todo-example-机型标签-EW6.7-202.xlsx，20260728）
产出的「属性1/2/3」保持一致。

路径约定：``技术标/{档位}/{机型}/{类别}/[四级]/[五级]``，规则：

- 标签1 = 机型（路径第 3 段，如 ``EW6.7-202``）。以目录为准而不是文件名：
  示例中 ``EW6.7-220-125-...`` 文件放在 ``EW6.7-202`` 目录下，机型标签
  仍是 ``EW6.7-202``。
- 标签2 = 类别（路径第 4 段，如 ``部件``/``认证证书``/``专题``，原文）。
- 标签3：
  - 有五级目录 → 五级目录名原文（如 ``变流器``/``智能传感系统``）；
  - 有四级目录 → 四级目录名，先查 ``_TOPIC_TAG_MAP`` 缩短映射，未命中用原文；
  - 文件直接挂在 ``部件`` 类别下 → 文件名去扩展名、去括号备注
    （如 ``动力电缆（常规方案）.pdf`` → ``动力电缆``）；
  - 其他情况无标签3。
- 文件不在机型目录下（路径不足 3 段）→ 不打标签，返回空列表。

解析与匹配是确定性纯函数，便于单测。
"""

from __future__ import annotations

import re
from typing import Any

from app.services.bid_type import TECHNICAL_BID_TYPE
from app.services.material_tag_import import _file_stem, _fold
from app.services.material_tags import normalize_material_tags

# 四级专题目录名 → 标签3 的缩短映射。
# 来源：业主机型标签示例 Excel（todo-example-机型标签-EW6.7-202.xlsx，20260728），
# 属业主固定模板的结构特征（固定专题名），可按模板更新扩充。
_TOPIC_TAG_MAP = {
    "设备安装与调试方案": "设备安装与调试",
    "数字化智慧风场专题": "智慧风场",
    "项目风机环境适应性专题": "适应性",
}

# 文件直接挂在该类别目录下时，标签3 取「文件名去括号备注」。
# 来源：同上示例 Excel 中「部件」类别的属性3 规律。
_FILENAME_TAG_CATEGORY = "部件"

# 括号备注（全/半角）整段剥掉：动力电缆（常规方案）→ 动力电缆
_PAREN_REMARK_RE = re.compile(r"\s*\([^()]*\)")


def _split_folder_parts(folder_path: str) -> list[str]:
    """把 folderPath 切成段，并去掉开头的「技术标」根，返回相对段。"""

    parts = [seg.strip() for seg in str(folder_path or "").split("/") if seg.strip()]
    if parts and _fold(parts[0]).casefold() == _fold(TECHNICAL_BID_TYPE).casefold():
        parts = parts[1:]
    return parts


# 折叠键版本，模块级只构建一次
_TOPIC_TAG_MAP_FOLDED = {_fold(key).casefold(): value for key, value in _TOPIC_TAG_MAP.items()}


def _topic_tag(level4: str) -> str:
    """四级目录名 → 标签3：先查映射表（按全角折叠后的键），未命中用原文。"""

    return _TOPIC_TAG_MAP_FOLDED.get(_fold(level4).casefold(), level4)


def _filename_tag(file_name: str) -> str:
    """文件名 → 标签3：去真实扩展名 + 全角折半角 + 去括号备注。"""

    stem = _fold(_file_stem(file_name))
    cleaned = _PAREN_REMARK_RE.sub("", stem).strip()
    return cleaned


def derive_auto_tags(folder_path: str, file_name: str) -> list[str]:
    """按目录路径 + 文件名推导标签，返回规整后的标签列表（可为空）。"""

    parts = _split_folder_parts(folder_path)
    # parts: [档位, 机型, 类别, 四级, 五级, ...]
    if len(parts) < 2:
        return []
    tags: list[str] = [parts[1]]  # 标签1：机型
    if len(parts) < 3:
        return normalize_material_tags(tags)
    category = parts[2]
    tags.append(category)  # 标签2：类别

    tag3 = ""
    if len(parts) >= 5:
        tag3 = parts[4]  # 五级目录名原文
    elif len(parts) == 4:
        tag3 = _topic_tag(parts[3])
    elif _fold(category).casefold() == _fold(_FILENAME_TAG_CATEGORY).casefold():
        tag3 = _filename_tag(file_name)
    if tag3:
        tags.append(tag3)
    return normalize_material_tags(tags)


def build_auto_tag_items(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """对子树文件列表逐个推导标签，过滤推导为空的，产出打标条目。"""

    items: list[dict[str, Any]] = []
    for item in files:
        file_id = str(item.get("id") or "")
        if not file_id:
            continue
        tags = derive_auto_tags(str(item.get("folderPath") or ""), str(item.get("name") or ""))
        if not tags:
            continue
        items.append(
            {
                "fileId": file_id,
                "name": str(item.get("name") or ""),
                "folderPath": str(item.get("folderPath") or ""),
                "existingTags": normalize_material_tags(item.get("tags")),
                "tags": tags,
            }
        )
    return items
