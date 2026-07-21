from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from app.services.material_folder_maintenance import (
    bootstrap_project_material_folder,
    ensure_material_target_folder,
)
from app.services.material_raw_folder_operations import RawFolderOperations
from app.services.material_raw_lifecycle_operations import create_raw_folder


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _CreateFolderSession:
    def __init__(self, parent):
        self._results = iter((_ScalarResult(parent), _ScalarResult(None)))
        self.added = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, _statement):
        return next(self._results)

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None

    async def commit(self):
        return None


class _DuplicateFolderResult:
    def __init__(self, *values):
        self._values = values

    def scalar_one_or_none(self):
        raise AssertionError("历史重复目录不应导致查询要求唯一结果")

    def scalars(self):
        return self

    def first(self):
        return self._values[0] if self._values else None


class _DuplicateFolderSession:
    def __init__(self, *folders):
        self.result = _DuplicateFolderResult(*folders)
        self.added = []

    async def execute(self, _statement):
        return self.result

    async def get(self, _model, _identity):
        return None

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None


class MaterialEmptyRootTests(IsolatedAsyncioTestCase):
    async def test_technical_project_target_uses_project_customization_folder(self) -> None:
        technical_root = SimpleNamespace(id=1, path="技术标")
        project_root = SimpleNamespace(id=2, path="技术标/项目定制")
        project_folder = SimpleNamespace(id=3, path="技术标/项目定制/MATPRJ-001")
        ensure_folder_path = AsyncMock(side_effect=(technical_root, project_root, project_folder))

        result = await ensure_material_target_folder(
            object(),
            material_tier="project",
            bid_type="技术标",
            project_id="MATPRJ-001",
            ensure_folder_path=ensure_folder_path,
            clear_default_folder_deletion=AsyncMock(),
        )

        self.assertIs(result, project_folder)
        self.assertEqual(ensure_folder_path.await_args_list[1].args[1], "项目定制")

    async def test_technical_project_bootstrap_uses_project_customization_folder(self) -> None:
        technical_root = SimpleNamespace(id=1, path="技术标")
        project_root = SimpleNamespace(id=2, path="技术标/项目定制")
        project_folder = SimpleNamespace(id=3, path="技术标/项目定制/MATPRJ-001")
        ensure_folder_path = AsyncMock(side_effect=(technical_root, project_root, project_folder))

        result = await bootstrap_project_material_folder(
            object(),
            project_id="MATPRJ-001",
            bid_type="技术标",
            find_folder=AsyncMock(return_value=None),
            ensure_folder_path=ensure_folder_path,
        )

        self.assertEqual(result["payload"]["path"], "技术标/项目定制/MATPRJ-001")
        self.assertEqual(ensure_folder_path.await_args_list[1].args[1], "项目定制")

    async def test_ensure_folder_path_reuses_first_legacy_duplicate(self) -> None:
        operations = RawFolderOperations(ensure_runtime_tables=AsyncMock())
        first = SimpleNamespace(id=1, path="技术标")
        duplicate = SimpleNamespace(id=2, path="技术标")
        session = _DuplicateFolderSession(first, duplicate)

        folder = await operations.ensure_folder_path(
            session,
            "技术标",
            None,
            "standard",
            "技术标",
            None,
            1,
        )

        self.assertIs(folder, first)
        self.assertEqual(session.added, [])

    async def test_technical_root_does_not_precreate_tier_folders(self) -> None:
        ensure_runtime_tables = AsyncMock()
        operations = RawFolderOperations(ensure_runtime_tables=ensure_runtime_tables)
        root = SimpleNamespace(id=1, path="技术标")
        operations.ensure_folder_path = AsyncMock(return_value=root)
        operations.deleted_default_folder_paths = AsyncMock(return_value=set())

        with (
            patch(
                "app.services.material_raw_folder_operations.raw_material_root_specs",
                return_value=({"name": "技术标", "tier": "standard", "bid_type": "技术标", "sort_order": 1},),
            ),
            patch("app.services.material_raw_folder_operations.raw_material_tier_folder_specs") as tier_specs,
            patch(
                "app.services.material_raw_folder_operations.migrate_legacy_technical_folders",
                new=AsyncMock(),
            ),
        ):
            roots = await operations.ensure_raw_material_roots(object())

        self.assertEqual(roots, [root])
        tier_specs.assert_not_called()
        operations.ensure_folder_path.assert_awaited_once()

    async def test_business_root_keeps_existing_tier_bootstrap(self) -> None:
        operations = RawFolderOperations(ensure_runtime_tables=AsyncMock())
        business_root = SimpleNamespace(id=10, path="商务标")
        tier_folders = (
            SimpleNamespace(id=11, path="商务标/通用素材"),
            SimpleNamespace(id=12, path="商务标/客户素材"),
            SimpleNamespace(id=13, path="商务标/项目素材"),
        )
        tier_specs_value = (
            {"name": "通用素材", "tier": "standard", "sort_order": 1, "customer_name": "平台标准"},
            {"name": "客户素材", "tier": "customer", "sort_order": 2},
            {"name": "项目素材", "tier": "project", "sort_order": 3},
        )
        operations.ensure_folder_path = AsyncMock(side_effect=(business_root, *tier_folders))
        operations.deleted_default_folder_paths = AsyncMock(return_value=set())
        operations.find_folder = AsyncMock(return_value=tier_folders[0])

        with (
            patch(
                "app.services.material_raw_folder_operations.raw_material_root_specs",
                return_value=({"name": "商务标", "tier": "standard", "bid_type": "商务标", "sort_order": 2},),
            ),
            patch(
                "app.services.material_raw_folder_operations.raw_material_tier_folder_specs",
                return_value=tier_specs_value,
            ) as tier_specs,
            patch(
                "app.services.material_raw_folder_operations.ensure_business_standard_subfolders",
                new=AsyncMock(),
            ) as ensure_standard_subfolders,
            patch(
                "app.services.material_raw_folder_operations.backfill_existing_business_customized_subfolders",
                new=AsyncMock(),
            ) as backfill_customized_subfolders,
            patch(
                "app.services.material_raw_folder_operations.prune_empty_legacy_business_default_folders",
                new=AsyncMock(),
            ) as prune_legacy_folders,
            patch(
                "app.services.material_raw_folder_operations.migrate_legacy_technical_folders",
                new=AsyncMock(),
            ),
        ):
            roots = await operations.ensure_raw_material_roots(object())

        self.assertEqual(roots, [business_root])
        tier_specs.assert_called_once_with("商务标")
        self.assertEqual(operations.ensure_folder_path.await_count, 4)
        ensure_standard_subfolders.assert_awaited_once()
        backfill_customized_subfolders.assert_awaited_once()
        prune_legacy_folders.assert_awaited_once()

    async def test_creating_folder_from_technical_root_lazily_creates_standard_tier(self) -> None:
        technical_root = SimpleNamespace(
            id=1,
            path="技术标",
            tier="standard",
            bid_type="技术标",
            customer_name=None,
            project_id=None,
        )
        standard_root = SimpleNamespace(
            id=2,
            path="技术标/标准文件",
            tier="standard",
            bid_type="技术标",
            customer_name="平台标准",
            project_id=None,
        )
        session = _CreateFolderSession(technical_root)
        ensure_folder_path = AsyncMock(return_value=standard_root)

        with patch(
            "app.services.material_raw_lifecycle_operations.async_session",
            return_value=session,
        ):
            result = await create_raw_folder(
                parent_path="技术标",
                folder_name="自建目录",
                bid_type="技术标",
                ensure_runtime_tables=AsyncMock(),
                ensure_folder_path=ensure_folder_path,
                raw_tree=AsyncMock(return_value={"tree": []}),
            )

        self.assertEqual(result["folderPath"], "技术标/标准文件/自建目录")
        self.assertEqual(len(session.added), 1)
        self.assertEqual(session.added[0].parent_id, standard_root.id)
        self.assertEqual(session.added[0].path, "技术标/标准文件/自建目录")
        ensure_folder_path.assert_awaited_once()


class MaterialInitSqlTests(TestCase):
    def test_initdb_does_not_seed_legacy_technical_raw_folders(self) -> None:
        sql_path = Path(__file__).resolve().parents[2] / "initdb" / "01-init.sql"
        sql = sql_path.read_text(encoding="utf-8")

        self.assertNotIn("'通用素材/技术标'", sql)
        self.assertNotIn("'客户素材/华能集团/技术标'", sql)
        self.assertNotIn("'客户素材/大唐集团/技术标'", sql)

    def test_technical_wiki_has_no_seed_and_keeps_public_regeneration_entrypoint(self) -> None:
        code_root = Path(__file__).resolve().parents[2]
        sql = (code_root / "initdb" / "01-init.sql").read_text(encoding="utf-8")
        page_source = (
            code_root
            / "sewpg-bid-frontend"
            / "src"
            / "workspaces"
            / "technical"
            / "pages"
            / "TechnicalMaterialWiki.jsx"
        ).read_text(encoding="utf-8")
        api_source = (code_root / "sewpg-bid-frontend" / "src" / "api" / "index.js").read_text(encoding="utf-8")
        route_source = (
            code_root / "sewpg-bid-backend" / "app" / "api" / "routes" / "technical.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("INSERT INTO wiki_nodes", sql)
        self.assertNotIn("INSERT INTO wiki_docs", sql)
        # 刷新入口随预览重试功能改名为「刷新并重试」，重建入口保持不变
        self.assertIn("刷新并重试", page_source)
        self.assertIn("重建Wiki", page_source)
        self.assertIn("/technical/materials/wiki/bootstrap", api_source)
        self.assertIn("technical_wiki_bootstrap", route_source)
