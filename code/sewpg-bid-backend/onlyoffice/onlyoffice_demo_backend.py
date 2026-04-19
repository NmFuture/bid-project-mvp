from __future__ import annotations

import json
import socket
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

BASE_DIR = Path(__file__).resolve().parent
FILES_DIR = BASE_DIR / "files"
WORD_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
APP_PORT = 8000
ONLYOFFICE_PORT = 8080


def get_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            lan_ip = sock.getsockname()[0]
            if lan_ip and not lan_ip.startswith("127."):
                return lan_ip
    except OSError:
        pass

    try:
        _, _, ip_addresses = socket.gethostbyname_ex(socket.gethostname())
        for ip_address in ip_addresses:
            if ip_address and not ip_address.startswith("127."):
                return ip_address
    except socket.gaierror:
        pass

    raise RuntimeError("Unable to determine a non-loopback LAN IP address.")


LAN_IP = get_lan_ip()
API_BASE_URL = f"http://{LAN_IP}:{APP_PORT}"
DOCUMENT_SERVER_URL = f"http://{LAN_IP}:{ONLYOFFICE_PORT}"

app = FastAPI(title="OnlyOffice Demo Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def build_document_key(doc_path: Path) -> str:
    stat = doc_path.stat()
    modified_at = datetime.fromtimestamp(stat.st_mtime).strftime("%Y%m%d%H%M%S")
    return f"{doc_path.stem}-{modified_at}-{stat.st_size}"


def build_doc_path(doc_id: str, require_exists: bool = True) -> Path:
    if not doc_id or Path(doc_id).name != doc_id or doc_id in {".", ".."}:
        raise ValueError(f"Invalid doc_id: {doc_id!r}")

    doc_path = (FILES_DIR / f"{doc_id}.docx").resolve()
    files_dir = FILES_DIR.resolve()
    if doc_path.parent != files_dir:
        raise ValueError(f"Resolved path escaped files directory: {doc_path}")
    if require_exists and not doc_path.is_file():
        raise FileNotFoundError(f"Document not found: {doc_path}")
    return doc_path


def get_existing_doc_path_or_404(doc_id: str) -> Path:
    try:
        return build_doc_path(doc_id, require_exists=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/files/{doc_id}.docx")
async def download_source_file(doc_id: str) -> FileResponse:
    doc_path = get_existing_doc_path_or_404(doc_id)
    return FileResponse(path=doc_path, media_type=WORD_MEDIA_TYPE, filename=doc_path.name)


@app.get("/api/documents/{doc_id}/config")
async def get_document_config(doc_id: str) -> dict[str, Any]:
    doc_path = get_existing_doc_path_or_404(doc_id)
    return {
        "document": {
            "fileType": "docx",
            "key": build_document_key(doc_path),
            "title": doc_path.name,
            "url": f"{API_BASE_URL}/api/files/{doc_id}.docx",
        },
        "documentType": "word",
        "type": "desktop",
        "permissions": {
            "edit": True,
            "download": True,
        },
        "editorConfig": {
            "mode": "edit",
            "lang": "zh-CN",
            "callbackUrl": f"{API_BASE_URL}/api/onlyoffice/callback/{doc_id}",
            "customization": {
                "autosave": True,
                "forcesave": True,
            },
        },
    }


@app.post("/api/onlyoffice/callback/{doc_id}")
async def onlyoffice_callback(doc_id: str, request: Request) -> dict[str, int]:
    raw_body = await request.body()

    try:
        body = json.loads(raw_body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        print(f"[OnlyOffice callback] doc_id={doc_id} invalid JSON body={raw_body!r}", flush=True)
        return {"error": 0}

    status = body.get("status")
    print(f"[OnlyOffice callback] doc_id={doc_id} status={status}", flush=True)
    print(
        f"[OnlyOffice callback] body={json.dumps(body, ensure_ascii=False, sort_keys=True)}",
        flush=True,
    )

    if status in {2, 6}:
        download_url = body.get("url")
        if not download_url:
            print("[OnlyOffice callback] Save event missing url, skipping overwrite.", flush=True)
            return {"error": 0}

        try:
            doc_path = build_doc_path(doc_id, require_exists=True)
            async with httpx.AsyncClient(timeout=120.0, follow_redirects=True, trust_env=False) as client:
                response = await client.get(download_url)
                response.raise_for_status()
            doc_path.write_bytes(response.content)
            print(f"[OnlyOffice callback] Saved updated file to {doc_path}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[OnlyOffice callback] Failed to persist updated file: {exc}", flush=True)

    return {"error": 0}


@app.get("/api/documents/{doc_id}/download")
async def download_final_file(doc_id: str) -> FileResponse:
    doc_path = get_existing_doc_path_or_404(doc_id)
    return FileResponse(
        path=doc_path,
        media_type=WORD_MEDIA_TYPE,
        filename=doc_path.name,
    )


@app.get("/api/documents/{doc_id}/meta")
async def get_document_meta(doc_id: str) -> dict[str, Any]:
    doc_path = get_existing_doc_path_or_404(doc_id)
    stat = doc_path.stat()
    updated_at = datetime.fromtimestamp(stat.st_mtime).isoformat()
    return {
        "docId": doc_id,
        "fileName": doc_path.name,
        "documentKey": build_document_key(doc_path),
        "lastSavedAt": updated_at,
        "fileSize": stat.st_size,
        "downloadUrl": f"{API_BASE_URL}/api/documents/{doc_id}/download",
        "fileUrl": f"{API_BASE_URL}/api/files/{doc_id}.docx",
        "callbackUrl": f"{API_BASE_URL}/api/onlyoffice/callback/{doc_id}",
    }


@app.get("/api/meta")
async def get_meta() -> dict[str, str]:
    return {
        "lan_ip": LAN_IP,
        "api_base_url": API_BASE_URL,
        "document_server_url": DOCUMENT_SERVER_URL,
    }
