from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
LOCAL_DATA_DIR = BASE_DIR / ".localdata"


def _csv_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _upload_extensions() -> tuple[str, ...]:
    raw = _csv_env("ALLOWED_UPLOAD_EXTENSIONS", (".pdf", ".docx"))
    normalized: list[str] = []
    for item in raw:
        ext = item.lower().strip()
        if not ext:
            continue
        if not ext.startswith("."):
            ext = f".{ext}"
        normalized.append(ext)
    return tuple(dict.fromkeys(normalized)) or (".pdf", ".docx")


@dataclass
class Settings:
    app_env: str
    sqlite_path: Path
    uploads_dir: Path
    documents_dir: Path
    parsed_dir: Path
    opencode_base_url: str
    opencode_provider_id: str
    opencode_model_id: str
    opencode_timeout_sec: float
    onlyoffice_internal_url: str
    onlyoffice_backend_base_url: str
    cors_origins: list[str]
    allowed_upload_extensions: tuple[str, ...]
    max_upload_file_size_bytes: int
    onlyoffice_callback_token: str
    onlyoffice_callback_allowed_hosts: tuple[str, ...]
    onlyoffice_download_allowed_hosts: tuple[str, ...]
    onlyoffice_download_max_bytes: int

    def ensure_dirs(self) -> None:
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        self.parsed_dir.mkdir(parents=True, exist_ok=True)


settings = Settings(
    app_env=os.getenv("APP_ENV", "development"),
    sqlite_path=Path(os.getenv("SQLITE_PATH", str(LOCAL_DATA_DIR / "sqlite" / "app.db"))),
    uploads_dir=Path(os.getenv("UPLOADS_DIR", str(LOCAL_DATA_DIR / "uploads"))),
    documents_dir=Path(os.getenv("DOCUMENTS_DIR", str(LOCAL_DATA_DIR / "documents"))),
    parsed_dir=Path(os.getenv("PARSED_DIR", str(LOCAL_DATA_DIR / "parsed"))),
    opencode_base_url=os.getenv("OPENCODE_BASE_URL", "http://127.0.0.1:4096"),
    opencode_provider_id=os.getenv("OPENCODE_PROVIDER_ID", "opencode"),
    opencode_model_id=os.getenv("OPENCODE_MODEL_ID", "big-pickle"),
    opencode_timeout_sec=float(os.getenv("OPENCODE_TIMEOUT_SEC", "60")),
    onlyoffice_internal_url=os.getenv("ONLYOFFICE_INTERNAL_URL", "http://127.0.0.1:8080"),
    onlyoffice_backend_base_url=os.getenv("ONLYOFFICE_BACKEND_BASE_URL", "").rstrip("/"),
    cors_origins=_csv_env(
        "CORS_ORIGINS",
        (
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1",
            "http://localhost",
        ),
    ),
    allowed_upload_extensions=_upload_extensions(),
    max_upload_file_size_bytes=_int_env("MAX_UPLOAD_FILE_SIZE_BYTES", 500 * 1024 * 1024),
    onlyoffice_callback_token=os.getenv("ONLYOFFICE_CALLBACK_TOKEN", "").strip(),
    onlyoffice_callback_allowed_hosts=_csv_env(
        "ONLYOFFICE_CALLBACK_ALLOWED_HOSTS",
        ("onlyoffice", "127.0.0.1", "localhost"),
    ),
    onlyoffice_download_allowed_hosts=_csv_env(
        "ONLYOFFICE_DOWNLOAD_ALLOWED_HOSTS",
        ("onlyoffice", "127.0.0.1", "localhost"),
    ),
    onlyoffice_download_max_bytes=_int_env("ONLYOFFICE_DOWNLOAD_MAX_BYTES", 500 * 1024 * 1024),
)
