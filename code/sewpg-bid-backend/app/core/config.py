from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
LOCAL_DATA_DIR = BASE_DIR / ".localdata"
DEFAULT_OPENCODE_PROVIDER_ID = "deepseek"
DEFAULT_OPENCODE_MODEL_ID = "deepseek-v4-flash"


def normalize_opencode_model_selection(provider_value: object, model_value: object) -> tuple[str, str]:
    provider_id = str(provider_value or DEFAULT_OPENCODE_PROVIDER_ID).strip() or DEFAULT_OPENCODE_PROVIDER_ID
    model_id = str(model_value or DEFAULT_OPENCODE_MODEL_ID).strip() or DEFAULT_OPENCODE_MODEL_ID

    if (provider_id, model_id) == ("opencode", "big-pickle") or model_id == "opencode/big-pickle":
        return DEFAULT_OPENCODE_PROVIDER_ID, DEFAULT_OPENCODE_MODEL_ID

    if model_id == f"{DEFAULT_OPENCODE_PROVIDER_ID}/{DEFAULT_OPENCODE_MODEL_ID}":
        return DEFAULT_OPENCODE_PROVIDER_ID, DEFAULT_OPENCODE_MODEL_ID

    qualified_prefix = f"{provider_id}/"
    if model_id.startswith(qualified_prefix):
        model_id = model_id[len(qualified_prefix):].strip()
    return provider_id, model_id or DEFAULT_OPENCODE_MODEL_ID


def _csv_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    return default


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _non_negative_int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed >= 0 else default


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _docling_device_env() -> str:
    value = os.getenv("DOCLING_DEVICE", "cpu").strip().lower() or "cpu"
    return value if value in {"auto", "cpu", "cuda"} else "cpu"


def _int_tuple_env(name: str, default: tuple[int, ...]) -> tuple[int, ...]:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    parsed: list[int] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            number = int(item)
        except ValueError:
            continue
        if number >= 0:
            parsed.append(number)
    return tuple(parsed) or default


def _upload_extensions() -> tuple[str, ...]:
    raw = _csv_env(
        "ALLOWED_UPLOAD_EXTENSIONS",
        (
            ".pdf",
            ".doc",
            ".docx",
            ".md",
            ".txt",
            ".xls",
            ".xlsx",
            ".xlsm",
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".bmp",
            ".tif",
            ".tiff",
        ),
    )
    normalized: list[str] = []
    for item in raw:
        ext = item.lower().strip()
        if not ext:
            continue
        if not ext.startswith("."):
            ext = f".{ext}"
        normalized.append(ext)
    return tuple(dict.fromkeys(normalized)) or (".pdf", ".docx", ".md", ".png", ".jpg", ".jpeg")


@dataclass
class Settings:
    app_env: str
    uploads_dir: Path
    documents_dir: Path
    parsed_dir: Path
    project_store_backend: str
    opencode_base_url: str
    opencode_provider_id: str
    opencode_model_id: str
    opencode_timeout_sec: float
    opencode_max_concurrency: int
    s1_parse_opencode_enabled: bool
    business_template_extractor_enabled: bool
    business_pdf_parse_engine: str
    business_pdf_engine_fallback: str
    business_pdf_ocr_fallback_enabled: bool
    docling_artifacts_path: Path
    docling_device: str
    bid_internal_api_base_url: str
    onlyoffice_internal_url: str
    onlyoffice_backend_base_url: str
    cors_origins: list[str]
    allowed_upload_extensions: tuple[str, ...]
    max_upload_file_size_bytes: int
    onlyoffice_callback_token: str
    onlyoffice_callback_allowed_hosts: tuple[str, ...]
    onlyoffice_download_allowed_hosts: tuple[str, ...]
    onlyoffice_download_max_bytes: int
    s2_toc_output_file_name: str
    s2_toc_evidence_file_name: str
    fact_specs_override_path: Path
    fact_specs_versions_dir: Path

    # PostgreSQL
    database_url: str

    # MinIO
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_buckets: dict[str, str]

    # Redis / background jobs
    redis_url: str
    redis_job_lock_ttl_sec: int
    redis_job_queue_lock_ttl_sec: int
    redis_job_result_ttl_sec: int
    redis_worker_poll_timeout_sec: int

    # S1 parse async job
    s1_parse_job_max_attempts: int
    s1_parse_job_retry_backoff_sec: tuple[int, ...]
    parse_progress_persist_interval_sec: float

    # Auth bootstrap
    auth_admin_email: str
    auth_admin_password: str
    auth_admin_name: str
    auth_session_ttl_sec: int

    # Default model configuration shown in system settings.
    default_llm_base_url: str
    default_llm_api_key: str
    default_llm_model: str
    default_llm_provider_id: str
    default_ocr_base_url: str
    default_ocr_api_key: str
    default_ocr_model: str

    def ensure_dirs(self) -> None:
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        self.parsed_dir.mkdir(parents=True, exist_ok=True)


_configured_opencode_provider_id, _configured_opencode_model_id = normalize_opencode_model_selection(
    os.getenv("OPENCODE_PROVIDER_ID"),
    os.getenv("OPENCODE_MODEL_ID"),
)
_configured_default_llm_provider_id, _configured_default_llm_model_id = normalize_opencode_model_selection(
    _first_env("DEFAULT_LLM_PROVIDER_ID", default=_configured_opencode_provider_id),
    _first_env("DEFAULT_LLM_MODEL", default=_configured_opencode_model_id),
)

DOCUMENTS_DIR = Path(os.getenv("DOCUMENTS_DIR", str(LOCAL_DATA_DIR / "documents")))

settings = Settings(
    app_env=os.getenv("APP_ENV", "development"),
    uploads_dir=Path(os.getenv("UPLOADS_DIR", str(LOCAL_DATA_DIR / "uploads"))),
    documents_dir=DOCUMENTS_DIR,
    parsed_dir=Path(os.getenv("PARSED_DIR", str(LOCAL_DATA_DIR / "parsed"))),
    project_store_backend=os.getenv("APP_STORE_BACKEND", "postgres").strip().lower() or "postgres",
    opencode_base_url=os.getenv("OPENCODE_BASE_URL", "http://127.0.0.1:4096"),
    opencode_provider_id=_configured_opencode_provider_id,
    opencode_model_id=_configured_opencode_model_id,
    opencode_timeout_sec=float(os.getenv("OPENCODE_TIMEOUT_SEC", "1800")),
    opencode_max_concurrency=_int_env("OPENCODE_MAX_CONCURRENCY", 8),
    s1_parse_opencode_enabled=_bool_env(
        "S1_PARSE_OPENCODE_ENABLED",
        os.getenv("APP_ENV", "development") == "production",
    ),
    business_template_extractor_enabled=_bool_env("BUSINESS_TEMPLATE_EXTRACTOR_ENABLED", True),
    business_pdf_parse_engine=os.getenv("BUSINESS_PDF_PARSE_ENGINE", "docling").strip().lower() or "docling",
    business_pdf_engine_fallback=os.getenv("BUSINESS_PDF_ENGINE_FALLBACK", "none").strip().lower() or "none",
    business_pdf_ocr_fallback_enabled=_bool_env("BUSINESS_PDF_OCR_FALLBACK_ENABLED", True),
    docling_artifacts_path=Path(
        _first_env("BID_DOCLING_ARTIFACTS_PATH", "DOCLING_ARTIFACTS_PATH", default="/opt/docling-models")
    ),
    docling_device=_docling_device_env(),
    bid_internal_api_base_url=os.getenv("BID_INTERNAL_API_BASE_URL", "http://fastapi:8000").rstrip("/"),
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
    max_upload_file_size_bytes=_int_env("MAX_UPLOAD_FILE_SIZE_BYTES", 30 * 1024 * 1024 * 1024),
    onlyoffice_callback_token=os.getenv("ONLYOFFICE_CALLBACK_TOKEN", "").strip(),
    onlyoffice_callback_allowed_hosts=_csv_env(
        "ONLYOFFICE_CALLBACK_ALLOWED_HOSTS",
        ("onlyoffice", "127.0.0.1", "localhost"),
    ),
    onlyoffice_download_allowed_hosts=_csv_env(
        "ONLYOFFICE_DOWNLOAD_ALLOWED_HOSTS",
        ("onlyoffice", "127.0.0.1", "localhost"),
    ),
    onlyoffice_download_max_bytes=_int_env("ONLYOFFICE_DOWNLOAD_MAX_BYTES", 1024 * 1024 * 1024),
    s2_toc_output_file_name=os.getenv("S2_TOC_OUTPUT_FILE_NAME", "toc.json").strip() or "toc.json",
    s2_toc_evidence_file_name=os.getenv("S2_TOC_EVIDENCE_FILE_NAME", "toc_evidence.json").strip()
    or "toc_evidence.json",
    fact_specs_override_path=Path(
        os.getenv(
            "FACT_SPECS_OVERRIDE_PATH",
            str(DOCUMENTS_DIR / "technical_fact_field_specs.override.json"),
        )
    ),
    fact_specs_versions_dir=Path(
        os.getenv(
            "FACT_SPECS_VERSIONS_DIR",
            str(DOCUMENTS_DIR / "fact_spec_versions"),
        )
    ),
    database_url=os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://biduser:bidpass@localhost:5432/bidplatform",
    ),
    minio_endpoint=os.getenv("MINIO_ENDPOINT", "http://localhost:9000"),
    minio_access_key=os.getenv("MINIO_ROOT_USER", "minioadmin"),
    minio_secret_key=os.getenv("MINIO_ROOT_PASSWORD", "minioadmin"),
    minio_buckets={
        "materials": os.getenv("MINIO_BUCKET_MATERIALS", "bid-materials"),
        "documents": os.getenv("MINIO_BUCKET_DOCUMENTS", "bid-documents"),
        "templates": os.getenv("MINIO_BUCKET_TEMPLATES", "bid-templates"),
    },
    redis_url=os.getenv("REDIS_URL", "").strip(),
    redis_job_lock_ttl_sec=_int_env("REDIS_JOB_LOCK_TTL_SEC", 2 * 60 * 60),
    redis_job_queue_lock_ttl_sec=_int_env("REDIS_JOB_QUEUE_LOCK_TTL_SEC", 6 * 60 * 60),
    redis_job_result_ttl_sec=_int_env("REDIS_JOB_RESULT_TTL_SEC", 24 * 60 * 60),
    redis_worker_poll_timeout_sec=_int_env("REDIS_WORKER_POLL_TIMEOUT_SEC", 5),
    s1_parse_job_max_attempts=_int_env("S1_PARSE_JOB_MAX_ATTEMPTS", 3),
    s1_parse_job_retry_backoff_sec=_int_tuple_env("S1_PARSE_JOB_RETRY_BACKOFF_SEC", (30, 120)),
    parse_progress_persist_interval_sec=float(
        os.getenv("PARSE_PROGRESS_PERSIST_INTERVAL_SEC", "2").strip() or "2"
    ),
    auth_admin_email=os.getenv("AUTH_ADMIN_EMAIL", "admin@sewpg.com").strip() or "admin@sewpg.com",
    auth_admin_password=os.getenv("AUTH_ADMIN_PASSWORD", "123456").strip() or "123456",
    auth_admin_name=os.getenv("AUTH_ADMIN_NAME", "当前用户").strip() or "当前用户",
    auth_session_ttl_sec=_int_env("AUTH_SESSION_TTL_SEC", 24 * 60 * 60),
    default_llm_base_url=_first_env("DEFAULT_LLM_BASE_URL", "INTERNAL_LLM_BASE_URL"),
    default_llm_api_key=_first_env("DEFAULT_LLM_API_KEY", "INTERNAL_LLM_API_KEY"),
    default_llm_model=_configured_default_llm_model_id,
    default_llm_provider_id=_configured_default_llm_provider_id,
    default_ocr_base_url=_first_env("DEFAULT_OCR_BASE_URL"),
    default_ocr_api_key=_first_env("DEFAULT_OCR_API_KEY"),
    default_ocr_model=_first_env("DEFAULT_OCR_MODEL", default="deepseek-ai/DeepSeek-OCR"),
)
