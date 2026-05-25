from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.material_identity_options import build_material_identity_options
from app.services.material_store import material_store
from app.services.technical_turbine_material_options import list_technical_turbine_model_options


class _ScalarResult:
    def __init__(self, items: list[object]) -> None:
        self._items = items

    def all(self) -> list[object]:
        return self._items


class _ExecuteResult:
    def __init__(self, items: list[object]) -> None:
        self._items = items

    def scalars(self) -> _ScalarResult:
        return _ScalarResult(self._items)


class _MappingResult:
    def __init__(self, items: list[dict[str, object]]) -> None:
        self._items = items

    def all(self) -> list[dict[str, object]]:
        return self._items


class _ExecuteMappingResult:
    def __init__(self, items: list[dict[str, object]]) -> None:
        self._items = items

    def mappings(self) -> _MappingResult:
        return _MappingResult(self._items)


class _FakeSession:
    def __init__(self, folders: list[object], files: list[object], projects: list[dict[str, object]] | None = None) -> None:
        self._results = [_ExecuteResult(folders), _ExecuteResult(files), _ExecuteMappingResult(projects or [])]

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def execute(self, _statement: object) -> _ExecuteResult:
        return self._results.pop(0)


class _SingleExecuteSession:
    def __init__(self, items: list[object]) -> None:
        self._items = items

    async def __aenter__(self) -> _SingleExecuteSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, _statement: object) -> _ExecuteResult:
        return _ExecuteResult(self._items)


class MaterialIdentityOptionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_identity_options_only_return_material_library_identities(self) -> None:
        folders = [
            SimpleNamespace(
                path="技术标/客户素材/华能集团",
                tier="customer",
                bid_type="技术标",
                customer_name="华能集团",
                project_id="",
            ),
            SimpleNamespace(
                path="技术标/项目素材/MAT-HN-CHIFENG-001",
                tier="project",
                bid_type="技术标",
                customer_name="",
                project_id="MAT-HN-CHIFENG-001",
            ),
        ]
        files = [
            SimpleNamespace(
                ext_fields={
                    "materialTier": "project",
                    "bidType": "技术标",
                    "projectId": "MAT-HN-CHIFENG-001",
                    "projectCode": "MAT-HN-CHIFENG-001",
                    "projectName": "MAT-HN-CHIFENG-001",
                    "customerId": "CUST-HUANENG",
                    "customerCanonicalName": "华能集团",
                },
            )
        ]

        fake_session = _FakeSession(folders, files)
        with (
            patch("app.services.material_store.async_session", return_value=fake_session),
            patch("app.services.material_store.ensure_material_runtime_tables", new=AsyncMock()),
            patch.object(material_store._raw_folders, "ensure_raw_material_roots", new=AsyncMock(return_value=[])),
        ):
            payload = await material_store.identity_options(bid_type="技术标")

        self.assertEqual([item["customerId"] for item in payload["customers"]], ["CUST-HUANENG"])
        self.assertEqual([item["projectId"] for item in payload["projects"]], ["MAT-HN-CHIFENG-001"])

    async def test_identity_options_include_project_store_projects(self) -> None:
        fake_session = _FakeSession(
            folders=[],
            files=[],
            projects=[
                {
                    "id": "PRJ-0001",
                    "payload": {
                        "id": "PRJ-0001",
                        "projectCode": "PRJ-0001",
                        "name": "赤峰风电项目",
                        "customerName": "华能集团",
                        "bidType": "技术标",
                    },
                }
            ],
        )
        with (
            patch("app.services.material_store.async_session", return_value=fake_session),
            patch("app.services.material_store.ensure_material_runtime_tables", new=AsyncMock()),
            patch.object(material_store._raw_folders, "ensure_raw_material_roots", new=AsyncMock(return_value=[])),
        ):
            payload = await material_store.identity_options(bid_type="技术标")

        self.assertEqual([item["customerId"] for item in payload["customers"]], ["CUST-HUANENG"])
        self.assertEqual([item["projectId"] for item in payload["projects"]], ["PRJ-0001"])
        self.assertEqual(payload["projects"][0]["source"], "project")

    async def test_identity_options_builder_filters_opposite_bid_type_projects(self) -> None:
        payload = build_material_identity_options(
            folders=[],
            files=[
                SimpleNamespace(
                    ext_fields={
                        "materialTier": "project",
                        "bidType": "商务标",
                        "projectId": "BIZ-001",
                        "projectName": "商务项目",
                        "customerCanonicalName": "华能集团",
                    }
                )
            ],
            project_rows=[
                {
                    "id": "TECH-001",
                    "payload": {
                        "id": "TECH-001",
                        "name": "技术项目",
                        "customerName": "华能集团",
                        "bidType": "技术标",
                    },
                }
            ],
            bid_type="商务标",
        )

        self.assertEqual([item["projectId"] for item in payload["projects"]], ["BIZ-001"])
        self.assertEqual(payload["projects"][0]["bidType"], "商务标")

    async def test_identity_options_builder_keeps_unscoped_legacy_project_as_common(self) -> None:
        payload = build_material_identity_options(
            folders=[
                SimpleNamespace(
                    path="项目素材/LEGACY-COMMON-001",
                    tier="",
                    bid_type="",
                    customer_name="",
                    project_id="",
                )
            ],
            files=[],
            project_rows=[],
            bid_type="",
        )

        self.assertEqual([item["projectId"] for item in payload["projects"]], ["LEGACY-COMMON-001"])
        self.assertEqual(payload["projects"][0]["bidType"], "通用")


class TechnicalTurbineMaterialOptionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_turbine_options_ignore_business_materials(self) -> None:
        files = [
            SimpleNamespace(
                id=1,
                name="EW10.0-220下置 技术说明.docx",
                ext_fields={"bidType": "技术标"},
                folder=SimpleNamespace(path="技术标/通用素材", bid_type="技术标"),
                minio_bucket="bid-materials",
                minio_key="raw/technical.docx",
            ),
            SimpleNamespace(
                id=2,
                name="EW10.0-230上置 商务授权.docx",
                ext_fields={"bidType": "商务标"},
                folder=SimpleNamespace(path="商务标/通用素材", bid_type="商务标"),
                minio_bucket="bid-materials",
                minio_key="raw/business.docx",
            ),
            SimpleNamespace(
                id=3,
                name="EW10.0-240下置 商务补充.docx",
                ext_fields={},
                folder=SimpleNamespace(path="商务标/通用素材", bid_type=""),
                minio_bucket="bid-materials",
                minio_key="raw/business-untagged.docx",
            ),
        ]

        with patch("app.services.technical_turbine_material_options.async_session", return_value=_SingleExecuteSession(files)):
            payload = await list_technical_turbine_model_options()

        self.assertEqual(payload["bidType"], "技术标")
        self.assertEqual([item["model"] for item in payload["items"]], ["EW10.0-220"])
        self.assertNotIn("EW10.0-230", [item["model"] for item in payload["items"]])
        self.assertNotIn("EW10.0-240", [item["model"] for item in payload["items"]])


if __name__ == "__main__":
    unittest.main()
