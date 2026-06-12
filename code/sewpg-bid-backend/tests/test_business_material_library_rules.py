from __future__ import annotations

import json
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.bid_type import BUSINESS_BID_TYPE, GENERAL_BID_TYPE, TECHNICAL_BID_TYPE
from app.services.material_store import material_store
from app.services.material_folder_scope import (
    business_customized_child_tier_for_parent_folder_path,
    business_customized_subfolder_specs,
    business_customized_tier_from_folder_path,
    business_standard_subfolder_specs,
    build_raw_material_permissions,
    canonical_raw_folder_metadata,
    infer_material_tier_from_folder,
    is_raw_folder_move_descendant_target,
    is_raw_folder_move_protected_path,
    normalize_material_bid_type,
    project_material_root_path,
    raw_material_tier_folder_specs,
)
from app.services.material_move_metadata import (
    RAW_MOVE_FILE_ACTION,
    build_raw_move_file_ext_fields,
    build_raw_move_folder_file_ext_fields,
)
from app.services.material_raw_file_filter import (
    build_raw_files_payload,
    raw_file_matches_bid_type,
    raw_file_matches_scope,
    raw_folder_matches_bid_type,
)
from app.services.material_raw_tree import build_raw_tree_payload
from app.services.material_taxonomy import (
    BUSINESS_CUSTOMIZED_SUBFOLDERS,
    MATERIAL_LIBRARY_ALLOWED_SUFFIXES,
    RAW_MATERIAL_PROTECTED_FOLDER_PATHS,
    business_customized_child_tier_for_parent_path,
    business_customized_tier_from_path,
    clean_status_for_new_file,
    ext_of,
    is_raw_material_protected_folder_path,
    material_suffix,
)
from app.services.material_tags import normalize_material_tags
from app.services.material_upload_metadata import (
    build_raw_upload_existing_ext_fields,
    build_raw_upload_ext_fields,
    build_raw_upload_record_ext_fields,
)
from app.services.material_upload_target import (
    build_raw_upload_target_plan,
    resolve_raw_upload_canonical_target,
)
from app.services.material_update_metadata import build_raw_update_file_ext_fields
from app.services.material_wiki_import import (
    build_generated_wiki_root_spec,
    generated_wiki_import_message,
    normalize_wiki_import_mode,
    wiki_import_node_bid_types,
    wiki_import_node_markdown,
    wiki_import_node_tags,
    wiki_import_node_title,
)
from app.services.material_wiki_attachment_operations import wiki_doc_matches_bid_type
from app.services.material_wiki_tree import build_wiki_tree_context
from app.services.material_wiki_scope import wiki_node_bid_types, wiki_root_bid_type, wiki_root_visible_for_bid_type
from app.services.peripheral import PeripheralError


class _FakePerformanceResult:
    def __init__(self, row: dict | None = None, *, rows: list[dict] | None = None, scalar: int | None = None) -> None:
        self.row = row
        self.rows = rows
        self.scalar = scalar

    def first(self):
        if self.row is None:
            return None
        return SimpleNamespace(_mapping=self.row)

    def scalar_one(self):
        return self.scalar if self.scalar is not None else 0

    def __iter__(self):
        return iter([SimpleNamespace(_mapping=row) for row in (self.rows if self.rows is not None else [])])


class _FakePerformanceSession:
    def __init__(
        self,
        row: dict | None = None,
        *,
        rows: list[dict] | None = None,
        scalar: int | None = None,
        results: list[_FakePerformanceResult] | None = None,
    ) -> None:
        self.row = row
        self.rows = rows
        self.scalar = scalar
        self.results = list(results or [])
        self.statements: list[str] = []
        self.params: list[dict] = []
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, statement, params=None):
        self.statements.append(str(statement))
        self.params.append(dict(params or {}))
        if self.results:
            return self.results.pop(0)
        return _FakePerformanceResult(self.row, rows=self.rows, scalar=self.scalar)

    async def commit(self):
        self.committed = True


class BusinessMaterialLibraryRulesTests(unittest.TestCase):
    def test_image_files_are_marked_original_only(self) -> None:
        status, message = clean_status_for_new_file("机型认证证书.png")
        self.assertEqual(status, "original_only")
        self.assertIn("原件", message)

    def test_cleanable_documents_still_queue_cleaning(self) -> None:
        status, message = clean_status_for_new_file("授权书.docx")
        self.assertEqual(status, "pending")
        self.assertIn("清洗", message)

    def test_existing_business_customer_project_paths_are_detected_for_backfill(self) -> None:
        self.assertEqual(
            business_customized_tier_from_path("商务标/客户素材/华能集团"),
            "customer",
        )
        self.assertEqual(
            business_customized_tier_from_path("商务标/项目素材/MAT-BIZ-HN-001"),
            "project",
        )
        self.assertEqual(
            business_customized_tier_from_path("商务标/客户素材/华能集团/客户关系与专项证明"),
            "",
        )

    def test_manual_customer_project_folder_creation_under_business_roots_gets_subfolders(self) -> None:
        self.assertEqual(
            business_customized_child_tier_for_parent_path("商务标/客户素材"),
            "customer",
        )
        self.assertEqual(
            business_customized_child_tier_for_parent_path("商务标/项目素材"),
            "project",
        )
        self.assertEqual(
            business_customized_child_tier_for_parent_path("技术标/客户素材"),
            "",
        )

    def test_business_customized_subfolder_specs_remain_three_modules(self) -> None:
        self.assertEqual(
            [item["name"] for item in BUSINESS_CUSTOMIZED_SUBFOLDERS],
            [
                "客户准入与专项证明",
                "客户专用响应口径",
                "客户模板与历史文件",
            ],
        )

    def test_material_library_whitelist_includes_images_without_touching_parse_whitelist(self) -> None:
        for suffix in [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"]:
            self.assertIn(suffix, MATERIAL_LIBRARY_ALLOWED_SUFFIXES)

    def test_ds_store_is_allowed_as_original_only_material(self) -> None:
        self.assertEqual(material_suffix(".DS_Store"), ".ds_store")
        self.assertEqual(ext_of(".DS_Store"), "ds_store")
        self.assertIn(".ds_store", MATERIAL_LIBRARY_ALLOWED_SUFFIXES)
        status, message = clean_status_for_new_file(".DS_Store")
        self.assertEqual(status, "original_only")
        self.assertIn("DS_Store", message)

    def test_material_cleaning_uses_short_paths_for_long_names(self) -> None:
        from app.services.material_cleaning import _short_file_name_for_path, cleaned_object_key

        long_name = (
            "【标段一】华能蒙东新能源公司赤峰市200万千瓦自建调峰能力风光储多能互补一体化+荒漠治理基地项目"
            "（翁牛特旗120万千瓦风电项目区）风力发电机组（不含塔筒）及附属设备采购文件.docx"
        )
        short_name = _short_file_name_for_path(long_name)
        key = cleaned_object_key(95, long_name)

        self.assertTrue(short_name.endswith(".docx"))
        self.assertLessEqual(len(short_name.encode("utf-8")), 96)
        self.assertIn("cleaned/RAW-0095/", key)
        self.assertLessEqual(max(len(part.encode("utf-8")) for part in key.split("/")), 120)

    def test_business_upload_metadata_sets_business_kind_and_identity(self) -> None:
        ext, clean_status = build_raw_upload_ext_fields(
            file_name="授权委托书.docx",
            folder_path="商务标/客户素材/华能集团/客户专用商务响应文件",
            folder_tier="customer",
            requested_bid_type="商务标",
            business_material_kind="fixed",
            customer_id="CUST-HN",
            source_minio_bucket="bid-materials",
            source_minio_key="raw/business.docx",
            clean_updated_at="2026-05-24T00:00:00Z",
            tags=["资质", "授权书", "资质"],
        )

        self.assertEqual(clean_status, "pending")
        self.assertEqual(ext["bidType"], "商务标")
        self.assertEqual(ext["materialTier"], "customer")
        self.assertEqual(ext["businessMaterialKind"], "fixed")
        self.assertEqual(ext["materialCategory"], "customer_response")
        self.assertEqual(ext["materialCategoryLabel"], "客户专用响应口径")
        self.assertEqual(ext["customerId"], "CUST-HN")
        self.assertEqual(ext["customerName"], "华能集团")
        self.assertEqual(ext["cleanUpdatedAt"], "2026-05-24T00:00:00Z")
        self.assertEqual(ext["tags"], ["资质", "授权书"])

    def test_material_tags_normalize_arrays_json_and_delimited_text(self) -> None:
        self.assertEqual(normalize_material_tags(["资质", " 资质 ", "承诺函"]), ["资质", "承诺函"])
        self.assertEqual(normalize_material_tags(["资质，承诺函", "授权书;报价"]), ["资质", "承诺函", "授权书", "报价"])
        self.assertEqual(normalize_material_tags('["报价", "商务附件", "报价"]'), ["报价", "商务附件"])
        self.assertEqual(normalize_material_tags("业绩，资格; 授权书\n承诺函"), ["业绩", "资格", "授权书", "承诺函"])

    def test_technical_upload_metadata_adds_turbine_hint_without_business_kind(self) -> None:
        ext, clean_status = build_raw_upload_ext_fields(
            file_name="EW10.0-220下置 技术方案.docx",
            folder_path="技术标/通用素材",
            folder_tier="standard",
            requested_bid_type="技术标",
            source_minio_bucket="bid-materials",
            source_minio_key="raw/technical.docx",
            clean_updated_at="2026-05-24T00:00:00Z",
        )

        self.assertEqual(clean_status, "pending")
        self.assertEqual(ext["bidType"], "技术标")
        self.assertEqual(ext["materialTier"], "standard")
        self.assertEqual(ext["customerName"], "平台标准")
        self.assertEqual(ext["turbineModel"], "EW10.0-220")
        self.assertNotIn("businessMaterialKind", ext)

    def test_unscoped_upload_metadata_does_not_default_to_technical_bid(self) -> None:
        ext, clean_status = build_raw_upload_ext_fields(
            file_name="平台授权模板.docx",
            folder_path="通用素材",
            folder_tier="standard",
            requested_bid_type="",
            source_minio_bucket="bid-materials",
            source_minio_key="raw/common.docx",
            clean_updated_at="2026-05-24T00:00:00Z",
        )

        self.assertEqual(clean_status, "pending")
        self.assertEqual(ext["bidType"], GENERAL_BID_TYPE)
        self.assertEqual(ext["materialTier"], "standard")

    def test_raw_upload_action_metadata_is_built_outside_store(self) -> None:
        record_ext = build_raw_upload_record_ext_fields({"bidType": "商务标"})
        existing_ext = build_raw_upload_existing_ext_fields(
            {"bidType": "技术标", "old": True},
            {"bidType": "商务标", "new": True},
            last_action="version",
        )

        self.assertEqual(record_ext["lastAction"], "upload")
        self.assertEqual(record_ext["lastOperator"], "当前用户")
        self.assertEqual(existing_ext["lastAction"], "version")
        self.assertEqual(existing_ext["lastOperator"], "当前用户")
        self.assertEqual(existing_ext["bidType"], "商务标")
        self.assertTrue(existing_ext["old"])
        self.assertTrue(existing_ext["new"])

    def test_raw_upload_target_plan_handles_auto_project_target(self) -> None:
        plan = build_raw_upload_target_plan(
            target_path="",
            project_id="BIZ-001",
            bid_type="商务标",
        )

        self.assertEqual(plan["mode"], "auto")
        self.assertEqual(plan["bidType"], "商务标")
        self.assertEqual(plan["materialTier"], "project")
        self.assertEqual(plan["projectId"], "BIZ-001")

    def test_raw_upload_target_plan_requires_explicit_bid_type(self) -> None:
        plan = build_raw_upload_target_plan(
            target_path="",
            project_id="BIZ-001",
            bid_type="",
        )

        self.assertEqual(plan["mode"], "error")
        self.assertEqual(plan["code"], "BID_TYPE_REQUIRED")
        self.assertEqual(plan["bidType"], "")

    def test_raw_upload_target_plan_infers_business_customer_subfolder(self) -> None:
        plan = build_raw_upload_target_plan(
            target_path="商务标/客户素材/华能集团/客户关系与专项证明",
            bid_type="商务标",
        )

        self.assertEqual(plan["mode"], "scoped-path")
        self.assertEqual(plan["materialTier"], "customer")
        self.assertEqual(plan["customerName"], "华能集团")
        self.assertEqual(plan["requestedPath"], "商务标/客户素材/华能集团/客户关系与专项证明")

    def test_raw_upload_target_plan_keeps_legacy_customer_aliases_canonicalizable(self) -> None:
        plan = build_raw_upload_target_plan(
            target_path="客户素材/华能集团",
            bid_type="商务标",
        )

        self.assertEqual(plan["mode"], "tier-root")
        self.assertEqual(plan["materialTier"], "customer")
        self.assertEqual(plan["customerName"], "华能集团")

    def test_raw_upload_canonical_target_resolution(self) -> None:
        self.assertEqual(
            resolve_raw_upload_canonical_target(
                "商务标/项目素材/BIZ-001/项目商务响应文件",
                "商务标/项目素材/BIZ-001",
            ),
            {"mode": "nested", "relativeDir": "项目商务响应文件"},
        )
        self.assertEqual(
            resolve_raw_upload_canonical_target("客户素材/华能集团", "商务标/客户素材/华能集团")["mode"],
            "canonical",
        )
        self.assertEqual(
            resolve_raw_upload_canonical_target("技术标/不存在/子目录", "技术标/客户素材/华能集团")["mode"],
            "not-found",
        )

    def test_wiki_root_scope_rules_split_business_and_technical_roots(self) -> None:
        self.assertEqual(wiki_root_bid_type("商务标Wiki（自动生成）"), "商务标")
        self.assertEqual(wiki_root_bid_type("技术标Wiki（自动生成）"), "技术标")

        self.assertTrue(
            wiki_root_visible_for_bid_type(
                title="技术标Wiki（自动生成）",
                bid_types=["技术标"],
                bid_type="技术标",
            )
        )
        self.assertFalse(
            wiki_root_visible_for_bid_type(
                title="商务标Wiki（自动生成）",
                bid_types=["商务标"],
                bid_type="技术标",
            )
        )
        self.assertFalse(
            wiki_root_visible_for_bid_type(
                title="平台级Wiki（自动生成）",
                bid_types=["技术标", "商务标"],
                bid_type="商务标",
            )
        )
        self.assertTrue(
            wiki_root_visible_for_bid_type(
                title="商务资料卡片",
                bid_types=["商务标"],
                bid_type="商务标",
            )
        )
        self.assertFalse(
            wiki_root_visible_for_bid_type(
                title="混合资料卡片",
                bid_types=["技术标", "商务标"],
                bid_type="商务标",
            )
        )

    def test_wiki_node_bid_types_inherit_parent_or_default_to_scope(self) -> None:
        self.assertEqual(wiki_node_bid_types(parent_bid_types=["商务标"], bid_type="技术标"), ["商务标"])
        self.assertEqual(wiki_node_bid_types(bid_type="技术标"), ["技术标"])
        self.assertEqual(wiki_node_bid_types(bid_type="未知"), ["通用"])

    def test_wiki_tree_context_filters_roots_and_preserves_selected_order(self) -> None:
        tech_root = SimpleNamespace(id=1, parent_id=None, title="技术标Wiki", bid_types=["技术标"])
        tech_child = SimpleNamespace(id=2, parent_id=1, title="技术方案", bid_types=["技术标"])
        business_root = SimpleNamespace(id=3, parent_id=None, title="商务标Wiki", bid_types=["商务标"])
        business_child = SimpleNamespace(id=4, parent_id=3, title="资质证明", bid_types=["商务标"])

        context = build_wiki_tree_context(
            all_nodes=[tech_root, tech_child, business_root, business_child],
            node_id="WIKI-0004",
            bid_type="商务标",
        )

        self.assertEqual(context["normalizedBidType"], "商务标")
        self.assertEqual(context["tree"][0]["id"], "WIKI-0003")
        self.assertEqual(context["tree"][0]["children"][0]["id"], "WIKI-0004")
        self.assertEqual(context["selectedNodeIds"], [4, 3])
        self.assertEqual(context["visibleNodeIds"], {3, 4})

    def test_generated_wiki_import_rules_build_scoped_root_and_defaults(self) -> None:
        root_spec = build_generated_wiki_root_spec(
            root_title="商务标Wiki（自动生成）",
            nodes=[{"title": "资质库"}],
        )

        self.assertEqual(normalize_wiki_import_mode("bad-mode"), "create")
        self.assertEqual(root_spec["tags"], ["商务标", "素材库"])
        self.assertEqual(root_spec["applicableTypes"], ["商务标"])
        self.assertEqual(root_spec["children"][0]["title"], "资质库")
        self.assertEqual(generated_wiki_import_message(root_spec["title"], "refreshed"), "商务标 Wiki 已刷新，并已替换自动生成节点。")
        self.assertEqual(wiki_import_node_title({"title": "A/B"}), "A-B")
        self.assertEqual(wiki_import_node_markdown({}, "默认节点"), "# 默认节点\n")
        self.assertEqual(wiki_import_node_tags({}, ["旧标签"]), ["旧标签"])
        self.assertEqual(wiki_import_node_bid_types({}, ["技术标"]), ["技术标"])

    def test_wiki_attachment_scope_allows_common_docs_and_rejects_opposite_bid(self) -> None:
        business_doc = SimpleNamespace(node=SimpleNamespace(bid_types=["商务标"]))
        common_doc = SimpleNamespace(node=SimpleNamespace(bid_types=["通用"]))

        self.assertTrue(wiki_doc_matches_bid_type(business_doc, "商务标"))
        self.assertFalse(wiki_doc_matches_bid_type(business_doc, "技术标"))
        self.assertTrue(wiki_doc_matches_bid_type(common_doc, "商务标"))
        self.assertTrue(wiki_doc_matches_bid_type(common_doc, "技术标"))
        self.assertFalse(wiki_doc_matches_bid_type(common_doc, ""))

    def test_raw_folder_scope_rules_describe_bid_roots_and_legacy_paths(self) -> None:
        self.assertEqual(project_material_root_path("商务标", "BIZ-001"), "商务标/项目素材/BIZ-001")
        self.assertEqual(
            [item["name"] for item in raw_material_tier_folder_specs("技术标")],
            ["通用素材", "客户素材", "项目素材"],
        )
        self.assertEqual(normalize_material_bid_type(""), "")
        with self.assertRaises(ValueError):
            raw_material_tier_folder_specs("")
        with self.assertRaises(ValueError):
            project_material_root_path("", "LEGACY-001")
        self.assertEqual(
            infer_material_tier_from_folder(tier="", path="商务标/客户素材/华能集团"),
            "customer",
        )
        self.assertEqual(
            canonical_raw_folder_metadata("客户素材/华能集团/技术标")["bidType"],
            "技术标",
        )
        self.assertEqual(
            canonical_raw_folder_metadata("项目素材/LEGACY-COMMON-001")["bidType"],
            GENERAL_BID_TYPE,
        )
        self.assertEqual(
            canonical_raw_folder_metadata("商务标/项目素材/BIZ-001")["projectId"],
            "BIZ-001",
        )

    def test_raw_permission_rules_cover_both_bid_roots(self) -> None:
        payload = build_raw_material_permissions("admin")

        self.assertEqual(payload["role"], "admin")
        self.assertEqual([item["pathPrefix"] for item in payload["rules"]], ["技术标", "商务标"])
        self.assertEqual([item["label"] for item in payload["rules"]], ["技术标素材", "商务标素材"])
        self.assertTrue(payload["rules"][0]["actions"]["upload"])
        self.assertTrue(payload["rules"][1]["actions"]["delete"])

    def test_raw_tree_payload_counts_direct_and_nested_files(self) -> None:
        root = SimpleNamespace(id=1, parent_id=None, name="技术标", path="技术标")
        child = SimpleNamespace(id=2, parent_id=1, name="通用素材", path="技术标/通用素材")
        business_root = SimpleNamespace(id=3, parent_id=None, name="商务标", path="商务标")
        payload = build_raw_tree_payload(
            root_folders=[
                SimpleNamespace(id=99, parent_id=None, name="旧技术标", path="技术标"),
                business_root,
            ],
            all_folders=[root, child, business_root],
            all_files=[
                SimpleNamespace(folder_id=1),
                SimpleNamespace(folder_id=2),
                SimpleNamespace(folder_id=2),
            ],
            bid_type=TECHNICAL_BID_TYPE,
            updated_at="2026-05-24 12:00:00",
        )

        self.assertEqual(payload["updatedAt"], "2026-05-24 12:00:00")
        self.assertEqual([item["name"] for item in payload["tree"]], ["技术标"])
        self.assertEqual(payload["tree"][0]["name"], "技术标")
        self.assertEqual(payload["tree"][0]["directFileCount"], 1)
        self.assertEqual(payload["tree"][0]["fileCount"], 3)
        self.assertEqual(payload["tree"][0]["children"][0]["directFileCount"], 2)
        self.assertEqual(payload["tree"][0]["children"][0]["fileCount"], 2)

    def test_business_folder_scope_rules_describe_standard_and_customized_children(self) -> None:
        standard_specs = business_standard_subfolder_specs("平台标准")
        self.assertEqual(standard_specs[0]["name"], "资格审查与基础证明")
        self.assertEqual(standard_specs[0]["bidType"], "商务标")
        self.assertEqual(standard_specs[0]["customerName"], "平台标准")
        self.assertEqual(standard_specs[0]["materialCategory"], "qualification_evidence")
        self.assertEqual(
            [item["name"] for item in standard_specs],
            ["资格审查与基础证明", "财务信用与合规声明", "制造商与供应链材料", "机型认证与测试报告", "企业能力与供货业绩", "表单模板与过程稿"],
        )

        customized_specs = business_customized_subfolder_specs(
            tier="project",
            project_id="BIZ-001",
            customer_name="华能集团",
        )
        self.assertEqual(customized_specs[0]["tier"], "project")
        self.assertEqual(customized_specs[0]["bidType"], "商务标")
        self.assertEqual(customized_specs[0]["projectId"], "BIZ-001")
        self.assertEqual(customized_specs[0]["customerName"], "华能集团")
        self.assertEqual(
            business_customized_tier_from_folder_path("商务标/客户素材/华能集团"),
            "customer",
        )
        self.assertEqual(
            business_customized_child_tier_for_parent_folder_path("商务标/项目素材"),
            "project",
        )

    def test_raw_move_metadata_preserves_action_and_updates_scope(self) -> None:
        ext = build_raw_move_file_ext_fields(
            {"lastAction": "version", "projectId": "OLD", "bidType": "技术标"},
            source_minio_key="raw/商务标/客户素材/华能集团/授权书.docx",
            source_file_name="授权书.docx",
            material_tier="customer",
            destination_bid_type="商务标",
            destination_project_id="",
            destination_customer_name="华能集团",
        )

        self.assertEqual(ext["lastAction"], "version")
        self.assertEqual(ext["bidType"], "商务标")
        self.assertEqual(ext["projectId"], "OLD")
        self.assertEqual(ext["customerName"], "华能集团")
        self.assertEqual(ext["materialTierLabel"], "客户素材")

    def test_raw_move_metadata_can_set_file_move_action(self) -> None:
        ext = build_raw_move_file_ext_fields(
            {"projectId": "OLD"},
            source_minio_key="raw/商务标/客户素材/华能集团/授权书.docx",
            source_file_name="授权书.docx",
            material_tier="customer",
            destination_bid_type="商务标",
            destination_customer_name="华能集团",
            last_action=RAW_MOVE_FILE_ACTION,
        )

        self.assertEqual(ext["lastAction"], "move")
        self.assertEqual(ext["lastOperator"], "当前用户")

    def test_raw_move_folder_metadata_sets_folder_move_action(self) -> None:
        ext = build_raw_move_folder_file_ext_fields(
            {"lastAction": "upload", "projectId": "OLD"},
            source_minio_key="raw/商务标/项目素材/BIZ-001/报价.xlsx",
            source_file_name="报价.xlsx",
            material_tier="project",
            destination_bid_type="商务标",
            destination_project_id="BIZ-001",
        )

        self.assertEqual(ext["lastAction"], "move-folder")
        self.assertEqual(ext["lastOperator"], "当前用户")
        self.assertEqual(ext["bidType"], "商务标")
        self.assertEqual(ext["projectId"], "BIZ-001")

    def test_raw_folder_move_scope_rules_protect_roots_and_descendants(self) -> None:
        self.assertTrue(is_raw_folder_move_protected_path("技术标"))
        self.assertTrue(is_raw_folder_move_protected_path("商务标"))
        self.assertTrue(is_raw_folder_move_protected_path("商务标/通用素材"))
        self.assertTrue(is_raw_folder_move_protected_path("商务标/客户素材"))
        self.assertTrue(is_raw_folder_move_protected_path("商务标/项目素材"))
        self.assertTrue(is_raw_folder_move_protected_path("商务标/客户素材/华能集团"))
        self.assertTrue(is_raw_folder_move_protected_path("商务标/项目素材/BIZ-001"))
        self.assertTrue(is_raw_folder_move_protected_path("商务标/客户素材/华能集团/客户专用响应口径"))
        self.assertTrue(is_raw_folder_move_protected_path("商务标/客户素材/华能集团/客户专用商务响应文件"))
        self.assertFalse(is_raw_folder_move_protected_path("商务标/客户素材/华能集团/临时目录"))
        self.assertTrue(
            is_raw_folder_move_descendant_target(
                "商务标/客户素材/华能集团",
                "商务标/客户素材/华能集团/子目录",
            )
        )
        self.assertFalse(
            is_raw_folder_move_descendant_target(
                "商务标/客户素材/华能集团",
                "商务标/项目素材/BIZ-001",
            )
        )

    def test_raw_update_metadata_renames_and_updates_business_kind(self) -> None:
        ext = build_raw_update_file_ext_fields(
            {"bidType": "商务标", "businessMaterialKind": "other"},
            source_minio_key="raw/商务标/通用素材/授权书.docx",
            source_file_name="授权书.docx",
            business_material_kind="固定素材",
        )

        self.assertEqual(ext["sourceFileName"], "授权书.docx")
        self.assertEqual(ext["sourceMinioKey"], "raw/商务标/通用素材/授权书.docx")
        self.assertEqual(ext["businessMaterialKind"], "fixed")
        self.assertEqual(ext["businessMaterialKindLabel"], "固定素材")
        self.assertEqual(ext["lastAction"], "update")

    def test_raw_update_metadata_updates_and_clears_tags(self) -> None:
        ext = build_raw_update_file_ext_fields(
            {"bidType": "商务标", "tags": ["旧标签"]},
            source_minio_key="raw/商务标/通用素材/授权书.docx",
            source_file_name="授权书.docx",
            tags="资质，承诺函，资质",
            update_tags=True,
        )
        cleared = build_raw_update_file_ext_fields(
            ext,
            source_minio_key="raw/商务标/通用素材/授权书.docx",
            source_file_name="授权书.docx",
            tags=[],
            update_tags=True,
        )

        self.assertEqual(ext["tags"], ["资质", "承诺函"])
        self.assertEqual(ext["lastAction"], "update")
        self.assertEqual(cleared["tags"], [])

    def test_raw_update_metadata_keeps_technical_updates_as_rename(self) -> None:
        ext = build_raw_update_file_ext_fields(
            {"bidType": "技术标"},
            source_minio_key="raw/技术标/通用素材/方案.docx",
            source_file_name="方案.docx",
            business_material_kind="固定素材",
        )

        self.assertEqual(ext["lastAction"], "rename")
        self.assertNotIn("businessMaterialKind", ext)

    def test_raw_file_filter_keeps_bid_scope_and_pagination_together(self) -> None:
        items = [
            SimpleNamespace(
                ext_fields={"bidType": "商务标", "materialTier": "standard", "cleanStatus": "cleaned"},
                folder=SimpleNamespace(tier="standard"),
                to_dict=lambda: {"id": "RAW-BIZ"},
            ),
            SimpleNamespace(
                ext_fields={"bidType": "技术标", "materialTier": "standard", "cleanStatus": "cleaned"},
                folder=SimpleNamespace(tier="standard"),
                to_dict=lambda: {"id": "RAW-TECH"},
            ),
            SimpleNamespace(
                ext_fields={"bidType": "通用", "materialTier": "standard", "cleanStatus": "cleaned"},
                folder=SimpleNamespace(tier="standard"),
                to_dict=lambda: {"id": "RAW-COMMON"},
            ),
        ]

        payload = build_raw_files_payload(
            items,
            bid_type="商务标",
            material_tier="standard",
            clean_status="cleaned",
            page=2,
            page_size=1,
        )

        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["items"], [{"id": "RAW-COMMON"}])
        self.assertEqual(payload["page"], 2)
        self.assertEqual(payload["pageSize"], 1)

    def test_raw_file_filter_supports_title_and_tag_options(self) -> None:
        items = [
            SimpleNamespace(
                name="质量专题更新20240729.docx",
                ext_fields={"bidType": "商务标", "materialTier": "standard", "tags": ["资质", "质量"]},
                folder=SimpleNamespace(tier="standard"),
                to_dict=lambda: {"id": "RAW-QUALITY"},
            ),
            SimpleNamespace(
                name="财务审计报告.docx",
                ext_fields={"bidType": "商务标", "materialTier": "standard", "tags": ["财务"]},
                folder=SimpleNamespace(tier="standard"),
                to_dict=lambda: {"id": "RAW-FINANCE"},
            ),
            SimpleNamespace(
                name="质量体系证书.docx",
                ext_fields={"bidType": "商务标", "materialTier": "standard", "tags": ["资质"]},
                folder=SimpleNamespace(tier="standard"),
                to_dict=lambda: {"id": "RAW-CERT"},
            ),
        ]

        payload = build_raw_files_payload(
            items,
            bid_type="商务标",
            title="质量",
            tag=["资质"],
            page=1,
            page_size=20,
        )

        self.assertEqual(payload["items"], [{"id": "RAW-QUALITY"}, {"id": "RAW-CERT"}])
        self.assertEqual(payload["tagOptions"], ["资质", "质量"])
        self.assertEqual(payload["total"], 2)

        multi_tag_payload = build_raw_files_payload(
            items,
            bid_type="商务标",
            title="质量",
            tag=["资质", "质量"],
            page=1,
            page_size=20,
        )

        self.assertEqual(multi_tag_payload["items"], [{"id": "RAW-QUALITY"}])
        self.assertEqual(multi_tag_payload["total"], 1)

    def test_raw_file_filter_applies_project_customer_tier_and_clean_status(self) -> None:
        item = SimpleNamespace(
            ext_fields={
                "bidType": "商务标",
                "materialTier": "project",
                "cleanStatus": "cleaned",
                "projectId": "BIZ-001",
                "projectCode": "BIZ-001",
                "customerCanonicalName": "华能集团",
            },
            folder=SimpleNamespace(tier="project"),
        )

        self.assertTrue(
            raw_file_matches_scope(
                item,
                bid_type="商务标",
                project_id="BIZ-001",
                customer_name="华能集团",
                material_tier="project",
                clean_status="cleaned",
            )
        )
        self.assertFalse(raw_file_matches_scope(item, bid_type="技术标"))
        self.assertFalse(raw_file_matches_scope(item, bid_type="商务标", material_tier="standard"))
        self.assertFalse(raw_file_matches_scope(item, bid_type="商务标", clean_status="pending"))

    def test_raw_file_bid_scope_allows_common_materials_and_rejects_opposite_bid(self) -> None:
        business_item = SimpleNamespace(
            ext_fields={"bidType": "商务标"},
            folder=SimpleNamespace(path="商务标/通用素材", bid_type="商务标"),
        )
        common_item = SimpleNamespace(
            ext_fields={"bidType": "通用"},
            folder=SimpleNamespace(path="技术标/通用素材", bid_type="技术标"),
        )
        legacy_item = SimpleNamespace(
            ext_fields={},
            folder=SimpleNamespace(path="商务标/通用素材", bid_type=""),
        )

        self.assertTrue(raw_file_matches_bid_type(business_item, "商务标"))
        self.assertFalse(raw_file_matches_bid_type(business_item, "技术标"))
        self.assertTrue(raw_file_matches_bid_type(common_item, "商务标"))
        self.assertTrue(raw_file_matches_bid_type(legacy_item, "商务标"))
        self.assertFalse(raw_file_matches_bid_type(legacy_item, "技术标"))
        self.assertTrue(raw_folder_matches_bid_type(SimpleNamespace(path="商务标/通用素材", bid_type=""), "商务标"))
        self.assertFalse(raw_folder_matches_bid_type(SimpleNamespace(path="商务标/通用素材", bid_type=""), "技术标"))


class RawMaterialProtectedFolderTests(unittest.IsolatedAsyncioTestCase):
    async def test_technical_tier_roots_can_be_deleted_but_business_tier_roots_are_protected(self) -> None:
        expected_deletable = {
            "技术标/通用素材",
            "技术标/客户素材",
            "技术标/项目素材",
        }

        for folder_path in expected_deletable:
            self.assertNotIn(folder_path, RAW_MATERIAL_PROTECTED_FOLDER_PATHS)
            self.assertFalse(is_raw_material_protected_folder_path(folder_path))

        for folder_path in {"技术标", "商务标", "商务标/通用素材", "商务标/客户素材", "商务标/项目素材"}:
            self.assertIn(folder_path, RAW_MATERIAL_PROTECTED_FOLDER_PATHS)
            self.assertTrue(is_raw_material_protected_folder_path(folder_path))

    async def test_auto_bootstrapped_business_folders_cannot_be_deleted(self) -> None:
        expected_static_paths = {
            "商务标/通用素材",
            "商务标/客户素材",
            "商务标/项目素材",
            "商务标/通用素材/资格审查与基础证明",
            "商务标/通用素材/财务信用与合规声明",
            "商务标/通用素材/制造商与供应链材料",
            "商务标/通用素材/机型认证与测试报告",
            "商务标/通用素材/企业能力与供货业绩",
            "商务标/通用素材/表单模板与过程稿",
        }
        self.assertTrue(expected_static_paths.issubset(RAW_MATERIAL_PROTECTED_FOLDER_PATHS))
        self.assertTrue(is_raw_material_protected_folder_path("商务标/通用素材/专题证书库/机型认证证书"))
        self.assertTrue(is_raw_material_protected_folder_path("商务标/通用素材/通用模板底稿库"))

        dynamic_paths = {
            "商务标/客户素材/华能集团",
            "商务标/客户素材/华能集团/客户准入与专项证明",
            "商务标/客户素材/华能集团/客户专用响应口径",
            "商务标/客户素材/华能集团/客户模板与历史文件",
            "商务标/项目素材/MAT-BIZ-HN-001",
            "商务标/项目素材/MAT-BIZ-HN-001/招标要求与专项证明",
            "商务标/项目素材/MAT-BIZ-HN-001/资格审查与商务响应成册",
            "商务标/项目素材/MAT-BIZ-HN-001/项目过程稿与澄清文件",
        }
        for folder_path in expected_static_paths | dynamic_paths:
            self.assertTrue(is_raw_material_protected_folder_path(folder_path))
            with self.assertRaises(PeripheralError) as context:
                await material_store.raw_delete_folder(folder_path, bid_type=BUSINESS_BID_TYPE)
            self.assertEqual(context.exception.code, "RAW_FOLDER_DELETE_PROTECTED")

        self.assertFalse(is_raw_material_protected_folder_path("商务标/客户素材/华能集团/临时目录"))
        self.assertFalse(is_raw_material_protected_folder_path("商务标/客户素材/华能集团/资格审查与商务响应成册"))
        self.assertFalse(is_raw_material_protected_folder_path("商务标/项目素材/MAT-BIZ-HN-001/客户专用响应口径"))


class BusinessPerformanceLibraryTests(unittest.IsolatedAsyncioTestCase):
    def _performance_row(self, **overrides) -> dict:
        row = {
            "id": 7,
            "name": "华能风电业绩",
            "customer_name": "华能集团",
            "project_type": "风电项目",
            "scale": "100MW",
            "location": "内蒙古",
            "started_at": "2024-01",
            "completed_at": "2024-12",
            "amount": "1200万",
            "turbine_model": "EW6.25",
            "tags": ["业绩"],
            "applicable_bid_types": ["商务标"],
            "scope": "customer",
            "word_object_key": "performance/PERF-0007/业绩.docx",
            "word_file_name": "业绩.docx",
            "word_size_bytes": 128,
            "word_mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "cleaned_object_key": "",
            "review_status": "reviewed",
            "created_at": None,
            "updated_at": None,
        }
        row.update(overrides)
        return row

    async def test_performance_list_filters_disabled_records_by_default(self) -> None:
        from app.services.performance_library_service import PerformanceLibraryService

        session = _FakePerformanceSession(
            results=[
                _FakePerformanceResult(scalar=1),
                _FakePerformanceResult(rows=[self._performance_row()]),
            ]
        )
        with patch("app.services.performance_library_service.async_session", return_value=session), patch(
            "app.services.performance_library_service.ensure_material_runtime_tables", new=AsyncMock()
        ):
            payload = await PerformanceLibraryService().list_records(page=1, page_size=20)

        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["id"], "PERF-0007")
        self.assertIn("review_status <> 'disabled'", session.statements[0])
        self.assertIn("review_status <> 'disabled'", session.statements[1])

    async def test_performance_create_and_update_normalize_payload_fields(self) -> None:
        from app.services.performance_library_service import PerformanceLibraryService

        service = PerformanceLibraryService()
        create_session = _FakePerformanceSession(row=self._performance_row(tags=["业绩", "合同"], applicable_bid_types=["商务标"]))
        update_session = _FakePerformanceSession(row=self._performance_row(tags=["业绩", "中标"], applicable_bid_types=["商务标", "技术标"]))
        with patch("app.services.performance_library_service.ensure_material_runtime_tables", new=AsyncMock()):
            with patch("app.services.performance_library_service.async_session", return_value=create_session):
                created = await service.create_record(
                    {
                        "name": " 华能风电业绩 ",
                        "customerName": "华能集团",
                        "tags": "业绩，合同，业绩",
                        "applicableBidTypes": ["商务标", "bad"],
                        "scope": "bad-scope",
                        "reviewStatus": "bad-status",
                    }
                )
            with patch("app.services.performance_library_service.async_session", return_value=update_session):
                updated = await service.update_record(
                    "PERF-0007",
                    {
                        "tags": ["业绩", "中标", "业绩"],
                        "applicableBidTypes": ["商务标", "技术标"],
                        "reviewStatus": "reviewed",
                    },
                )

        create_params = create_session.params[0]
        update_params = update_session.params[0]
        self.assertEqual(create_params["name"], "华能风电业绩")
        self.assertEqual(create_params["scope"], "standard")
        self.assertEqual(create_params["review_status"], "draft")
        self.assertEqual(json.loads(create_params["tags"]), ["业绩", "合同"])
        self.assertEqual(json.loads(create_params["applicable_bid_types"]), ["商务标"])
        self.assertIn("CAST(:tags AS JSONB)", update_session.statements[0])
        self.assertEqual(json.loads(update_params["tags"]), ["业绩", "中标"])
        self.assertEqual(json.loads(update_params["applicable_bid_types"]), ["商务标", "技术标"])
        self.assertEqual(created["item"]["name"], "华能风电业绩")
        self.assertEqual(updated["item"]["reviewStatus"], "reviewed")

    async def test_performance_delete_soft_disables_record_without_removing_word_object(self) -> None:
        from app.services.performance_library_service import PerformanceLibraryService

        session = _FakePerformanceSession(self._performance_row(review_status="disabled"))
        service = PerformanceLibraryService()

        with patch("app.services.performance_library_service.async_session", return_value=session), patch(
            "app.services.performance_library_service.ensure_material_runtime_tables", new=AsyncMock()
        ), patch("app.services.performance_library_service.minio_client.remove_object") as remove_object:
            result = await service.delete_record("PERF-0007")

        self.assertIn("停用", result["message"])
        self.assertEqual(result["item"]["reviewStatus"], "disabled")
        self.assertTrue(session.committed)
        self.assertIn("UPDATE performance_records", session.statements[0])
        self.assertIn("review_status = 'disabled'", session.statements[0])
        self.assertNotIn("DELETE FROM performance_records", session.statements[0])
        remove_object.assert_not_called()

    async def test_performance_word_upload_and_download_use_minio_payload(self) -> None:
        from app.services.performance_library_service import PerformanceLibraryService

        service = PerformanceLibraryService()
        upload = SimpleNamespace(
            filename='华能/业绩?.docx',
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            file=BytesIO(b"docx-bytes"),
        )
        upload_session = _FakePerformanceSession(row=self._performance_row(word_file_name="华能-业绩-.docx", word_size_bytes=10))

        with patch("app.services.performance_library_service.async_session", return_value=upload_session), patch(
            "app.services.performance_library_service.ensure_material_runtime_tables", new=AsyncMock()
        ), patch("app.services.performance_library_service.minio_client.put_object_stream") as put_object:
            result = await service.upload_word("PERF-0007", upload)

        put_object.assert_called_once()
        _bucket, object_key, _stream, size = put_object.call_args.args[:4]
        self.assertEqual(object_key, "performance/PERF-0007/华能-业绩-.docx")
        self.assertEqual(size, 10)
        self.assertEqual(upload_session.params[0]["word_file_name"], "华能-业绩-.docx")
        self.assertEqual(result["item"]["wordFileName"], "华能-业绩-.docx")

        with patch.object(service, "get_record", AsyncMock(return_value=result["item"])):
            payload = await service.download_word("PERF-0007")

        self.assertEqual(payload["key"], "performance/PERF-0007/业绩.docx")
        self.assertEqual(payload["fileName"], "华能-业绩-.docx")

    async def test_performance_match_candidates_filter_scope_and_shape_materials(self) -> None:
        from app.services.performance_library_service import PerformanceLibraryService

        rows = [
            self._performance_row(id=1, scope="standard", customer_name="平台标准", name="平台标准供货业绩"),
            self._performance_row(id=2, scope="customer", customer_name="华能集团", name="华能集团供货业绩"),
            self._performance_row(id=3, scope="customer", customer_name="大唐集团", name="大唐集团供货业绩"),
            self._performance_row(id=4, scope="project", customer_name="华能集团", name="MAT-001 项目供货业绩"),
            self._performance_row(id=5, scope="project", customer_name="华能集团", name="其他项目业绩"),
        ]
        session = _FakePerformanceSession(rows=rows)
        scope = {
            "identity": {"customerCanonicalName": "华能集团", "projectId": "MAT-001"},
            "readableScopes": [
                {"customerName": "华能集团"},
                {"projectId": "MAT-001"},
            ],
        }

        with patch("app.services.performance_library_service.async_session", return_value=session), patch(
            "app.services.performance_library_service.ensure_material_runtime_tables", new=AsyncMock()
        ):
            items = await PerformanceLibraryService().list_match_candidates(scope, limit=10)

        self.assertEqual([item["id"] for item in items], ["PERF-0001", "PERF-0002", "PERF-0004"])
        self.assertTrue(all(item["sourceType"] == "performance_library" for item in items))
        self.assertEqual(items[1]["businessMaterialKindLabel"], "共用业绩")
        self.assertIn("华能集团", items[1]["summary"])
        self.assertIn("业绩证明", items[1]["keywords"])
        self.assertIn("review_status <> 'disabled'", session.statements[0])

    async def test_business_material_index_includes_performance_candidates(self) -> None:
        from app.services import business_gap_planning

        material_scope = {
            "bidType": "商务标",
            "identity": {"customerCanonicalName": "华能集团", "projectId": "MAT-001"},
            "readableScopes": [{"path": "商务标/通用素材", "materialTier": "standard"}],
        }
        performance_candidate = {
            "id": "PERF-0008",
            "materialId": "PERF-0008",
            "name": "华能风电供货业绩",
            "folderPath": "商务标/共用业绩库/华能集团",
            "materialTier": "customer",
            "sourceType": "performance_library",
            "candidateType": "performance_record",
            "businessMaterialKind": "performance",
            "businessMaterialKindLabel": "共用业绩",
            "cleanStatus": "original_only",
            "tags": ["业绩"],
            "summary": "华能集团；风电供货；合同",
        }

        async def fake_raw_files(**_kwargs):
            return {
                "items": [
                    {
                        "id": "RAW-0001",
                        "name": "授权书.docx",
                        "folderPath": "商务标/通用素材/主体资质与基础证照",
                        "materialTier": "standard",
                        "tags": ["授权"],
                    }
                ]
            }

        async def fake_performance_candidates(scope, *, limit=300):
            self.assertEqual(scope, material_scope)
            self.assertEqual(limit, 300)
            return [performance_candidate]

        with patch.object(business_gap_planning.business_material_store, "raw_files", side_effect=fake_raw_files), patch.object(
            business_gap_planning.performance_library_service,
            "list_match_candidates",
            side_effect=fake_performance_candidates,
        ):
            items = business_gap_planning._business_material_index(material_scope, {})

        self.assertEqual([item["id"] for item in items], ["RAW-0001", "PERF-0008"])
        self.assertEqual(items[1]["sourceType"], "performance_library")
        self.assertEqual(items[1]["businessMaterialKindLabel"], "共用业绩")


if __name__ == "__main__":
    unittest.main()
