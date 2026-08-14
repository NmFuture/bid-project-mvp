"""大素材 docx 的媒体旁路：处理期只搬 XML，图片字节到最后一步才原样归位。

投标素材约 97% 的体积是图片字节（实测 234MB 的业绩情况素材里 789 张图占 239MB，
全部 XML 只有 7.1MB），而整条组装链路一个字节都不改它们。把这些字节在处理期换成
按原始 sha1 派生的小占位符，python-docx / docxcompose 就只需要面对几 MB 的 XML；
成稿写出时再按 sha1 把原始字节流式搬回。

由此得到两条保证：
- 保真：图片是字节级原样搬运，不解压重压、不重编码，与素材原件严格一致。
- 有界：任何一步的内存占用只与 XML 体量相关，与素材大小解耦。

占位符内容由原始 sha1 派生，因此「同图去重」语义与 docxcompose 原本按 sha1 去重
完全一致：内容相同的图片仍然只在成稿里存一份。
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import zipfile
from pathlib import Path
from typing import Any

from .docx_package import COPY_CHUNK, copy_entry, is_media_entry, stored_info

log = logging.getLogger("merger")

STUB_MAGIC = b"SEWPG-MEDIA-STUB-V1:"
VAULT_SCHEMA_VERSION = "bid-tech-media-vault-v1"

_HASH_CHUNK = 1 << 20
# 占位符只有几十字节；超过这个长度的条目一定是真实媒体，不必读出来比对。
_STUB_PROBE_LIMIT = 256


def _stub_payload(digest: str, size: int) -> bytes:
    return STUB_MAGIC + f"{digest}:{size}".encode("ascii")


def _stub_digest(payload: bytes) -> str | None:
    if not payload.startswith(STUB_MAGIC):
        return None
    body = payload[len(STUB_MAGIC) :].decode("ascii", errors="replace")
    digest, _, _ = body.partition(":")
    return digest or None


def _stream_sha1(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    digest = hashlib.sha1()
    with archive.open(info, "r") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


class MediaVault:
    """原始媒体字节的索引：sha1 → 去哪个文件的哪个条目取回它。"""

    def __init__(self, entries: dict[str, dict[str, Any]] | None = None) -> None:
        self._entries: dict[str, dict[str, Any]] = dict(entries or {})

    def __len__(self) -> int:
        return len(self._entries)

    def register(self, digest: str, *, source: Path | str, entry: str, size: int) -> None:
        # 首次登记即定案：同一 sha1 的字节内容按定义完全相同，换个来源取回结果一样。
        self._entries.setdefault(
            digest,
            {"source": str(source), "entry": str(entry), "size": int(size)},
        )

    def get(self, digest: str) -> dict[str, Any] | None:
        return self._entries.get(digest)

    def total_bytes(self) -> int:
        return sum(int(item.get("size") or 0) for item in self._entries.values())

    def rebase(self, old_root: Path | str, new_root: Path | str) -> None:
        """素材目录整体搬家后重挂来源路径。"""
        old_text = str(old_root)
        new_text = str(new_root)
        for record in self._entries.values():
            source = str(record.get("source") or "")
            if source.startswith(old_text):
                record["source"] = new_text + source[len(old_text) :]

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schemaVersion": VAULT_SCHEMA_VERSION, "entries": self._entries}
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> "MediaVault":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
            raise RuntimeError(f"媒体索引文件格式不正确：{path}")
        return cls(data["entries"])


def strip_media(src: Path, dst: Path, vault: MediaVault) -> dict[str, Any]:
    """把 src 的媒体条目换成占位符写出 dst，原始字节登记进 vault。

    非媒体部件（XML、rels）原样搬运；处理链路后续只会看到这些部件。
    """
    src = Path(src)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    stripped = 0
    stripped_bytes = 0
    with zipfile.ZipFile(src, "r") as archive, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as out:
        for info in archive.infolist():
            if info.is_dir():
                continue
            if not is_media_entry(info.filename):
                copy_entry(archive, info, out)
                continue
            if info.file_size <= _STUB_PROBE_LIMIT and _stub_digest(archive.read(info)) is not None:
                # 已经剥离过的文档再进来一次时原样放行：否则会把占位符自身当成原始
                # 字节登记，最后"还原"出来的就是占位符。
                copy_entry(archive, info, out)
                continue
            digest = _stream_sha1(archive, info)
            vault.register(digest, source=src, entry=info.filename, size=info.file_size)
            out.writestr(stored_info(info), _stub_payload(digest, info.file_size))
            stripped += 1
            stripped_bytes += int(info.file_size or 0)
    return {
        "strippedCount": stripped,
        "strippedBytes": stripped_bytes,
        "outputFile": str(dst),
    }


def restore_media_from_vault(light_file: str, output_file: str, vault_file: str) -> dict[str, Any]:
    """按索引文件归位图片。参数全是字符串，便于交给子进程执行。"""
    return restore_media(Path(light_file), Path(output_file), MediaVault.load(Path(vault_file)))


def restore_media(src: Path, dst: Path, vault: MediaVault) -> dict[str, Any]:
    """把 src 里的占位符按 vault 换回原始字节，流式写出 dst。

    只读写单个条目的分块，内存占用与文档总体积无关。找不到来源的占位符属于
    索引与成稿不一致，直接报错，不静默产出缺图的标书。
    """
    src = Path(src)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    handles: dict[str, zipfile.ZipFile] = {}
    missing: list[str] = []
    restored = 0
    restored_bytes = 0
    passthrough = 0

    def source_archive(path_text: str) -> zipfile.ZipFile:
        handle = handles.get(path_text)
        if handle is None:
            handle = zipfile.ZipFile(path_text, "r")
            handles[path_text] = handle
        return handle

    try:
        with zipfile.ZipFile(src, "r") as archive, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as out:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                digest = None
                if is_media_entry(info.filename) and info.file_size <= _STUB_PROBE_LIMIT:
                    digest = _stub_digest(archive.read(info))
                if digest is None:
                    copy_entry(archive, info, out)
                    passthrough += 1
                    continue
                record = vault.get(digest)
                if record is None or not Path(str(record.get("source") or "")).exists():
                    missing.append(f"{info.filename}({digest[:12]})")
                    continue
                target = stored_info(info)
                with source_archive(str(record["source"])).open(str(record["entry"]), "r") as reader:
                    with out.open(target, "w") as writer:
                        shutil.copyfileobj(reader, writer, COPY_CHUNK)
                restored += 1
                restored_bytes += int(record.get("size") or 0)
    finally:
        for handle in handles.values():
            handle.close()

    if missing:
        preview = "、".join(missing[:5])
        raise RuntimeError(
            f"媒体还原失败：{len(missing)} 个图片占位符在索引中找不到原始字节（{preview}）。"
        )

    log.info(
        "media restored → %s (%d 张图 %.1f MB，其余 %d 个部件原样搬运)",
        dst,
        restored,
        restored_bytes / 1024 / 1024,
        passthrough,
    )
    return {
        "restoredCount": restored,
        "restoredBytes": restored_bytes,
        "passthroughCount": passthrough,
        "outputFile": str(dst),
    }
