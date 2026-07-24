from __future__ import annotations

from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from app.services.material_move_operations import rename_raw_folder
from app.services.peripheral import PeripheralError


class _Result:
    def __init__(self, values=(), scalar=None):
        self._values = list(values)
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return self

    def all(self):
        return list(self._values)


class _RenameSession:
    """按序返回 rename_raw_folder 的查询：源目录、父级目录、两次 path lock、重名冲突、子树目录、子树文件。"""

    def __init__(self, *, source=None, parent=None, conflict=None, folders=(), files=()):
        self._results = iter(
            (
                _Result(scalar=source),
                _Result(scalar=parent),
                # _relocate_folder_subtree 会先按字典序对 source.path 和 next_root_path 加 advisory lock
                _Result(scalar=None),
                _Result(scalar=None),
                _Result(scalar=conflict),
                _Result(values=folders),
                _Result(values=files),
            )
        )
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, _statement, *_args, **_kwargs):
        return next(self._results)

    async def commit(self):
        self.committed = True


def _folder(folder_id, path, *, name=None, parent_id=None, tier="standard", bid_type="技术标", **extra):
    return SimpleNamespace(
        id=folder_id,
        parent_id=parent_id,
        name=name if name is not None else str(path).split("/")[-1],
        path=path,
        tier=tier,
        bid_type=bid_type,
        customer_name=extra.get("customer_name"),
        project_id=extra.get("project_id"),
        sort_order=0,
    )


def _file(file_id, folder, name, *, bucket="materials"):
    return SimpleNamespace(
        id=file_id,
        folder_id=folder.id,
        folder=folder,
        name=name,
        minio_bucket=bucket,
        minio_key=f"{folder.path}/{name}",
        ext_fields={},
    )


def _rename_kwargs(session):
    return {
        "ensure_runtime_tables": AsyncMock(),
        "raw_object_key": lambda folder_path, name: f"{folder_path}/{name}",
        "infer_material_tier_from_folder": lambda folder: str(getattr(folder, "tier", "") or "project"),
        "raw_tree": AsyncMock(return_value={"tree": []}),
        "session": session,
    }


class RenameRawFolderTests(IsolatedAsyncioTestCase):
    async def _rename(self, session, **overrides):
        kwargs = _rename_kwargs(session)
        kwargs.update(overrides)
        with (
            patch("app.services.material_move_operations.async_session", return_value=session),
            patch("app.services.material_move_operations.minio_client") as minio_mock,
        ):
            result = await rename_raw_folder(
                path=kwargs.pop("path"),
                new_name=kwargs.pop("new_name"),
                bid_type=kwargs.pop("bid_type"),
                ensure_runtime_tables=kwargs["ensure_runtime_tables"],
                raw_object_key=kwargs["raw_object_key"],
                infer_material_tier_from_folder=kwargs["infer_material_tier_from_folder"],
                raw_tree=kwargs["raw_tree"],
            )
        return result, minio_mock

    async def test_rename_folder_rewrites_subtree_paths_and_file_keys(self) -> None:
        parent = _folder(2, "技术标/标准文件")
        source = _folder(10, "技术标/标准文件/旧目录", parent_id=2)
        child = _folder(11, "技术标/标准文件/旧目录/子目录", parent_id=10)
        item = _file(5, child, "机型参数.docx")
        session = _RenameSession(source=source, parent=parent, folders=[source, child], files=[item])

        result, minio_mock = await self._rename(
            session,
            path="技术标/标准文件/旧目录",
            new_name="新目录",
            bid_type="技术标",
        )

        self.assertEqual(result["message"], "文件夹重命名成功")
        self.assertEqual(result["folderPath"], "技术标/标准文件/新目录")
        self.assertEqual(result["movedFileCount"], 1)
        # 子树目录路径级联更新，父级与继承属性保持不变
        self.assertEqual(source.name, "新目录")
        self.assertEqual(source.path, "技术标/标准文件/新目录")
        self.assertEqual(source.parent_id, parent.id)
        self.assertEqual(source.tier, "standard")
        self.assertEqual(child.path, "技术标/标准文件/新目录/子目录")
        # 子树文件 minio key 迁移 + 审计口径与 move-folder 一致（rename-folder 动作）
        self.assertEqual(item.minio_key, "技术标/标准文件/新目录/子目录/机型参数.docx")
        self.assertEqual(item.ext_fields["lastAction"], "rename-folder")
        self.assertEqual(item.ext_fields["lastOperator"], "当前用户")
        minio_mock.copy_object.assert_called_once_with(
            "materials",
            "技术标/标准文件/旧目录/子目录/机型参数.docx",
            "技术标/标准文件/新目录/子目录/机型参数.docx",
        )
        minio_mock.remove_object.assert_called_once_with(
            "materials",
            "技术标/标准文件/旧目录/子目录/机型参数.docx",
        )
        self.assertTrue(session.committed)

    async def test_rename_folder_conflict_returns_409(self) -> None:
        parent = _folder(2, "技术标/标准文件")
        source = _folder(10, "技术标/标准文件/旧目录", parent_id=2)
        existing = _folder(12, "技术标/标准文件/新目录", parent_id=2)
        session = _RenameSession(source=source, parent=parent, conflict=existing)

        with (
            patch("app.services.material_move_operations.async_session", return_value=session),
            self.assertRaises(PeripheralError) as context,
        ):
            await rename_raw_folder(
                path="技术标/标准文件/旧目录",
                new_name="新目录",
                bid_type="技术标",
                ensure_runtime_tables=AsyncMock(),
                raw_object_key=lambda folder_path, name: f"{folder_path}/{name}",
                infer_material_tier_from_folder=lambda folder: "standard",
                raw_tree=AsyncMock(return_value={"tree": []}),
            )

        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(context.exception.code, "RAW_FOLDER_EXISTS")
        self.assertFalse(session.committed)

    async def test_rename_default_tier_folder_and_root_are_protected(self) -> None:
        for folder_path in ("技术标", "技术标/标准文件", "技术标/客户定制", "技术标/项目定制"):
            with (
                patch("app.services.material_move_operations.async_session") as session_factory,
                self.assertRaises(PeripheralError) as context,
            ):
                await rename_raw_folder(
                    path=folder_path,
                    new_name="改名",
                    bid_type="技术标",
                    ensure_runtime_tables=AsyncMock(),
                    raw_object_key=lambda fp, name: f"{fp}/{name}",
                    infer_material_tier_from_folder=lambda folder: "standard",
                    raw_tree=AsyncMock(return_value={"tree": []}),
                )
            self.assertEqual(context.exception.status_code, 400)
            self.assertEqual(context.exception.code, "RAW_FOLDER_RENAME_PROTECTED")
            session_factory.assert_not_called()

    async def test_rename_missing_folder_returns_404(self) -> None:
        session = _RenameSession(source=None)

        with (
            patch("app.services.material_move_operations.async_session", return_value=session),
            self.assertRaises(PeripheralError) as context,
        ):
            await rename_raw_folder(
                path="技术标/标准文件/不存在",
                new_name="新目录",
                bid_type="技术标",
                ensure_runtime_tables=AsyncMock(),
                raw_object_key=lambda fp, name: f"{fp}/{name}",
                infer_material_tier_from_folder=lambda folder: "standard",
                raw_tree=AsyncMock(return_value={"tree": []}),
            )

        self.assertEqual(context.exception.status_code, 404)
        self.assertEqual(context.exception.code, "RAW_FOLDER_NOT_FOUND")

    async def test_rename_invalid_name_returns_400(self) -> None:
        for new_name, code in (("  ", "RAW_FOLDER_NAME_REQUIRED"), ("含/分隔符", "RAW_FOLDER_NAME_INVALID"), ("含\\分隔符", "RAW_FOLDER_NAME_INVALID")):
            with self.assertRaises(PeripheralError) as context:
                await rename_raw_folder(
                    path="技术标/标准文件/旧目录",
                    new_name=new_name,
                    bid_type="技术标",
                    ensure_runtime_tables=AsyncMock(),
                    raw_object_key=lambda fp, name: f"{fp}/{name}",
                    infer_material_tier_from_folder=lambda folder: "standard",
                    raw_tree=AsyncMock(return_value={"tree": []}),
                )
            self.assertEqual(context.exception.status_code, 400)
            self.assertEqual(context.exception.code, code)


class RenameRawFolderBusinessTests(IsolatedAsyncioTestCase):
    async def test_business_rename_folder_success(self) -> None:
        parent = _folder(3, "商务标/客户素材/华能集团", tier="customer", bid_type="商务标", customer_name="华能集团")
        source = _folder(20, "商务标/客户素材/华能集团/临时目录", parent_id=3, tier="customer", bid_type="商务标")
        item = _file(7, source, "授权书.docx")
        session = _RenameSession(source=source, parent=parent, folders=[source], files=[item])

        with (
            patch("app.services.material_move_operations.async_session", return_value=session),
            patch("app.services.material_move_operations.minio_client") as minio_mock,
        ):
            result = await rename_raw_folder(
                path="商务标/客户素材/华能集团/临时目录",
                new_name="正式目录",
                bid_type="商务标",
                ensure_runtime_tables=AsyncMock(),
                raw_object_key=lambda folder_path, name: f"{folder_path}/{name}",
                infer_material_tier_from_folder=lambda folder: str(getattr(folder, "tier", "") or "project"),
                raw_tree=AsyncMock(return_value={"tree": []}),
            )

        self.assertEqual(result["folderPath"], "商务标/客户素材/华能集团/正式目录")
        self.assertEqual(source.name, "正式目录")
        self.assertEqual(source.path, "商务标/客户素材/华能集团/正式目录")
        self.assertEqual(item.minio_key, "商务标/客户素材/华能集团/正式目录/授权书.docx")
        self.assertEqual(item.ext_fields["lastAction"], "rename-folder")
        minio_mock.copy_object.assert_called_once()
        self.assertTrue(session.committed)

    async def test_business_rename_default_tier_folder_is_protected(self) -> None:
        for folder_path in ("商务标", "商务标/通用素材", "商务标/客户素材", "商务标/项目素材", "商务标/客户素材/华能集团"):
            with (
                patch("app.services.material_move_operations.async_session") as session_factory,
                self.assertRaises(PeripheralError) as context,
            ):
                await rename_raw_folder(
                    path=folder_path,
                    new_name="改名",
                    bid_type="商务标",
                    ensure_runtime_tables=AsyncMock(),
                    raw_object_key=lambda fp, name: f"{fp}/{name}",
                    infer_material_tier_from_folder=lambda folder: "customer",
                    raw_tree=AsyncMock(return_value={"tree": []}),
                )
            self.assertEqual(context.exception.status_code, 400)
            self.assertEqual(context.exception.code, "RAW_FOLDER_RENAME_PROTECTED")
            session_factory.assert_not_called()


if __name__ == "__main__":
    import unittest

    unittest.main()
