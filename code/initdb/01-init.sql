-- ============================================================
-- Bid Platform Material Library Schema (PostgreSQL + pgvector)
-- ============================================================

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================
-- 1. Raw Material Library (原始素材库)
-- ============================================================

CREATE TABLE raw_folders (
    id          BIGSERIAL PRIMARY KEY,
    parent_id   BIGINT REFERENCES raw_folders(id) ON DELETE CASCADE,
    name        VARCHAR(255) NOT NULL,
    path        TEXT NOT NULL,
    tier        VARCHAR(20) NOT NULL CHECK (tier IN ('standard', 'customer', 'project')),
    bid_type    VARCHAR(20),                    -- 技术标 / 商务标 / 通用
    customer_name VARCHAR(200),                 -- 客户素材层用
    project_id  VARCHAR(50),                    -- 项目素材层用
    sort_order  INT DEFAULT 0,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_raw_folders_path ON raw_folders(path);
CREATE INDEX idx_raw_folders_parent ON raw_folders(parent_id);
CREATE INDEX idx_raw_folders_tier ON raw_folders(tier, bid_type);

CREATE TABLE raw_files (
    id          BIGSERIAL PRIMARY KEY,
    folder_id   BIGINT NOT NULL REFERENCES raw_folders(id) ON DELETE CASCADE,
    name        VARCHAR(255) NOT NULL,
    size_bytes  BIGINT NOT NULL DEFAULT 0,
    mime_type   VARCHAR(100),
    minio_key   VARCHAR(500) NOT NULL,
    minio_bucket VARCHAR(100) NOT NULL DEFAULT 'bid-materials',
    version     INT DEFAULT 1,
    ext_fields  JSONB DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    created_by  VARCHAR(100),
    updated_by  VARCHAR(100)
);

CREATE INDEX idx_raw_files_folder ON raw_files(folder_id);
CREATE INDEX idx_raw_files_name ON raw_files(name);

CREATE TABLE raw_file_versions (
    id          BIGSERIAL PRIMARY KEY,
    file_id     BIGINT NOT NULL REFERENCES raw_files(id) ON DELETE CASCADE,
    version     INT NOT NULL,
    minio_key   VARCHAR(500) NOT NULL,
    size_bytes  BIGINT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    created_by  VARCHAR(100)
);

-- ============================================================
-- 2. Structured Material Library (结构化素材库)
-- ============================================================

CREATE TABLE structured_tables (
    id          BIGSERIAL PRIMARY KEY,
    table_key   VARCHAR(80) UNIQUE NOT NULL,
    table_label VARCHAR(200) NOT NULL,
    schema_def  JSONB NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE structured_rows (
    id          BIGSERIAL PRIMARY KEY,
    table_id    BIGINT NOT NULL REFERENCES structured_tables(id) ON DELETE CASCADE,
    row_data    JSONB NOT NULL,
    version     INT DEFAULT 1,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    created_by  VARCHAR(100),
    updated_by  VARCHAR(100)
);

CREATE INDEX idx_structured_rows_table ON structured_rows(table_id);
CREATE INDEX idx_structured_rows_data ON structured_rows USING GIN (row_data);

CREATE TABLE structured_imports (
    id          BIGSERIAL PRIMARY KEY,
    table_id    BIGINT NOT NULL REFERENCES structured_tables(id),
    file_name   VARCHAR(255),
    minio_key   VARCHAR(500),
    row_count   INT,
    success_count INT,
    fail_count  INT,
    error_report JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    created_by  VARCHAR(100)
);

-- ============================================================
-- 3. Wiki Material Library (Wiki 素材库)
-- ============================================================

CREATE TABLE wiki_nodes (
    id          BIGSERIAL PRIMARY KEY,
    parent_id   BIGINT REFERENCES wiki_nodes(id) ON DELETE CASCADE,
    title       VARCHAR(300) NOT NULL,
    tier        VARCHAR(20) NOT NULL CHECK (tier IN ('standard', 'customer', 'project')),
    path        TEXT NOT NULL,
    bid_types   VARCHAR(20)[] DEFAULT ARRAY['通用']::varchar[],
    sort_order  INT DEFAULT 0,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_wiki_nodes_parent ON wiki_nodes(parent_id);
CREATE INDEX idx_wiki_nodes_path ON wiki_nodes(path);
CREATE INDEX idx_wiki_nodes_bid_types ON wiki_nodes USING GIN (bid_types);

CREATE TABLE wiki_docs (
    id          BIGSERIAL PRIMARY KEY,
    node_id     BIGINT NOT NULL UNIQUE REFERENCES wiki_nodes(id) ON DELETE CASCADE,
    markdown_content TEXT,
    ai_summary  TEXT,
    tags        VARCHAR(100)[] DEFAULT '{}',
    minio_key   VARCHAR(500),
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE wiki_attachments (
    id          BIGSERIAL PRIMARY KEY,
    doc_id      BIGINT NOT NULL REFERENCES wiki_docs(id) ON DELETE CASCADE,
    file_name   VARCHAR(255) NOT NULL,
    size_bytes  BIGINT DEFAULT 0,
    mime_type   VARCHAR(100),
    minio_key   VARCHAR(500),
    minio_bucket VARCHAR(100) DEFAULT 'bid-materials',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    created_by  VARCHAR(100)
);

CREATE TABLE wiki_paragraphs (
    id          BIGSERIAL PRIMARY KEY,
    doc_id      BIGINT NOT NULL REFERENCES wiki_docs(id) ON DELETE CASCADE,
    text        TEXT NOT NULL,
    embedding   vector(1024)
);

CREATE INDEX idx_wiki_paragraphs_embedding ON wiki_paragraphs
    USING hnsw (embedding vector_cosine_ops);

-- ============================================================
-- 3.1 Template Assets (.dotx / Excel)
-- ============================================================

CREATE TABLE template_assets (
    id          BIGSERIAL PRIMARY KEY,
    asset_type  VARCHAR(20) NOT NULL,
    table_key   VARCHAR(80),
    file_name   VARCHAR(255) NOT NULL,
    version     VARCHAR(40) NOT NULL,
    minio_key   VARCHAR(500),
    minio_bucket VARCHAR(100) DEFAULT 'bid-templates',
    size_bytes  BIGINT DEFAULT 0,
    mime_type   VARCHAR(100),
    is_active   BOOLEAN DEFAULT FALSE,
    uploaded_by VARCHAR(100),
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- 4. Audit Log (审计日志)
-- ============================================================

CREATE TABLE audit_log (
    id          BIGSERIAL PRIMARY KEY,
    user_id     VARCHAR(100) NOT NULL,
    user_name   VARCHAR(100),
    action      VARCHAR(80) NOT NULL,
    action_type VARCHAR(40) NOT NULL,
    module_id   VARCHAR(80) NOT NULL,
    module_label VARCHAR(200),
    target      VARCHAR(500),
    status      VARCHAR(20),
    diff        JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_audit_user_time ON audit_log (user_id, created_at DESC);
CREATE INDEX idx_audit_module_target ON audit_log (module_id, target);

-- ============================================================
-- 5. Seed Data (初始化示例数据)
-- ============================================================

-- Raw folders seed
INSERT INTO raw_folders (id, parent_id, name, path, tier, bid_type, customer_name, project_id, sort_order)
VALUES
    (1, NULL, '通用素材', '通用素材', 'standard', NULL, NULL, NULL, 1),
    (2, 1, '技术标', '通用素材/技术标', 'standard', '技术标', '平台标准', NULL, 1),
    (3, 1, '商务标', '通用素材/商务标', 'standard', '商务标', '平台标准', NULL, 2),
    (4, NULL, '客户素材', '客户素材', 'customer', NULL, NULL, NULL, 2),
    (5, 4, '华能集团', '客户素材/华能集团', 'customer', NULL, '华能集团', NULL, 1),
    (6, 5, '技术标', '客户素材/华能集团/技术标', 'customer', '技术标', '华能集团', NULL, 1),
    (7, 4, '大唐集团', '客户素材/大唐集团', 'customer', NULL, '大唐集团', NULL, 2),
    (8, 7, '技术标', '客户素材/大唐集团/技术标', 'customer', '技术标', '大唐集团', NULL, 1),
    (9, NULL, '项目素材', '项目素材', 'project', NULL, NULL, NULL, 3),
    (10, 5, '商务标', '客户素材/华能集团/商务标', 'customer', '商务标', '华能集团', NULL, 2),
    (11, 7, '商务标', '客户素材/大唐集团/商务标', 'customer', '商务标', '大唐集团', NULL, 2);

SELECT setval('raw_folders_id_seq', 11);

-- Structured tables seed
INSERT INTO structured_tables (id, table_key, table_label, schema_def)
VALUES
    (1, 'performance_guarantee', '性能保证', '{"columns": [{"name": "指标", "type": "text", "required": true}, {"name": "保证值", "type": "text", "required": true}, {"name": "备注", "type": "text", "required": false}]}'),
    (2, 'project_reference', '项目业绩', '{"columns": [{"name": "项目名称", "type": "text", "required": true}, {"name": "业主", "type": "text", "required": true}, {"name": "机型", "type": "text", "required": true}, {"name": "容量(MW)", "type": "number", "required": true}, {"name": "年份", "type": "number", "required": true}]}');

SELECT setval('structured_tables_id_seq', 2);

-- Wiki nodes seed
INSERT INTO wiki_nodes (id, parent_id, title, tier, path, bid_types, sort_order)
VALUES
    (1, NULL, '风资源', 'standard', '风资源', ARRAY['技术标','通用'], 1),
    (2, 1, '测风塔布设说明', 'standard', '风资源/测风塔布设说明', ARRAY['技术标'], 1),
    (3, NULL, '机组选型', 'standard', '机组选型', ARRAY['技术标','通用'], 2);

SELECT setval('wiki_nodes_id_seq', 3);

INSERT INTO wiki_docs (node_id, markdown_content, ai_summary, tags)
VALUES
    (2, '# 测风塔布设说明\n\n用于支撑风资源章节的测风布点说明。', '包含测风塔布设原则、数量与位置说明。', ARRAY['风资源', '技术标']);

-- Audit log seed
INSERT INTO audit_log (user_id, user_name, action, action_type, module_id, module_label, target, status, diff)
VALUES
    ('system', '系统初始化', '系统初始化', 'config', 'system', '系统', 'material_db', '成功', '{}');
