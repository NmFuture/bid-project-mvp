from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
LOCAL_DATA_DIR = BASE_DIR / ".localdata"
DEFAULT_OPENCODE_PROVIDER_ID = "deepseek"
DEFAULT_OPENCODE_MODEL_ID = "deepseek-v4-flash"


def normalize_opencode_model_selection(provider_value: object, model_value: object) -> tuple[str, str]:
    # harness-08：big-pickle → 默认模型的映射与 opencode/docker-entrypoint.sh 的
    # resolve_model_selection() 互为镜像（entrypoint 内部已单点化），改动必须同步。
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


# harness-07（超时配置统一）：opencode 超时的唯一推导点。
# 三个概念命名分离，不再散落 max()/min() 隐式缝合：
# - read 超时（read_timeout_sec）：opencode 单次 HTTP 请求的读超时。
#   事实源 = 系统设置页 timeoutMs（用户可改）；未配置（空/0/非法）时回退
#   OPENCODE_TIMEOUT_SEC。
# - idle 超时（idle_timeout_sec）：轮询监管「无新输出即停滞」的判定时限。
#   事实源 = OPENCODE_TIMEOUT_SEC，钳制在 [120, 900]s：低于 120s 时脚本/生成
#   阶段无新消息的长会话会被误判停滞；高于 900s 则停滞会话悬挂过久才回收。
# - 总超时（run_read_timeout_sec）：长轮询 message 请求的整体读超时，
#   公式 = max(read, idle + 60s 收尾宽限)。不得短于 idle 监管时限，否则
#   HTTP 层先于监管触发，后端报错而 opencode 会话仍在后台运行。
OPENCODE_IDLE_TIMEOUT_MIN_SEC = 120.0
OPENCODE_IDLE_TIMEOUT_MAX_SEC = 900.0
OPENCODE_RUN_READ_GRACE_SEC = 60.0
OPENCODE_CONNECT_TIMEOUT_SEC = 10.0


@dataclass(frozen=True)
class OpencodeTimeoutProfile:
    """一次调用的生效超时（秒），字段语义见上方 harness-07 注释。"""

    read_timeout_sec: float
    idle_timeout_sec: float
    run_read_timeout_sec: float


def resolve_opencode_read_timeout_sec(configured_timeout_ms: object) -> float:
    """read 超时（秒）：系统设置页 timeoutMs / 1000，下限 1s；未配置时回退 OPENCODE_TIMEOUT_SEC。"""
    try:
        timeout_ms = float(configured_timeout_ms or 0)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        timeout_ms = 0.0
    if timeout_ms <= 0:
        timeout_ms = float(settings.opencode_timeout_sec) * 1000
    return max(1.0, timeout_ms / 1000)


def resolve_opencode_idle_timeout_sec(timeout_sec: float | None = None) -> float:
    """idle 超时（秒）：clamp(OPENCODE_TIMEOUT_SEC 或显式覆盖值, 120, 900)。"""
    configured = float(timeout_sec or settings.opencode_timeout_sec)
    return max(OPENCODE_IDLE_TIMEOUT_MIN_SEC, min(configured, OPENCODE_IDLE_TIMEOUT_MAX_SEC))


def resolve_opencode_timeouts(configured_timeout_ms: object) -> OpencodeTimeoutProfile:
    """从配置值推导三个超时（唯一推导点，公式见上方 harness-07 注释）。"""
    read = resolve_opencode_read_timeout_sec(configured_timeout_ms)
    idle = resolve_opencode_idle_timeout_sec()
    run_read = max(read, idle + OPENCODE_RUN_READ_GRACE_SEC)
    return OpencodeTimeoutProfile(
        read_timeout_sec=read,
        idle_timeout_sec=idle,
        run_read_timeout_sec=run_read,
    )


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


def _optional_float_env(name: str) -> float | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


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
    # engine-10：opencode serve 的 HTTP Basic 鉴权（服务端原生读 OPENCODE_SERVER_PASSWORD）。
    # 密码为空 = 不启用鉴权（本地安全默认）；生产由 docker-compose.5090.yml 强制非空。
    opencode_server_username: str
    opencode_server_password: str
    # B4（engine-06）：全局 Agent 并发预算（单一事实）。引擎默认请求槽、S1 分片槽、
    # 目录章节槽与进程型引擎（codex/pi）进程池全部从它派生，总并发恒 ≤ 预算。
    # 取代 OPENCODE_MAX_CONCURRENCY——原配置只限默认请求槽一个池，不代表总量，
    # 直接当预算回落会把 S1 分片压回串行，故不做旧值回落。默认值本地安全；
    # 5090 实测取值只写 docker-compose.5090.yml。
    agent_concurrency_budget: int
    # B2（engine-04）：send_prompt 重发与轮询断线重连预算，默认值本地安全；
    # 5090 实测取值只写 docker-compose.5090.yml。
    opencode_send_prompt_max_retries: int
    opencode_send_prompt_retry_backoff_sec: tuple[int, ...]
    opencode_poll_reconnect_max_attempts: int
    opencode_poll_reconnect_backoff_sec: tuple[int, ...]
    s1_parse_opencode_enabled: bool
    s1_parse_technical_shard_enabled: bool
    s1_parse_shard_concurrency: int
    s4_llm_fill_timeout_sec: float | None
    body_fill_concurrency: int
    s1_appendix_workers: int
    tech_outline_chapter_workers: int
    ocr_max_concurrent: int
    ocr_pdf_batch_size: int
    business_wiki_ocr_concurrency: int
    tech_wiki_preview_concurrency: int
    business_template_extractor_enabled: bool
    business_pdf_parse_engine: str
    business_pdf_engine_fallback: str
    business_pdf_ocr_fallback_enabled: bool
    material_wiki_auto_refresh: bool
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
    tech_outline_llm_finalize: bool
    fact_specs_override_path: Path
    fact_specs_versions_dir: Path

    # PostgreSQL
    database_url: str
    job_timing_db_connect_timeout_sec: int
    job_timing_db_statement_timeout_ms: int
    job_timing_db_lock_timeout_ms: int

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
    # harness-07：会话级超时（idle/总超时）的事实源，同时是系统设置页 timeoutMs
    # 未配置时 read 超时的回退默认；推导公式见本文件 resolve_opencode_timeouts。
    opencode_timeout_sec=float(os.getenv("OPENCODE_TIMEOUT_SEC", "1800")),
    opencode_server_username=os.getenv("OPENCODE_SERVER_USERNAME", "opencode").strip() or "opencode",
    opencode_server_password=os.getenv("OPENCODE_SERVER_PASSWORD", "").strip(),
    agent_concurrency_budget=_int_env("AGENT_CONCURRENCY_BUDGET", 8),
    # B2（engine-04）：send_prompt 只对「确认未送达」（连接未建立）重发，默认 2 次；
    # 轮询断线重连默认 6 次、退避合计约 23s，覆盖常规服务重启窗口。
    opencode_send_prompt_max_retries=_non_negative_int_env("OPENCODE_SEND_PROMPT_MAX_RETRIES", 2),
    opencode_send_prompt_retry_backoff_sec=_int_tuple_env("OPENCODE_SEND_PROMPT_RETRY_BACKOFF_SEC", (1, 2, 4)),
    opencode_poll_reconnect_max_attempts=_non_negative_int_env("OPENCODE_POLL_RECONNECT_MAX_ATTEMPTS", 6),
    opencode_poll_reconnect_backoff_sec=_int_tuple_env("OPENCODE_POLL_RECONNECT_BACKOFF_SEC", (1, 2, 4, 4, 4, 4)),
    s1_parse_opencode_enabled=_bool_env(
        "S1_PARSE_OPENCODE_ENABLED",
        os.getenv("APP_ENV", "development") == "production",
    ),
    s1_parse_technical_shard_enabled=_bool_env("S1_PARSE_TECHNICAL_SHARD_ENABLED", True),
    # projectBasics 与 6 个清单分片共 7 个独立会话，默认全部并发执行。
    s1_parse_shard_concurrency=_int_env("S1_PARSE_SHARD_CONCURRENCY", 7),
    # LLM 填写会话明显变长：独立超时，缺省沿用 OPENCODE_TIMEOUT_SEC；
    # 5090 实测取值只写 docker-compose.5090.yml。
    s4_llm_fill_timeout_sec=_optional_float_env("S4_LLM_FILL_TIMEOUT_SEC"),
    # 一键填写（正文+附表）的 compute 并发度；本地安全默认值，5090 实测取值只写
    # docker-compose.5090.yml。使用处另有 1~8 的 clamp 兜底。
    body_fill_concurrency=_int_env("BODY_FILL_CONCURRENCY", 4),
    # 以下六项此前是各服务模块内的硬编码常量，默认值与原值一致，仅打开调参能力；
    # 5090 实测取值只写 docker-compose.5090.yml。
    # S1 附表处理线程池，原为固定单线程。
    s1_appendix_workers=_int_env("S1_APPENDIX_WORKERS", 1),
    # 目录生成分章并发线程数；总槽位为本值 +1（projectBasics 占一个）。
    tech_outline_chapter_workers=_int_env("TECH_OUTLINE_CHAPTER_WORKERS", 6),
    # OcrService 自身的并发闸；真正的上限仍取决于 vLLM 单实例的批处理能力。
    ocr_max_concurrent=_int_env("OCR_MAX_CONCURRENT", 8),
    # 长 PDF 每批送入模型的页数，调大更省往返、调小更省显存。
    ocr_pdf_batch_size=_int_env("OCR_PDF_BATCH_SIZE", 10),
    business_wiki_ocr_concurrency=_int_env("BUSINESS_WIKI_OCR_CONCURRENCY", 8),
    tech_wiki_preview_concurrency=_int_env("TECH_WIKI_PREVIEW_CONCURRENCY", 8),
    business_template_extractor_enabled=_bool_env("BUSINESS_TEMPLATE_EXTRACTOR_ENABLED", True),
    business_pdf_parse_engine=os.getenv("BUSINESS_PDF_PARSE_ENGINE", "docling").strip().lower() or "docling",
    business_pdf_engine_fallback=os.getenv("BUSINESS_PDF_ENGINE_FALLBACK", "none").strip().lower() or "none",
    business_pdf_ocr_fallback_enabled=_bool_env("BUSINESS_PDF_OCR_FALLBACK_ENABLED", True),
    material_wiki_auto_refresh=_bool_env("MATERIAL_WIKI_AUTO_REFRESH", True),
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
    # 置 1 恢复旧串行 LLM 收口会话（附表判断 + LLM 全局复核 + compose/finalize 由 LLM 驱动）。
    # 默认关闭：5 次实测复核仅产出 1 次改判且为重复章节，质量兜底交给下游人工审核。
    tech_outline_llm_finalize=_bool_env("TECH_OUTLINE_LLM_FINALIZE", False),
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
    job_timing_db_connect_timeout_sec=_int_env("JOB_TIMING_DB_CONNECT_TIMEOUT_SEC", 2),
    job_timing_db_statement_timeout_ms=_int_env("JOB_TIMING_DB_STATEMENT_TIMEOUT_MS", 5000),
    job_timing_db_lock_timeout_ms=_int_env("JOB_TIMING_DB_LOCK_TIMEOUT_MS", 2000),
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


def opencode_auth_headers() -> dict[str, str]:
    """opencode 客户端请求的 HTTP Basic 鉴权头（engine-10）。

    密码为空返回空 dict：请求与无鉴权现状完全一致（本地安全默认）；
    密码非空时统一带 `Authorization: Basic <base64(username:password)>`。
    """
    if not settings.opencode_server_password:
        return {}
    credential = f"{settings.opencode_server_username}:{settings.opencode_server_password}"
    token = base64.b64encode(credential.encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}
