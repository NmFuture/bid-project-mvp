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
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS performance_categories (
                    id BIGSERIAL PRIMARY KEY,
                    name VARCHAR(300) NOT NULL,
                    scene VARCHAR(80),
                    power_rating VARCHAR(80),
                    summary TEXT,
                    field_schema JSONB DEFAULT '[]'::jsonb,
                    tags JSONB DEFAULT '[]'::jsonb,
                    scope VARCHAR(40) DEFAULT 'standard',
                    status VARCHAR(40) DEFAULT 'enabled',
                    review_status VARCHAR(40) DEFAULT 'draft',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        )
        await session.execute(text("ALTER TABLE performance_categories ADD COLUMN IF NOT EXISTS status VARCHAR(40) DEFAULT 'enabled'"))
        await session.execute(
            text(
                """
                UPDATE performance_categories
                SET status = 'disabled'
                WHERE review_status = 'disabled' AND COALESCE(status, 'enabled') <> 'disabled'
                """
            )
        )
        await session.execute(
            text(
                """
                UPDATE performance_categories
                SET status = 'enabled'
                WHERE COALESCE(status, '') = ''
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS performance_items (
                    id BIGSERIAL PRIMARY KEY,
                    category_id BIGINT NOT NULL REFERENCES performance_categories(id) ON DELETE CASCADE,
                    row_index INT NOT NULL,
                    project_name TEXT,
                    customer_name VARCHAR(300),
                    turbine_model VARCHAR(120),
                    turbine_models JSONB DEFAULT '[]'::jsonb,
                    contract_quantity VARCHAR(80),
                    trial_operation_quantity VARCHAR(80),
                    commissioned_capacity_mw VARCHAR(80),
                    delivery_or_operation_time VARCHAR(120),
                    contract_year INT,
                    delivery_year INT,
                    operation_year INT,
                    time_facts JSONB DEFAULT '{}'::jsonb,
                    contact_info VARCHAR(200),
                    row_values JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        )
        await session.execute(text("ALTER TABLE performance_items ADD COLUMN IF NOT EXISTS turbine_models JSONB DEFAULT '[]'::jsonb"))
        await session.execute(text("ALTER TABLE performance_items ADD COLUMN IF NOT EXISTS contract_year INT"))
        await session.execute(text("ALTER TABLE performance_items ADD COLUMN IF NOT EXISTS delivery_year INT"))
        await session.execute(text("ALTER TABLE performance_items ADD COLUMN IF NOT EXISTS operation_year INT"))
        await session.execute(text("ALTER TABLE performance_items ADD COLUMN IF NOT EXISTS time_facts JSONB DEFAULT '{}'::jsonb"))
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS performance_attachments (
                    id BIGSERIAL PRIMARY KEY,
                    category_id BIGINT NOT NULL REFERENCES performance_categories(id) ON DELETE CASCADE,
                    attachment_type VARCHAR(60) NOT NULL,
                    file_name VARCHAR(255) NOT NULL,
                    minio_key VARCHAR(500) NOT NULL,
                    minio_bucket VARCHAR(100) DEFAULT 'bid-materials',
                    mime_type VARCHAR(120),
                    size_bytes BIGINT DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    created_by VARCHAR(100)
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS performance_item_attachments (
                    id BIGSERIAL PRIMARY KEY,
                    category_id BIGINT NOT NULL REFERENCES performance_categories(id) ON DELETE CASCADE,
                    item_id BIGINT NOT NULL REFERENCES performance_items(id) ON DELETE CASCADE,
                    source_attachment_id BIGINT REFERENCES performance_attachments(id) ON DELETE CASCADE,
                    attachment_type VARCHAR(60) NOT NULL DEFAULT 'contract_item',
                    file_name VARCHAR(255) NOT NULL,
                    minio_key VARCHAR(500) NOT NULL,
                    minio_bucket VARCHAR(100) DEFAULT 'bid-materials',
                    mime_type VARCHAR(120),
                    size_bytes BIGINT DEFAULT 0,
                    format_version INT DEFAULT 1,
                    match_confidence INT DEFAULT 0,
                    match_method VARCHAR(80),
                    source_title TEXT,
                    source_block_start INT,
                    source_block_end INT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    created_by VARCHAR(100)
                )
                """
            )
        )
        await session.execute(text("ALTER TABLE performance_item_attachments ADD COLUMN IF NOT EXISTS format_version INT DEFAULT 1"))
        await session.execute(text("CREATE INDEX IF NOT EXISTS idx_performance_items_category_id ON performance_items(category_id)"))
        await session.execute(text("CREATE INDEX IF NOT EXISTS idx_performance_items_turbine_model ON performance_items(turbine_model)"))
        await session.execute(text("CREATE INDEX IF NOT EXISTS idx_performance_items_contract_year ON performance_items(contract_year)"))
        await session.execute(text("CREATE INDEX IF NOT EXISTS idx_performance_items_delivery_year ON performance_items(delivery_year)"))
        await session.execute(text("CREATE INDEX IF NOT EXISTS idx_performance_items_operation_year ON performance_items(operation_year)"))
        await session.execute(text("CREATE INDEX IF NOT EXISTS idx_performance_attachments_category_id ON performance_attachments(category_id)"))
        await session.execute(text("CREATE INDEX IF NOT EXISTS idx_performance_item_attachments_category_id ON performance_item_attachments(category_id)"))
        await session.execute(text("CREATE INDEX IF NOT EXISTS idx_performance_item_attachments_item_id ON performance_item_attachments(item_id)"))
        await session.execute(text("CREATE INDEX IF NOT EXISTS idx_performance_item_attachments_source_id ON performance_item_attachments(source_attachment_id)"))
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
