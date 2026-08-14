"""docx（OPC zip 包）的低层搬运助手。

docx 就是一个 zip。改一个 XML 部件不需要把整包解压进内存再全量重压——那样做的
代价与文档里图片的总体积成正比，而图片恰恰是不该被动的部分。这里提供按条目搬运的
写法：只重写真正改动的部件，其余条目分块流式拷贝，内存占用与文档大小无关。
"""

from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path

# OPC 里体积大且流水线从不改写的部件：图片与内嵌对象（OLE，例如内嵌的 Excel）。
MEDIA_PREFIXES = ("word/media/", "word/embeddings/")
COPY_CHUNK = 1 << 20


def is_media_entry(name: str) -> bool:
    return str(name or "").lstrip("/").startswith(MEDIA_PREFIXES)


def stored_info(info: zipfile.ZipInfo, name: str | None = None) -> zipfile.ZipInfo:
    """按原条目派生一个不压缩的写入条目。

    图片本身已是压缩格式，zip 再 deflate 实测只省 2.5%（239MB→233MB），却要为此
    付出全量压缩的时间。Word 自己也这么做：招标模板里 973 张图有 915 张就是直存的。
    直存与否只改变 zip 的封装方式，不改变图片字节本身。
    """
    target = zipfile.ZipInfo(name or info.filename, date_time=info.date_time)
    target.compress_type = zipfile.ZIP_STORED
    target.external_attr = info.external_attr
    target.internal_attr = info.internal_attr
    target.create_system = info.create_system
    return target


def copy_entry(
    source: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    target: zipfile.ZipFile,
    *,
    name: str | None = None,
) -> None:
    """把一个条目搬到目标包里：媒体直存并分块流式拷贝，XML 保持原压缩方式。"""
    if is_media_entry(info.filename):
        with source.open(info, "r") as reader, target.open(stored_info(info, name), "w") as writer:
            shutil.copyfileobj(reader, writer, COPY_CHUNK)
        return
    entry = zipfile.ZipInfo(name or info.filename, date_time=info.date_time)
    entry.compress_type = info.compress_type
    entry.external_attr = info.external_attr
    entry.internal_attr = info.internal_attr
    entry.create_system = info.create_system
    target.writestr(entry, source.read(info))


def read_parts(docx_path: Path, names: set[str]) -> dict[str, bytes]:
    """只读出关心的那几个部件，不把整包拉进内存。"""
    found: dict[str, bytes] = {}
    with zipfile.ZipFile(docx_path, "r") as archive:
        available = set(archive.namelist())
        for name in names & available:
            found[name] = archive.read(name)
    return found


def rewrite_parts(docx_path: Path, updates: dict[str, bytes]) -> int:
    """就地替换若干部件的内容，其余条目原样搬运。返回实际替换的部件数。

    updates 里不存在于包中的部件名会被忽略——调用方应先用 read_parts 确认。
    """
    docx_path = Path(docx_path)
    if not updates:
        return 0
    replaced = 0
    tmp_path = docx_path.with_name(f"{docx_path.stem}.rewrite{docx_path.suffix}")
    try:
        with zipfile.ZipFile(docx_path, "r") as archive:
            with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as out:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    payload = updates.get(info.filename)
                    if payload is None:
                        copy_entry(archive, info, out)
                        continue
                    entry = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                    entry.compress_type = zipfile.ZIP_DEFLATED
                    entry.external_attr = info.external_attr
                    out.writestr(entry, payload)
                    replaced += 1
        os.replace(tmp_path, docx_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
    return replaced
