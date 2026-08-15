import asyncio
import re
from pathlib import Path
from typing import Any
from app.services.file_utils import format_size_label, safe_segment


def test_wiki_scope_rules_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    scope_source = Path("app/services/material_wiki_scope.py").read_text(encoding="utf-8")
    tree_source = Path("app/services/material_wiki_tree.py").read_text(encoding="utf-8")
    import_source = Path("app/services/material_wiki_import.py").read_text(encoding="utf-8")

    assert "def _bid_type_for_wiki_root" not in material_source
    assert "title.startswith(f\"{normalized_bid_type}Wiki\")" not in material_source
    assert "wiki_root_visible_for_bid_type" not in material_source
    assert "wiki_root_visible_for_bid_type" in tree_source
    assert "wiki_root_bid_type" not in material_source
    assert "wiki_root_bid_type" in import_source
    assert "def wiki_root_visible_for_bid_type" in scope_source
    assert "def wiki_root_bid_type" in scope_source


def test_raw_folder_scope_rules_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    folder_scope_source = Path("app/services/material_folder_scope.py").read_text(encoding="utf-8")
    folder_maintenance_source = Path("app/services/material_folder_maintenance.py").read_text(encoding="utf-8")
    folder_operations_source = Path("app/services/material_raw_folder_operations.py").read_text(encoding="utf-8")
    lifecycle_source = Path("app/services/material_raw_lifecycle_operations.py").read_text(encoding="utf-8")

    assert "RAW_MATERIAL_ROOTS" not in material_source
    assert "TECHNICAL_TIER_FOLDERS" not in material_source
    assert "BUSINESS_TIER_FOLDERS" not in material_source
    assert "BUSINESS_STANDARD_SUBFOLDERS" not in material_source
    assert "BUSINESS_CUSTOMIZED_SUBFOLDERS" not in material_source
    assert "canonical_technical_material_path" not in material_source
    assert not re.search(r"(?<!material_)bid_type_sort_order", material_source)
    assert "canonical_raw_folder_metadata" not in material_source
    assert "raw_material_tier_folder_specs" not in material_source
    assert "business_standard_subfolder_specs" not in material_source
    assert "business_customized_subfolder_specs" not in material_source
    assert "business_customized_child_tier_for_parent_folder_path" not in material_source
    assert "project_material_root_path" not in material_source
    assert "projectId 不能为空。" not in material_source
    assert "migrate_legacy_technical_folders(" not in material_source
    assert "bootstrap_project_material_folder(" not in material_source
    assert "ensure_business_standard_subfolders(" not in material_source
    assert "ensure_business_customized_children_for_created_folder(" not in material_source
    assert "def _ensure_material_target_folder" not in material_source
    assert "def _infer_material_tier_from_folder" not in material_source
    assert "def raw_permissions" not in material_source
    assert "build_raw_material_permissions" not in material_source
    assert "技术标素材" not in material_source
    assert "商务标素材" not in material_source
    assert "RawFolderDeletion" not in material_source
    assert "RAW_MATERIAL_DEFAULT_TIER_FOLDER_PATHS" not in material_source
    assert "def ensure_raw_material_roots" not in material_source
    assert "def ensure_folder_path" not in material_source
    assert "def canonical_raw_folder_metadata" in folder_scope_source
    assert "def raw_material_tier_folder_specs" in folder_scope_source
    assert "def business_standard_subfolder_specs" in folder_scope_source
    assert "def business_customized_subfolder_specs" in folder_scope_source
    assert "def build_raw_material_permissions" in folder_scope_source
    assert "def infer_material_tier_from_raw_folder" in folder_scope_source
    assert "def ensure_business_standard_subfolders" in folder_maintenance_source
    assert "def ensure_business_customized_subfolders" in folder_maintenance_source
    assert "def ensure_business_customized_children_for_created_folder" in folder_maintenance_source
    assert "def backfill_existing_business_customized_subfolders" in folder_maintenance_source
    assert "def migrate_legacy_technical_folders" in folder_maintenance_source
    assert "def ensure_material_target_folder" in folder_maintenance_source
    assert "def bootstrap_project_material_folder" in folder_maintenance_source
    assert "business_standard_subfolder_specs" in folder_maintenance_source
    assert "business_customized_subfolder_specs" in folder_maintenance_source
    assert "ensure_business_customized_children_for_created_folder(" in lifecycle_source
    assert "business_customized_child_tier_for_parent_folder_path" in folder_maintenance_source
    assert "canonical_technical_material_path" in folder_maintenance_source
    assert "客户素材必须填写客户名称。" in folder_maintenance_source
    assert "projectId 不能为空。" in folder_maintenance_source
    assert "class RawFolderOperations" in folder_operations_source
    assert "def ensure_raw_material_roots" in folder_operations_source
    assert "def deleted_default_folder_paths" in folder_operations_source
    assert "def mark_default_folder_deleted" in folder_operations_source
    assert "def clear_default_folder_deletion" in folder_operations_source
    assert "def ensure_canonical_folder" in folder_operations_source
    assert "def ensure_folder_path" in folder_operations_source
    assert "def ensure_nested_folder" in folder_operations_source
    assert "RawFolderDeletion" in folder_operations_source
    assert "RAW_MATERIAL_DEFAULT_TIER_FOLDER_PATHS" in folder_operations_source
    assert "canonical_raw_folder_metadata" in folder_operations_source
    assert "raw_material_tier_folder_specs" in folder_operations_source
    assert "migrate_legacy_technical_folders(" in folder_operations_source
    assert "bootstrap_project_material_folder(" in folder_operations_source


def test_material_runtime_tables_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    runtime_source = Path("app/services/material_runtime_tables.py").read_text(encoding="utf-8")
    template_source = Path("app/services/template_store.py").read_text(encoding="utf-8")
    settings_source = Path("app/services/system_settings.py").read_text(encoding="utf-8")
    audit_source = Path("app/services/audit_service.py").read_text(encoding="utf-8")
    auth_source = Path("app/services/auth_service.py").read_text(encoding="utf-8")
    ocr_source = Path("app/services/ocr_service.py").read_text(encoding="utf-8")
    business_gap_planning_source = Path("app/services/business_gap_planning.py").read_text(encoding="utf-8")

    assert "MaterialRuntimeTables" not in material_source
    assert "ensure_material_runtime_tables" in material_source
    assert "async def ensure_material_runtime_tables" not in material_source
    assert "_ensure_runtime_tables" not in material_source
    assert "CREATE TABLE IF NOT EXISTS raw_folder_deletions" not in material_source
    assert "CREATE TABLE IF NOT EXISTS wiki_attachments" not in material_source
    assert "CREATE TABLE IF NOT EXISTS template_assets" not in material_source
    assert "CREATE TABLE IF NOT EXISTS system_users" not in material_source
    assert "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS meta JSONB" not in material_source
    assert "CREATE TABLE IF NOT EXISTS ocr_candidates" not in material_source
    assert "class MaterialRuntimeTables" in runtime_source
    assert "CREATE TABLE IF NOT EXISTS raw_folder_deletions" in runtime_source
    assert "CREATE TABLE IF NOT EXISTS wiki_attachments" in runtime_source
    assert "CREATE TABLE IF NOT EXISTS template_assets" in runtime_source
    assert "CREATE TABLE IF NOT EXISTS system_users" in runtime_source
    assert "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS meta JSONB" in runtime_source
    assert "CREATE TABLE IF NOT EXISTS ocr_candidates" in runtime_source
    assert "async def ensure_material_runtime_tables" in runtime_source
    for source in [
        template_source,
        settings_source,
        audit_source,
        auth_source,
        ocr_source,
        business_gap_planning_source,
    ]:
        assert "from app.services.material_runtime_tables import ensure_material_runtime_tables" in source
        assert "from app.services.material_store import ensure_material_runtime_tables" not in source


def test_performance_items_runtime_schema_keeps_partner_name() -> None:
    from app.services.material_runtime_tables import MaterialRuntimeTables

    class SqlCaptureSession:
        def __init__(self) -> None:
            self.statements: list[str] = []

        async def execute(self, statement: Any) -> None:
            self.statements.append(str(statement))

    session = SqlCaptureSession()
    asyncio.run(MaterialRuntimeTables().ensure(session))

    create_statement = next(
        statement
        for statement in session.statements
        if "CREATE TABLE IF NOT EXISTS performance_items (" in statement
    )
    assert "partner_name VARCHAR(300)" in create_statement
    assert (
        "ALTER TABLE performance_items ADD COLUMN IF NOT EXISTS partner_name VARCHAR(300)"
        in session.statements
    )


def test_material_runtime_tables_repairs_duplicate_folder_paths_before_unique_index() -> None:
    from app.services.material_runtime_tables import MaterialRuntimeTables

    class SqlCaptureSession:
        def __init__(self) -> None:
            self.statements: list[str] = []

        async def execute(self, statement: Any) -> None:
            self.statements.append(str(statement))

    session = SqlCaptureSession()
    asyncio.run(MaterialRuntimeTables().ensure(session))

    migration_statement = next(
        statement
        for statement in session.statements
        if "CREATE UNIQUE INDEX idx_raw_folders_path" in statement
    )
    file_relink = migration_statement.index("UPDATE raw_files AS target")
    child_relink = migration_statement.index("UPDATE raw_folders AS child")
    duplicate_delete = migration_statement.index("DELETE FROM raw_folders AS target")
    unique_index = migration_statement.index("CREATE UNIQUE INDEX idx_raw_folders_path")

    assert "pg_advisory_xact_lock" in migration_statement
    assert "MIN(id) OVER (PARTITION BY path)" in migration_statement
    assert file_relink < child_relink < duplicate_delete < unique_index


def test_material_file_display_helpers_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    file_source = Path("app/services/file_utils.py").read_text(encoding="utf-8")
    template_source = Path("app/services/template_store.py").read_text(encoding="utf-8")
    settings_source = Path("app/services/system_settings.py").read_text(encoding="utf-8")
    parse_assets_source = Path("app/services/business_parse_assets.py").read_text(encoding="utf-8")
    splitter_source = Path("app/services/business_material_splitter.py").read_text(encoding="utf-8")

    assert safe_segment(" 客户/A 项目.docx ", "fallback.docx") == "客户-A 项目.docx"
    assert format_size_label(7) == "7 B"
    assert format_size_label(1536) == "1.5 KB"
    assert format_size_label(2 * 1024 * 1024) == "2.00 MB"
    assert "def safe_segment" not in material_source
    assert "def size_label" not in material_source
    assert "def now_display" not in material_source
    assert "from app.services.material_store import ensure_material_runtime_tables, size_label" not in template_source
    assert "from app.services.material_store import ensure_material_runtime_tables, safe_segment, size_label" not in settings_source
    assert "from app.services.material_store import safe_segment" not in parse_assets_source
    assert "from app.services.material_store import safe_segment" not in splitter_source
    assert "def safe_segment" in file_source
    assert "def format_size_label" in file_source
    assert "def now_display" in file_source
    assert "from app.services.file_utils import format_size_label as size_label" in template_source
    assert "from app.services.file_utils import format_size_label as size_label" in settings_source
    assert "from app.services.file_utils import safe_segment" in parse_assets_source
    assert "from app.services.file_utils import safe_segment" in splitter_source


def test_material_store_is_thin_operation_facade() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")

    blocked_snippets = [
        "from sqlalchemy",
        "from app.models.materials import",
        "from app.services.minio_client import minio_client",
        "async with async_session",
        "session.execute",
        "select(",
        "session.execute(insert(",
        "session.execute(update(",
        "session.execute(delete(",
        "minio_client.",
        "RawFile(",
        "RawFile.",
        "RawFolder(",
        "RawFolder.",
        "WikiNode",
        "WikiDoc",
        "WikiAttachment",
        "CREATE TABLE",
        "ALTER TABLE",
        "Jsonb",
        "psycopg",
    ]
    for snippet in blocked_snippets:
        assert snippet not in material_source

    expected_operation_calls = [
        "raw_tree_operation(",
        "identity_options_operation(",
        "raw_files_operation(",
        "upload_raw_files(",
        "update_raw_file(",
        "raw_download_file_operation(",
        "wiki_list_operation(",
        "upload_wiki_attachment(",
        "import_generated_wiki_blueprint_operation(",
        "move_raw_file(",
        "move_raw_folder(",
    ]
    for snippet in expected_operation_calls:
        assert snippet in material_source


def test_raw_tree_display_rules_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    operations_source = Path("app/services/material_raw_tree_operations.py").read_text(encoding="utf-8")
    tree_source = Path("app/services/material_raw_tree.py").read_text(encoding="utf-8")

    assert "raw_tree_operation(" in material_source
    assert "build_raw_tree_payload" not in material_source
    assert "select(RawFile)" not in material_source
    assert "order_by(RawFolder.sort_order, RawFolder.id)" not in material_source
    assert "subtree_file_count" not in material_source
    assert '"directFileCount": direct_file_count' not in material_source
    assert "def raw_tree_operation" in operations_source
    assert "build_raw_tree_payload" in operations_source
    assert "select(RawFile)" in operations_source
    assert "order_by(RawFolder.sort_order, RawFolder.id)" in operations_source
    assert "def build_raw_tree_payload" in tree_source
    assert "subtree_file_count" in tree_source
    assert '"directFileCount": direct_file_count' in tree_source


def test_raw_move_metadata_rules_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    move_source = Path("app/services/material_move_metadata.py").read_text(encoding="utf-8")
    operations_source = Path("app/services/material_move_operations.py").read_text(encoding="utf-8")

    assert "move_raw_file(" in material_source
    assert "move_raw_folder(" in material_source
    assert "build_raw_move_file_ext_fields" not in material_source
    assert "build_raw_move_folder_file_ext_fields" not in material_source
    assert "build_raw_move_file_ext_fields" in operations_source
    assert "build_raw_move_folder_file_ext_fields" in operations_source
    assert "def move_raw_file" in operations_source
    assert "def move_raw_folder" in operations_source
    assert "folder_id_to_new_path" not in material_source
    assert "folder.path.removeprefix(source.path)" not in material_source
    assert "目标路径存在同名文件" in operations_source
    assert "folder_id_to_new_path" in operations_source
    assert "folder.path.removeprefix(source.path)" in operations_source
    assert '"lastAction": "move-folder"' not in material_source
    assert '"lastAction": "version"' not in material_source
    assert '"lastAction": "move"' not in material_source
    assert '"materialTierLabel": MATERIAL_TIER_LABELS.get' not in material_source
    assert "def build_raw_move_file_ext_fields" in move_source
    assert "def build_raw_move_folder_file_ext_fields" in move_source
    assert "RAW_MOVE_FILE_ACTION" in move_source


def test_raw_folder_move_scope_rules_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    folder_scope_source = Path("app/services/material_folder_scope.py").read_text(encoding="utf-8")
    operations_source = Path("app/services/material_move_operations.py").read_text(encoding="utf-8")

    assert "is_raw_folder_move_protected_path" not in material_source
    assert "is_raw_folder_move_descendant_target" not in material_source
    assert "is_raw_folder_move_protected_path" in operations_source
    assert "is_raw_folder_move_descendant_target" in operations_source
    assert "bid_type: str" in operations_source
    assert "raw_folder_matches_bid_type(source, bid_type)" in operations_source
    assert "raw_folder_matches_bid_type(target_parent, bid_type)" in operations_source
    assert '"RAW_FOLDER_SCOPE"' in operations_source
    assert 'protected_paths = {"技术标", "商务标"}' not in material_source
    assert 'source_path in protected_paths' not in material_source
    assert "def is_raw_folder_move_protected_path" in folder_scope_source
    assert "def is_raw_folder_move_descendant_target" in folder_scope_source


def test_wiki_node_scope_rules_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    wiki_scope_source = Path("app/services/material_wiki_scope.py").read_text(encoding="utf-8")

    assert "wiki_node_bid_types" not in material_source
    assert '[bid_type] if bid_type in {"技术标", "商务标"} else ["通用"]' not in material_source
    assert "def wiki_node_bid_types" in wiki_scope_source
    assert "DEFAULT_WIKI_APPLICABLE_TYPE = GENERAL_BID_TYPE" in wiki_scope_source


def test_wiki_tree_display_rules_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    list_source = Path("app/services/material_wiki_list_operations.py").read_text(encoding="utf-8")
    tree_source = Path("app/services/material_wiki_tree.py").read_text(encoding="utf-8")

    assert "wiki_list_operation(" in material_source
    assert "build_wiki_tree_context" not in material_source
    assert "WikiNode" not in material_source
    assert "WikiDoc" not in material_source
    assert "WikiAttachment" not in material_source
    assert "selectedNode" not in material_source
    assert "tagOptions" not in material_source
    assert "collect_visible" not in material_source
    assert '"icon": "folder" if has_children else "article"' not in material_source
    assert "def wiki_list_operation" in list_source
    assert "build_wiki_tree_context" in list_source
    assert "WikiNode" in list_source
    assert "WikiDoc" in list_source
    assert "WikiAttachment" in list_source
    assert "selectedNode" in list_source
    assert "tagOptions" in list_source
    assert "def build_wiki_tree_context" in tree_source
    assert "collect_visible" in tree_source
    assert '"icon": "folder" if has_children else "article"' in tree_source


def test_wiki_node_operations_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    node_source = Path("app/services/material_wiki_node_operations.py").read_text(encoding="utf-8")

    # wiki 节点 create/update/delete 写操作已随 deadcode-04/05 移除（HTTP 端点先删，service 链失去入口）；
    # 只保留 refresh_wiki_summary / move_wiki_node（商务轨仍有路由在用）。
    assert "create_wiki_node(" not in material_source
    assert "update_wiki_node(" not in material_source
    assert "delete_wiki_node(" not in material_source
    assert "refresh_wiki_summary(" in material_source
    assert "move_wiki_node(" in material_source
    assert "新建节点，尚未生成摘要。" not in material_source
    assert "请在此补充节点内容。" not in material_source
    assert "node_depths" not in material_source
    assert "def collect(current: WikiNode" not in material_source
    assert "source.parent_id = new_parent_id" not in material_source
    assert "目标节点不存在。" not in material_source
    assert "def create_wiki_node" not in node_source
    assert "def update_wiki_node" not in node_source
    assert "def delete_wiki_node" not in node_source
    assert "def refresh_wiki_summary" in node_source
    assert "def move_wiki_node" in node_source
    assert "新建节点，尚未生成摘要。" not in node_source
    assert "请在此补充节点内容。" not in node_source
    assert "node_depths" not in node_source
    assert "def collect(current: WikiNode" not in node_source
    assert "source.parent_id = new_parent_id" in node_source
    assert "目标节点不存在。" in node_source


def test_wiki_attachment_operations_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    list_source = Path("app/services/material_wiki_list_operations.py").read_text(encoding="utf-8")
    attachment_source = Path("app/services/material_wiki_attachment_operations.py").read_text(encoding="utf-8")

    assert "upload_wiki_attachment(" in material_source
    assert "download_wiki_attachment_content(" in material_source
    assert "delete_wiki_attachment(" in material_source
    assert "wiki_download_attachment_content(self, attachment_id: str) ->" not in material_source
    assert "wiki_download_attachment_content(self, attachment_id: str, bid_type: str)" in material_source
    assert "wiki_attachment_to_dict(" not in material_source
    assert "def _wiki_attachment_key" not in material_source
    assert "def _wiki_attachment_to_dict" not in material_source
    assert "def _purge_wiki_attachment_object" not in material_source
    assert "WIKI_ATTACHMENT_NAME_REQUIRED" not in material_source
    assert "附件文件名不能为空。" not in material_source
    assert "stream.seek(0, 2)" not in material_source
    assert "minio_client.put_object_stream(bucket, key, stream" not in material_source
    assert "wiki_attachment_to_dict(" in list_source
    assert "def upload_wiki_attachment" in attachment_source
    assert "def download_wiki_attachment_content" in attachment_source
    assert "def delete_wiki_attachment" in attachment_source
    assert "def wiki_doc_matches_bid_type" in attachment_source
    assert "WIKI_ATTACHMENT_SCOPE" in attachment_source
    assert "def wiki_attachment_to_dict" in attachment_source
    assert "def purge_wiki_attachment_object" in attachment_source
    assert "def wiki_attachment_key" in attachment_source
    assert "WIKI_ATTACHMENT_NAME_REQUIRED" in attachment_source
    assert "附件文件名不能为空。" in attachment_source
    assert "stream.seek(0, 2)" in attachment_source
    assert "minio_client.put_object_stream(bucket, key, stream" in attachment_source


def test_wiki_import_rules_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    import_source = Path("app/services/material_wiki_import.py").read_text(encoding="utf-8")
    operations_source = Path("app/services/material_wiki_import_operations.py").read_text(encoding="utf-8")

    assert "import_generated_wiki_blueprint_operation(" in material_source
    assert "import_generated_wiki_blueprint(" in material_source
    assert "bid_type: str" in material_source
    assert "build_generated_wiki_root_spec" not in material_source
    assert "normalize_wiki_import_mode" not in material_source
    assert "AUTO_WIKI_DOC_SUMMARY" not in material_source
    assert "purge_wiki_root" not in material_source
    assert "purge_generated_children" not in material_source
    assert "duplicate_root" not in material_source
    assert "这是系统自动生成的分标类 Wiki 根节点" not in material_source
    assert "Wiki 已重新生成并覆盖" not in material_source
    assert "VALID_WIKI_IMPORT_MODES" not in material_source
    assert "def build_generated_wiki_root_spec" in import_source
    assert "def generated_wiki_import_message" in import_source
    assert "VALID_WIKI_IMPORT_MODES" in import_source
    assert "def import_generated_wiki_blueprint_operation" in operations_source
    assert "build_generated_wiki_root_spec" in operations_source
    assert "normalize_wiki_import_mode" in operations_source
    assert "normalize_wiki_bid_type" in operations_source
    assert "WIKI_IMPORT_SCOPE" in operations_source
    assert "WIKI_IMPORT_BID_TYPE_REQUIRED" in operations_source
    assert "AUTO_WIKI_DOC_SUMMARY" in operations_source
    assert "purge_wiki_root" in operations_source
    assert "sync_children_to_specs" in operations_source
    assert "purge_generated_children" not in operations_source
    assert "duplicate_root" in operations_source
    assert "PLATFORM_WIKI_SECTION_TITLES" in operations_source


def test_raw_update_metadata_rules_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    update_source = Path("app/services/material_update_metadata.py").read_text(encoding="utf-8")
    operations_source = Path("app/services/material_raw_update_operations.py").read_text(encoding="utf-8")

    assert "update_raw_file(" in material_source
    assert "build_raw_update_file_ext_fields" not in material_source
    assert "RAW_FILE_FOLDER_MISSING" not in material_source
    assert "RAW_FILE_NAME_REQUIRED" not in material_source
    assert "目标目录存在同名文件。" not in material_source
    assert "minio_client.copy_object" not in material_source
    assert "重命名成功" not in material_source
    assert '"businessMaterialKindLabel": BUSINESS_MATERIAL_KIND_LABELS.get' not in material_source
    assert '"lastAction": "update"' not in material_source
    assert "def update_raw_file" in operations_source
    assert "build_raw_update_file_ext_fields" in operations_source
    assert "RAW_FILE_FOLDER_MISSING" in operations_source
    assert "RAW_FILE_NAME_REQUIRED" in operations_source
    assert "目标目录存在同名文件。" in operations_source
    assert "minio_client.copy_object" in operations_source
    assert "重命名成功" in operations_source
    assert "def build_raw_update_file_ext_fields" in update_source
    assert '"lastAction": "update"' in update_source


def test_material_identity_options_rules_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    identity_source = Path("app/services/material_identity_options.py").read_text(encoding="utf-8")
    operations_source = Path("app/services/material_identity_options_operations.py").read_text(encoding="utf-8")

    assert "identity_options_operation(" in material_source
    assert "build_material_identity_options" not in material_source
    assert "def add_customer" not in material_source
    assert "def add_project" not in material_source
    assert "canonical_customer" not in material_source
    assert "build_project_identity" not in material_source
    assert "SELECT id, payload FROM projects" not in material_source
    assert "def identity_options_operation" in operations_source
    assert "build_material_identity_options" in operations_source
    assert "SELECT id, payload FROM projects" in operations_source
    assert "def build_material_identity_options" in identity_source
    assert "canonical_customer" in identity_source
    assert "build_project_identity" in identity_source


def test_raw_file_filter_rules_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    filter_source = Path("app/services/material_raw_file_filter.py").read_text(encoding="utf-8")
    operations_source = Path("app/services/material_raw_file_operations.py").read_text(encoding="utf-8")

    assert "raw_files_operation(" in material_source
    assert "build_raw_files_payload" not in material_source
    assert "project_matches" not in material_source
    assert "customer_matches" not in material_source
    assert "raw_file_matches_scope" not in material_source
    assert "selectinload(RawFile.folder)" not in material_source
    assert "RawFolder.path.like" not in material_source
    assert "RawFile.name.ilike" not in material_source
    assert "desc(RawFile.updated_at)" not in material_source
    assert "def build_raw_files_payload" in filter_source
    assert "def raw_file_matches_scope" in filter_source
    assert "project_matches" in filter_source
    assert "customer_matches" in filter_source
    assert "def raw_files_operation" in operations_source
    assert "build_raw_files_payload" in operations_source
    assert "selectinload(RawFile.folder)" in operations_source
    assert "RawFolder.path.like" in operations_source
    assert "RawFile.name.ilike" in operations_source
    assert "desc(RawFile.updated_at)" in operations_source


def test_material_scope_helpers_require_explicit_bid_type() -> None:
    scoped_sources = {
        "material_identity_options.py": Path("app/services/material_identity_options.py").read_text(encoding="utf-8"),
        "material_identity_options_operations.py": Path(
            "app/services/material_identity_options_operations.py"
        ).read_text(encoding="utf-8"),
        "material_raw_file_filter.py": Path("app/services/material_raw_file_filter.py").read_text(encoding="utf-8"),
        "material_raw_file_operations.py": Path("app/services/material_raw_file_operations.py").read_text(
            encoding="utf-8"
        ),
        "material_raw_tree.py": Path("app/services/material_raw_tree.py").read_text(encoding="utf-8"),
        "material_raw_tree_operations.py": Path("app/services/material_raw_tree_operations.py").read_text(
            encoding="utf-8"
        ),
        "material_wiki_scope.py": Path("app/services/material_wiki_scope.py").read_text(encoding="utf-8"),
        "material_wiki_tree.py": Path("app/services/material_wiki_tree.py").read_text(encoding="utf-8"),
        "material_wiki_list_operations.py": Path("app/services/material_wiki_list_operations.py").read_text(
            encoding="utf-8"
        ),
        "material_move_metadata.py": Path("app/services/material_move_metadata.py").read_text(encoding="utf-8"),
        "material_raw_access_operations.py": Path("app/services/material_raw_access_operations.py").read_text(
            encoding="utf-8"
        ),
        "material_raw_lifecycle_operations.py": Path("app/services/material_raw_lifecycle_operations.py").read_text(
            encoding="utf-8"
        ),
        "material_raw_update_operations.py": Path("app/services/material_raw_update_operations.py").read_text(
            encoding="utf-8"
        ),
        "material_move_operations.py": Path("app/services/material_move_operations.py").read_text(encoding="utf-8"),
        "material_store.py": Path("app/services/material_store.py").read_text(encoding="utf-8"),
    }

    for source in scoped_sources.values():
        assert 'bid_type: str = ""' not in source
    assert 'item_bid_type: str = ""' not in scoped_sources["material_identity_options.py"]
    assert 'destination_bid_type: str = ""' not in scoped_sources["material_move_metadata.py"]
    assert "async def raw_tree(self) ->" not in scoped_sources["material_store.py"]
    assert "async def raw_tree(self, *, bid_type: str)" in scoped_sources["material_store.py"]
    assert "raw_tree=lambda: self.raw_tree(bid_type=bid_type)" in scoped_sources["material_store.py"]
    assert "async def raw_create_folder(self, parent_path: str, folder_name: str, *, bid_type: str)" in scoped_sources[
        "material_store.py"
    ]
    assert "async def raw_delete_folder(self, path: str, *, bid_type: str)" in scoped_sources["material_store.py"]
    assert (
        "async def raw_move_folder(self, source_path: str, target_parent_path: str, *, bid_type: str)"
        in scoped_sources["material_store.py"]
    )
    assert "async def raw_delete_file(self, file_id: str) ->" not in scoped_sources["material_store.py"]
    assert "async def raw_delete_file(self, file_id: str, *, bid_type: str)" in scoped_sources["material_store.py"]
    assert "async def raw_download_file(self, file_id: str) ->" not in scoped_sources["material_store.py"]
    assert "async def raw_download_content(self, file_id: str) ->" not in scoped_sources["material_store.py"]
    assert "async def raw_download_cleaned_content(self, file_id: str) ->" not in scoped_sources["material_store.py"]
    assert "raw_file_matches_bid_type" in scoped_sources["material_raw_access_operations.py"]
    assert "raw_file_matches_bid_type" in scoped_sources["material_raw_lifecycle_operations.py"]
    assert "raw_file_matches_bid_type" in scoped_sources["material_raw_update_operations.py"]
    assert "raw_folder_matches_bid_type(parent, bid_type)" in scoped_sources["material_raw_lifecycle_operations.py"]
    assert "raw_folder_matches_bid_type(folder, bid_type)" in scoped_sources["material_raw_lifecycle_operations.py"]
    assert "raw_folder_matches_bid_type" in scoped_sources["material_move_operations.py"]
    assert "raw_folder_matches_bid_type(source, bid_type)" in scoped_sources["material_move_operations.py"]
    assert "raw_folder_matches_bid_type(target_parent, bid_type)" in scoped_sources["material_move_operations.py"]


def test_raw_upload_target_rules_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    target_source = Path("app/services/material_upload_target.py").read_text(encoding="utf-8")
    operations_source = Path("app/services/material_upload_operations.py").read_text(encoding="utf-8")

    assert "upload_raw_files(" in material_source
    assert "build_raw_upload_target_plan" not in material_source
    assert "resolve_raw_upload_canonical_target" not in material_source
    assert "build_raw_upload_target_plan" in operations_source
    assert "resolve_raw_upload_canonical_target" in operations_source
    assert "classify_material_path" not in material_source
    assert "target_parts = [part for part in target_path.split" not in material_source
    assert "def build_raw_upload_target_plan" in target_source
    assert "def resolve_raw_upload_canonical_target" in target_source
    assert "classify_material_path" in target_source


def test_raw_upload_action_metadata_rules_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    metadata_source = Path("app/services/material_upload_metadata.py").read_text(encoding="utf-8")
    operations_source = Path("app/services/material_upload_operations.py").read_text(encoding="utf-8")

    assert "upload_raw_files(" in material_source
    assert "build_raw_upload_record_ext_fields" not in material_source
    assert "build_raw_upload_existing_ext_fields" not in material_source
    assert "build_raw_upload_record_ext_fields" in operations_source
    assert "build_raw_upload_existing_ext_fields" in operations_source
    assert "RAW_UPLOAD_CONFLICT_ACTIONS" not in material_source
    assert "RAW_UPLOAD_CONFLICT_ACTIONS" in operations_source
    assert "def upload_raw_files" in operations_source
    assert "RAW_UPLOAD_FILES_REQUIRED" not in material_source
    assert "RAW_UPLOAD_FILES_REQUIRED" in operations_source
    assert "RAW_FILE_TYPE_NOT_ALLOWED" not in material_source
    assert "RAW_FILE_TYPE_NOT_ALLOWED" in operations_source
    assert "file_stream.seek(0, 2)" not in material_source
    assert "file_stream.seek(0, 2)" in operations_source
    assert "build_raw_upload_ext_fields" in operations_source
    assert '"lastAction": "upload"' not in material_source
    assert 'ext["lastAction"] = on_conflict' not in material_source
    assert '"lastOperator": "当前用户"' not in material_source
    assert "RAW_UPLOAD_CONFLICT_ACTIONS" in metadata_source
    assert "def build_raw_upload_record_ext_fields" in metadata_source
    assert "def build_raw_upload_existing_ext_fields" in metadata_source


def test_raw_access_operations_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    access_source = Path("app/services/material_raw_access_operations.py").read_text(encoding="utf-8")

    assert "raw_download_file_operation(" in material_source
    assert "raw_download_content_operation(" in material_source
    assert "raw_cleaned_preview_operation(" in material_source
    assert "raw_download_cleaned_content_operation(" in material_source
    assert "raw_download_cleaned_file_operation(" not in material_source
    assert "def raw_download_cleaned_file(" not in material_source
    assert "def _cleaned_object_key" not in material_source
    assert "hashlib.sha1" not in material_source
    assert "PurePosixPath" not in material_source
    assert "quote(cleaned_file_name)" not in material_source
    assert "RAW_CLEANED_PREVIEW_UNAVAILABLE" not in material_source
    assert "documentKey" not in material_source
    assert "browserFileUrl" not in material_source
    assert "cleaned/content" not in material_source
    assert "def raw_download_file_operation" in access_source
    assert "def raw_download_content_operation" in access_source
    assert "def raw_cleaned_preview_operation" in access_source
    assert "def raw_download_cleaned_content_operation" in access_source
    assert "def raw_download_cleaned_file_operation" not in access_source
    assert "hashlib.sha1" in access_source
    assert "PurePosixPath" in access_source
    assert "quote(cleaned_file_name)" in access_source
    assert "RAW_CLEANED_PREVIEW_UNAVAILABLE" in access_source
    assert "documentKey" in access_source
    assert "browserFileUrl" in access_source
    assert "cleaned/content" in access_source


def test_raw_lifecycle_operations_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    lifecycle_source = Path("app/services/material_raw_lifecycle_operations.py").read_text(encoding="utf-8")

    assert "create_raw_folder(" in material_source
    assert "delete_raw_folder(" in material_source
    assert "delete_raw_file(" in material_source
    assert "retry_clean_raw_file(" not in material_source
    assert "def raw_retry_clean_file(" not in material_source
    assert "RAW_FOLDER_NAME_REQUIRED" not in material_source
    assert "文件夹名称不能为空。" not in material_source
    assert "文件夹创建成功。" not in material_source
    assert "RAW_FOLDER_EXISTS" not in material_source
    assert "parent_path.strip" not in material_source
    assert "RAW_FOLDER_DELETE_PROTECTED" not in material_source
    assert "文件夹删除成功，共删除" not in material_source
    assert "deletedFileCount" not in material_source
    assert "RawFolder.path.startswith" not in material_source
    assert "await self._mark_default_folder_deleted(session, folder_path)" not in material_source
    assert "RAW_FILE_NOT_CLEANABLE" not in material_source
    assert "cleanUpdatedAt" not in material_source
    assert "已重新触发素材清洗。" not in material_source
    assert '"message": "删除成功"' not in material_source
    assert "payload = item.to_dict()" not in material_source
    assert "def create_raw_folder" in lifecycle_source
    assert "def delete_raw_folder" in lifecycle_source
    assert "def delete_raw_file" in lifecycle_source
    assert "def retry_clean_raw_file" not in lifecycle_source
    assert "RAW_FOLDER_NAME_REQUIRED" in lifecycle_source
    assert "文件夹名称不能为空。" in lifecycle_source
    assert "文件夹创建成功。" in lifecycle_source
    assert "RAW_FOLDER_EXISTS" in lifecycle_source
    assert "parent_path_text.strip" in lifecycle_source
    assert "raw_folder_matches_bid_type(parent, bid_type)" in lifecycle_source
    assert "RAW_FOLDER_DELETE_PROTECTED" in lifecycle_source
    assert "raw_folder_matches_bid_type(folder, bid_type)" in lifecycle_source
    assert '"RAW_FOLDER_SCOPE"' in lifecycle_source
    assert "文件夹删除成功，共删除" in lifecycle_source
    assert "deletedFileCount" in lifecycle_source
    assert "RawFolder.path.startswith" in lifecycle_source
    assert "mark_default_folder_deleted(session, folder_path)" in lifecycle_source
    assert "RAW_FILE_NOT_CLEANABLE" not in lifecycle_source
    assert "cleanUpdatedAt" not in lifecycle_source
    assert "已重新触发素材清洗。" not in lifecycle_source
    assert "purge_raw_file_objects(session, item)" in lifecycle_source
    assert '"message": "删除成功"' in lifecycle_source


def test_raw_file_object_operations_are_outside_material_store() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")
    object_source = Path("app/services/material_raw_object_operations.py").read_text(encoding="utf-8")

    assert "archive_raw_file_version" in material_source
    assert "purge_raw_file_objects" in material_source
    assert "remove_cleaned_object_from_ext" in material_source
    assert "enqueue_cleaning_job" in material_source
    assert "def _archive_raw_file_version" not in material_source
    assert "def _purge_raw_file_objects" not in material_source
    assert "def _remove_cleaned_object_from_ext" not in material_source
    assert "def _enqueue_cleaning_job" not in material_source
    assert "def _raw_object_key" not in material_source
    assert "RawFileVersion(" not in material_source
    assert "select(RawFileVersion)" not in material_source
    assert "minio_client.remove_object" not in material_source
    assert "enqueue_generation_job" not in material_source
    assert "Failed to remove cleaned material object" not in material_source
    assert "Failed to enqueue material cleaning job" not in material_source
    assert "def archive_raw_file_version" in object_source
    assert "def purge_raw_file_objects" in object_source
    assert "def remove_cleaned_object_from_ext" in object_source
    assert "def enqueue_cleaning_job" in object_source
    assert "def raw_object_key" in object_source
    assert "RawFileVersion(" in object_source
    assert "select(RawFileVersion)" in object_source
    assert "minio_client.remove_object" in object_source
    assert "enqueue_generation_job" in object_source
    assert "Failed to remove cleaned material object" in object_source
    assert "Failed to enqueue material cleaning job" in object_source


def test_legacy_structured_material_store_api_is_removed() -> None:
    material_source = Path("app/services/material_store.py").read_text(encoding="utf-8")

    assert not Path("app/services/material_structured_operations.py").exists()
    assert "material_structured_operations" not in material_source
    assert "def structured_list(" not in material_source
    assert "def structured_template(" not in material_source
    assert "def structured_create(" not in material_source
    assert "def structured_delete(" not in material_source
    assert "def structured_update(" not in material_source
    assert "def structured_import_preview(" not in material_source
    assert "def structured_confirm_import(" not in material_source
    assert "def structured_import_excel(" not in material_source
    assert "StructuredTable" not in material_source
    assert "StructuredRow" not in material_source
    assert "STRUCTURED_TABLE_INVALID" not in material_source
    assert "STRUCTURED_MATERIAL_NOT_FOUND" not in material_source
    assert "导入模板.xlsx" not in material_source
    assert "待导入模板.xlsx" not in material_source
    assert "Imported" not in material_source
    assert "Deleted" not in material_source
    assert "Updated" not in material_source


def test_legacy_peripheral_structured_material_api_is_removed() -> None:
    peripheral_source = Path("app/services/peripheral.py").read_text(encoding="utf-8")
    template_source = Path("app/services/template_store.py").read_text(encoding="utf-8")

    assert "_structured_items" not in peripheral_source
    assert "_structured_table_options" not in peripheral_source
    assert "_structured_import_history" not in peripheral_source
    assert "_structured_latest_receipt" not in peripheral_source
    assert "def structured_list(" not in peripheral_source
    assert "def structured_template(" not in peripheral_source
    assert "def structured_preview_import(" not in peripheral_source
    assert "def structured_confirm_import(" not in peripheral_source
    assert "def structured_create(" not in peripheral_source
    assert "def structured_update(" not in peripheral_source
    assert "def structured_delete(" not in peripheral_source
    assert "def structured_import_excel(" not in peripheral_source
    assert "materials_structured" not in peripheral_source
    assert "导入结构化素材" not in peripheral_source
    assert "STRUCTURED_MATERIAL_NOT_FOUND" not in peripheral_source
    assert "peripheral_store._structured_table_options" not in template_source
    assert "DEFAULT_EXCEL_TEMPLATE_TABLE_OPTIONS" in template_source
    assert "PeripheralStore" not in peripheral_source
