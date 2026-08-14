"""素材库文件名归一化共享 helper。

原为「导入标签」Excel 链路的解析/匹配内核；该链路（preview/commit 端点、
``TechnicalMaterialStore.raw_tag_import_*``、fuzzy 桥接与
``bid-tech-tag-importer`` skill）已随 deadcode-04/05 整体移除。
当前只保留 ``material_auto_tags`` 仍在使用的文件名归一化工具：
``_fold``（全角折半角）与 ``_file_stem``（只剥真实扩展名）。
"""

from __future__ import annotations

import re

# 全角→半角的常见标点/数字映射，用于把「语义同名」的差异抹平。
# 例：EW6．25-220（全角点）↔ EW6.25-220，变桨系统（一）↔ 变桨系统(一)。
_FULLWIDTH_MAP = {
    "（": "(", "）": ")", "［": "[", "］": "]", "｛": "{", "｝": "}",
    "．": ".", "，": ",", "、": ",", "：": ":", "；": ";",
    "－": "-", "—": "-", "～": "~", "／": "/", "＼": "\\",
    "　": " ",
}
# 全角 ＡＺ ａｚ ０９ → 半角（U+FF01..U+FF5E 段，统一减 0xFEE0）
for _cp in range(0xFF01, 0xFF5F):
    _FULLWIDTH_MAP.setdefault(chr(_cp), chr(_cp - 0xFEE0))
# 仅当文件名以这些「真实扩展名」结尾时才剥离；避免把机型号里的小数点
# （如 EW6.25-220）误判成扩展名而截断文件名。
_KNOWN_EXTENSIONS = {
    "pdf", "doc", "docx", "xls", "xlsx", "xlsm", "ppt", "pptx", "txt", "csv",
    "png", "jpg", "jpeg", "webp", "bmp", "gif", "tif", "tiff",
    "zip", "rar", "7z", "dwg", "dxf",
}


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("　", " ")
    return re.sub(r"\s+", " ", text).strip()


def _fold(text: str) -> str:
    """把全角标点/数字/字母折叠成半角，便于「语义同名」比对。

    只做字符映射，不删任何字符——保留原长度语义，避免误把不同名字折成同名。
    """

    return "".join(_FULLWIDTH_MAP.get(ch, ch) for ch in str(text or ""))


def _file_stem(name: str) -> str:
    """去掉「真实扩展名」并归一，用作匹配键。

    只剥离 ``_KNOWN_EXTENSIONS`` 里的扩展名，绝不能用 ``PurePosixPath.stem``——
    机型号（如 ``EW6.25-220``）里的小数点会被它当成扩展名分隔符，导致文件名
    被截断（``EW6.25-220机型参数`` 会变成 ``EW6``）。
    """

    text = _cell_text(name)
    dot = text.rfind(".")
    if dot > 0:
        ext = text[dot + 1 :].strip().lower()
        if ext in _KNOWN_EXTENSIONS:
            text = text[:dot]
    return _cell_text(text)
