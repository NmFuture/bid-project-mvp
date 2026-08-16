"""素材塔型（钢塔/混塔）判型。

判型依据是业主技术标素材库的固定命名结构特征（2026-08 对素材库全量核验）：

- 文件名后缀 ``-钢塔`` / ``-混塔``（保供能力系列）；
- 文件名括号 ``（钢塔）`` / ``（混塔）``（智能传感系统等系列）；
- 目录段 ``投标项目塔筒专题-钢塔``（整目录为钢塔族）；
- 目录段 ``混塔``（认证证书/部件认证/混塔/）；
- 固定混塔专用文件 ``混塔解决方案专题``。

刻意不做裸子串匹配：「钢塔筒招标项目场址设计安全性」这类附表文件混塔项目
也要用（附表 G.3 备注：混塔只填钢段塔筒部分），裸匹配「钢塔」会把它误判成
钢塔专用。判不出的素材视为塔型无关，任何项目都保留。

项目侧基础形式口径（建项目弹窗 STATIC_FOUNDATION_TYPE_OPTIONS）：钢塔/混塔是
陆上塔型；单桩/导管架/多桩承台是海上基础形式，素材库没有对应素材。
"""

from __future__ import annotations

import re
from typing import Any

STEEL_TOWER = "钢塔"
MIXED_TOWER = "混塔"
TOWER_FAMILIES = {STEEL_TOWER, MIXED_TOWER}

# 海上基础形式：当前素材库是陆上产品线，这些选项下没有任何塔型素材可用。
OFFSHORE_FOUNDATION_TYPES = {"单桩", "导管架", "多桩承台"}

_TOWER_SUFFIX_RE = re.compile(r"[-－—_]\s*(钢塔|混塔)\s*$")
_TOWER_PAREN_RE = re.compile(r"[（(]\s*(钢塔|混塔)\s*[）)]")
_MIXED_ONLY_STEMS = {"混塔解决方案专题"}
_STEEL_DIR_MARKER = "塔筒专题-钢塔"


def material_tower_family(name: Any, folder_path: Any = "") -> str:
    """素材 → 塔型族：``钢塔`` / ``混塔`` / ``""``（塔型无关）。"""
    stem = str(name or "").strip()
    if "." in stem:
        stem = stem.rsplit(".", 1)[0].strip()
    segments = [
        seg.strip()
        for seg in str(folder_path or "").replace("\\", "/").split("/")
        if seg.strip()
    ]
    for segment in segments:
        if segment == MIXED_TOWER:
            return MIXED_TOWER
        if _STEEL_DIR_MARKER in segment:
            return STEEL_TOWER
    if stem in _MIXED_ONLY_STEMS:
        return MIXED_TOWER
    match = _TOWER_PAREN_RE.search(stem) or _TOWER_SUFFIX_RE.search(stem)
    return match.group(1) if match else ""
