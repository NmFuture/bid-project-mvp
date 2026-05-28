from __future__ import annotations

from typing import Any

from sqlalchemy import text


class MaterialRuntimeTables:
    def __init__(self) -> None:
        self._ready = False

    async def ensure(self, session: Any) -> None:
        if self._ready:
            return

        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS raw_folder_deletions (
                    path TEXT PRIMARY KEY,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    created_by VARCHAR(100)
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS raw_file_versions (
                    id BIGSERIAL PRIMARY KEY,
                    file_id BIGINT NOT NULL REFERENCES raw_files(id) ON DELETE CASCADE,
                    version INT NOT NULL,
                    minio_key VARCHAR(500) NOT NULL,
                    size_bytes BIGINT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    created_by VARCHAR(100)
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS wiki_attachments (
                    id BIGSERIAL PRIMARY KEY,
                    doc_id BIGINT NOT NULL REFERENCES wiki_docs(id) ON DELETE CASCADE,
                    file_name VARCHAR(255) NOT NULL,
                    size_bytes BIGINT DEFAULT 0,
                    mime_type VARCHAR(100),
                    minio_key VARCHAR(500),
                    minio_bucket VARCHAR(100) DEFAULT 'bid-materials',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    created_by VARCHAR(100)
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS template_assets (
                    id BIGSERIAL PRIMARY KEY,
                    asset_type VARCHAR(20) NOT NULL,
                    table_key VARCHAR(80),
                    file_name VARCHAR(255) NOT NULL,
                    version VARCHAR(40) NOT NULL,
                    minio_key VARCHAR(500),
                    minio_bucket VARCHAR(100) DEFAULT 'bid-templates',
                    size_bytes BIGINT DEFAULT 0,
                    mime_type VARCHAR(100),
                    is_active BOOLEAN DEFAULT FALSE,
                    uploaded_by VARCHAR(100),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS system_users (
                    id VARCHAR(80) PRIMARY KEY,
                    name VARCHAR(120) NOT NULL,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    dept VARCHAR(120),
                    roles VARCHAR(80)[] DEFAULT '{}',
                    status VARCHAR(20) DEFAULT 'active',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token VARCHAR(128) PRIMARY KEY,
                    user_id VARCHAR(80) NOT NULL REFERENCES system_users(id) ON DELETE CASCADE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    expires_at TIMESTAMPTZ NOT NULL,
                    revoked_at TIMESTAMPTZ,
                    user_agent TEXT,
                    ip_address VARCHAR(80)
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS system_configs (
                    key VARCHAR(100) PRIMARY KEY,
                    value JSONB NOT NULL,
                    sensitive BOOLEAN DEFAULT FALSE,
                    updated_by VARCHAR(100),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS backup_records (
                    id VARCHAR(80) PRIMARY KEY,
                    backup_type VARCHAR(20) DEFAULT 'manual',
                    status VARCHAR(20) DEFAULT 'success',
                    size_bytes BIGINT DEFAULT 0,
                    note TEXT,
                    manifest JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    created_by VARCHAR(100),
                    restored_at TIMESTAMPTZ,
                    restored_by VARCHAR(100)
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id BIGSERIAL PRIMARY KEY,
                    user_id VARCHAR(100) NOT NULL,
                    user_name VARCHAR(100),
                    action VARCHAR(80) NOT NULL,
                    action_type VARCHAR(40) NOT NULL,
                    module_id VARCHAR(80) NOT NULL,
                    module_label VARCHAR(200),
                    target VARCHAR(500),
                    status VARCHAR(20),
                    diff JSONB,
                    meta JSONB,
                    ip_address VARCHAR(80),
                    user_agent TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS performance_records (
                    id BIGSERIAL PRIMARY KEY,
                    name VARCHAR(300) NOT NULL,
                    customer_name VARCHAR(200),
                    project_type VARCHAR(120),
                    scale TEXT,
                    location VARCHAR(200),
                    started_at VARCHAR(40),
                    completed_at VARCHAR(40),
                    amount VARCHAR(120),
                    turbine_model VARCHAR(120),
                    tags JSONB DEFAULT '[]'::jsonb,
                    applicable_bid_types JSONB DEFAULT '[]'::jsonb,
                    scope VARCHAR(40) DEFAULT 'standard',
                    word_object_key VARCHAR(500),
                    word_file_name VARCHAR(255),
                    word_size_bytes BIGINT DEFAULT 0,
                    word_mime_type VARCHAR(120),
                    cleaned_object_key VARCHAR(500),
                    review_status VARCHAR(40) DEFAULT 'draft',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        )
        await session.execute(text("ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS meta JSONB"))
        await session.execute(text("ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS ip_address VARCHAR(80)"))
        await session.execute(text("ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS user_agent TEXT"))
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS ocr_tasks (
                    id VARCHAR(80) PRIMARY KEY,
                    project_id VARCHAR(50) NOT NULL,
                    source_file_name VARCHAR(255) NOT NULL,
                    source_path TEXT,
                    mime_type VARCHAR(100),
                    status VARCHAR(30) DEFAULT 'pending',
                    error_message TEXT,
                    page_count INT DEFAULT 0,
                    raw_response JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    created_by VARCHAR(100),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS ocr_candidates (
                    id VARCHAR(80) PRIMARY KEY,
                    task_id VARCHAR(80) NOT NULL REFERENCES ocr_tasks(id) ON DELETE CASCADE,
                    project_id VARCHAR(50) NOT NULL,
                    page_number INT DEFAULT 1,
                    field_name VARCHAR(200) NOT NULL,
                    field_value TEXT,
                    field_type VARCHAR(40) DEFAULT 'text',
                    confidence INT DEFAULT 80,
                    source_text TEXT,
                    status VARCHAR(30) DEFAULT 'pending',
                    confirmed_value TEXT,
                    confirmed_by VARCHAR(100),
                    confirmed_at TIMESTAMPTZ,
                    ignored_reason TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        )
        self._ready = True


_material_runtime_tables = MaterialRuntimeTables()


async def ensure_material_runtime_tables(session: Any) -> None:
    await _material_runtime_tables.ensure(session)
