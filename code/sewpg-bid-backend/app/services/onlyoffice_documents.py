from __future__ import annotations

from datetime import datetime
from pathlib import Path

import httpx
from docx import Document

from app.core.config import settings

WORD_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def document_path(project_id: str) -> Path:
    return settings.documents_dir / f"{project_id}.docx"


def build_document_key(path: Path) -> str:
    stat = path.stat()
    modified_at = datetime.fromtimestamp(stat.st_mtime).strftime("%Y%m%d%H%M%S")
    return f"{path.stem}-{modified_at}-{stat.st_size}"


def ensure_document(project_id: str, title: str, content: str) -> Path:
    path = document_path(project_id)
    if not path.exists():
        write_document(path, title, content)
    return path


def write_document(path: Path, title: str, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    doc = Document()
    title_text = Path(title).stem.strip()
    if title_text:
        doc.add_heading(title_text, level=0)

    for raw_line in (content or "").replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            doc.add_paragraph("")
            continue
        if line.startswith("### "):
            doc.add_heading(line[4:].strip(), level=3)
            continue
        if line.startswith("## "):
            doc.add_heading(line[3:].strip(), level=2)
            continue
        if line.startswith("# "):
            doc.add_heading(line[2:].strip(), level=1)
            continue
        doc.add_paragraph(line)

    doc.save(path)


async def download_document_from_onlyoffice(download_url: str, target_path: Path) -> None:
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True, trust_env=False) as client:
        response = await client.get(download_url)
        response.raise_for_status()
    target_path.write_bytes(response.content)
