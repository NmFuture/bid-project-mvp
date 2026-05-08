from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.material_store import material_store


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
            patch.object(material_store, "_ensure_runtime_tables", new=AsyncMock()),
            patch.object(material_store, "_ensure_raw_material_roots", new=AsyncMock(return_value=[])),
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
            patch.object(material_store, "_ensure_runtime_tables", new=AsyncMock()),
            patch.object(material_store, "_ensure_raw_material_roots", new=AsyncMock(return_value=[])),
        ):
            payload = await material_store.identity_options(bid_type="技术标")

        self.assertEqual([item["customerId"] for item in payload["customers"]], ["CUST-HUANENG"])
        self.assertEqual([item["projectId"] for item in payload["projects"]], ["PRJ-0001"])
        self.assertEqual(payload["projects"][0]["source"], "project")


if __name__ == "__main__":
    unittest.main()
