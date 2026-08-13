from __future__ import annotations

"""技术标填表规则清单上传（POST /api/settings/technical-fact-specs）与 spec override 加载测试。"""

import json
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import technical_fact_field_specs as specs_module
from app.services.minio_client import minio_client
from app.services.store import store
from app.services.technical_fact_spec_import import (
    CURRENT_HEADER,
    EXPECTED_HEADER,
    LEGACY_HEADER,
    FactSpecImportError,
    import_specs,
)


@pytest.fixture()
def override_path(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "documents" / "technical_fact_field_specs.override.json"
    monkeypatch.setattr(settings, "documents_dir", tmp_path / "documents")
    monkeypatch.setattr(settings, "fact_specs_override_path", path)
    settings.ensure_dirs()
    specs_module.clear_specs_cache()
    yield path
    specs_module.clear_specs_cache()


@pytest.fixture()
def client(override_path, monkeypatch):
    monkeypatch.setattr(minio_client, "ensure_bucket", lambda _bucket: None)
    store.reset_for_tests()
    with TestClient(app, base_url="http://127.0.0.1:8000") as test_client:
        login = test_client.post(
            "/api/auth/login", json={"email": "admin@sewpg.com", "password": "123456"}
        )
        assert login.status_code == 200
        test_client.headers["Authorization"] = f"Bearer {login.json()['token']}"
        yield test_client


def _build_xlsx(path: Path, rows: int = 5, header: list[str] | None = None, note: str = "说明") -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header if header is not None else EXPECTED_HEADER)
    for index in range(1, rows + 1):
        ws.append(
            [
                index,
                "招标文件-技术规范书",
                "第一章 1.1",
                f"上传测试字段{index}",
                note,
                "",
                "招标文件/技术规范书",
            ]
        )
    wb.save(path)
    return path


def _upload(client: TestClient, path: Path, filename: str = "清单.xlsx"):
    with path.open("rb") as handle:
        return client.post(
            "/api/settings/technical-fact-specs",
            files={"file": (filename, handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )


def test_upload_valid_xlsx_writes_override_and_matches_contract(client, override_path, tmp_path) -> None:
    xlsx_path = _build_xlsx(tmp_path / "清单.xlsx", rows=6)
    response = _upload(client, xlsx_path)

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "specTotal": 6,
        "fillableTotal": 6,
        "needsConfirmation": 0,
        "template": 0,
        "override": True,
    }
    assert override_path.is_file()

    specs = specs_module.load_specs()
    assert len(specs) == 6
    assert specs[0]["label"] == "上传测试字段1"
    assert {spec["sourceKind"] for spec in specs} == {"tender"}


def test_upload_needs_confirmation_and_template_rows_counted(client, override_path, tmp_path) -> None:
    xlsx_path = _build_xlsx(tmp_path / "清单.xlsx", rows=3, note="需确认：以招标文件为准")
    response = _upload(client, xlsx_path)

    assert response.status_code == 200
    payload = response.json()
    assert payload["specTotal"] == 3
    assert payload["needsConfirmation"] == 3
    assert payload["fillableTotal"] == 3


def test_upload_rejects_non_xlsx_extension(client, override_path, tmp_path) -> None:
    bad_path = tmp_path / "清单.txt"
    bad_path.write_text("not an xlsx", encoding="utf-8")
    response = _upload(client, bad_path, filename="清单.txt")

    assert response.status_code == 400
    assert response.json()["detail"]
    assert not override_path.exists()


def test_upload_rejects_wrong_header_and_keeps_current_list(client, override_path, tmp_path) -> None:
    assert _upload(client, _build_xlsx(tmp_path / "有效.xlsx", rows=3)).status_code == 200

    xlsx_path = _build_xlsx(tmp_path / "清单.xlsx", rows=2, header=["A", "B", "C", "D", "E", "F", "G"])
    response = _upload(client, xlsx_path)

    assert response.status_code == 400
    assert "表头" in response.json()["detail"]
    # 上传失败不动已生效的清单
    assert len(specs_module.load_specs()) == 3


def test_upload_rejects_empty_workbook(client, override_path, tmp_path) -> None:
    wb = openpyxl.Workbook()
    empty_path = tmp_path / "空.xlsx"
    wb.save(empty_path)
    response = _upload(client, empty_path)

    assert response.status_code == 400
    assert not override_path.exists()


def test_override_takes_priority_and_mtime_change_reloads(client, override_path, tmp_path) -> None:
    first = _build_xlsx(tmp_path / "第一版.xlsx", rows=4)
    assert _upload(client, first).status_code == 200
    assert len(specs_module.load_specs()) == 4

    # 绕过路由直接改写 override 文件：mtime 变化后 load_specs 自动重读（无需手工清缓存）
    second_specs = import_specs(_build_xlsx(tmp_path / "第二版.xlsx", rows=7))
    override_path.write_text(json.dumps(second_specs, ensure_ascii=False), encoding="utf-8")
    reloaded = specs_module.load_specs()
    assert len(reloaded) == 7
    assert reloaded[0]["label"] == "上传测试字段1"


def test_deleting_list_leaves_no_specs(client, override_path, tmp_path) -> None:
    """仓库不再自带默认清单：清单文件没了就是没有清单，不能拿内置的一份顶上。"""
    xlsx_path = _build_xlsx(tmp_path / "清单.xlsx", rows=3)
    assert _upload(client, xlsx_path).status_code == 200
    assert len(specs_module.load_specs()) == 3

    override_path.unlink()
    assert specs_module.load_specs() == ()
    assert specs_module.fillable_specs() == []


def test_corrupt_list_leaves_no_specs(override_path) -> None:
    override_path.write_text("{broken json", encoding="utf-8")
    assert specs_module.load_specs() == ()


def test_import_specs_writes_output_path(tmp_path) -> None:
    xlsx_path = _build_xlsx(tmp_path / "清单.xlsx", rows=2)
    output_path = tmp_path / "out" / "specs.json"
    specs = import_specs(xlsx_path, output_path=output_path)

    assert output_path.is_file()
    assert json.loads(output_path.read_text(encoding="utf-8")) == specs


def test_import_specs_maps_new_and_legacy_source_headers(tmp_path) -> None:
    new_path = _build_xlsx(tmp_path / "新表头.xlsx", rows=1)
    legacy_path = _build_xlsx(tmp_path / "旧表头.xlsx", rows=1, header=LEGACY_HEADER)

    for path in (new_path, legacy_path):
        spec = import_specs(path)[0]
        assert spec["targetFile"] == "招标文件-技术规范书"
        assert spec["sourceFile"] == spec["targetFile"]
        assert spec["referenceFile"] == "招标文件/技术规范书"
        assert spec["sourceKind"] == "tender"


def test_import_specs_rejects_bad_seq(tmp_path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(EXPECTED_HEADER)
    ws.append(["不是数字", "招标文件", "第一章", "字段A", "", "", "招标文件/x"])
    bad_path = tmp_path / "坏序号.xlsx"
    wb.save(bad_path)

    with pytest.raises(FactSpecImportError, match="序号无效"):
        import_specs(bad_path)


def _write_sheet(path: Path, header: list[str], rows: list[list]) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header)
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


def test_import_specs_accepts_missing_optional_columns(tmp_path) -> None:
    # 序号/必要说明/复核都是可选列：缺了不报错，序号退化成行号
    path = _write_sheet(
        tmp_path / "精简表头.xlsx",
        ["待填写文件", "原占位符位置", "实际要填写的字段", "来源文件"],
        [["华能/待填写-塔筒.docx", "[技术方案，待填写]", "塔筒段数", "项目定制-塔架"]],
    )
    spec = import_specs(path)[0]

    assert spec["seq"] == 1
    assert spec["note"] == "" and spec["needsConfirmation"] is False
    assert spec["reviewLabel"] == ""
    assert spec["targetFile"] == "华能/待填写-塔筒.docx"
    assert spec["placeholder"] == "[技术方案，待填写]"


def test_import_specs_locates_columns_by_name_not_position(tmp_path) -> None:
    path = _write_sheet(
        tmp_path / "乱序表头.xlsx",
        ["实际要填写的字段", "来源文件", "待填写文件", "原占位符位置"],
        [["塔筒段数", "项目定制-塔架", "华能/待填写-塔筒.docx", "[技术方案，待填写]"]],
    )
    spec = import_specs(path)[0]

    assert spec["label"] == "塔筒段数"
    assert spec["targetFile"] == "华能/待填写-塔筒.docx"
    assert spec["referenceFile"] == "项目定制-塔架"
    assert spec["sourceKind"] == "material"


def test_import_specs_rejects_missing_required_column(tmp_path) -> None:
    path = _write_sheet(
        tmp_path / "缺占位符列.xlsx",
        ["序号", "待填写文件", "实际要填写的字段", "来源文件"],
        [[1, "华能/待填写-塔筒.docx", "塔筒段数", "项目定制-塔架"]],
    )

    with pytest.raises(FactSpecImportError, match="原占位符位置"):
        import_specs(path)


def test_import_specs_supports_current_maintained_header(tmp_path) -> None:
    """现场维护版表头：无字段名列，label 由「文件名 + 占位符内容」合成。

    该版本单列均不足以唯一标识一行（实测 207 行清单里占位符内容仅 87 个唯一值），
    因此必须组合，否则 normalize_key 生成的字段键会互相覆盖。
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(CURRENT_HEADER)
    # 两行占位符内容相同、文件名不同 —— 组合后才唯一
    ws.append([1, "待插入", "标准文件", "待填写-塔筒设计方案", "[基础弯矩表-完整插入，待插入]", "基础弯矩表.xlsx"])
    ws.append([2, "待插入", "客户定制-华能", "待填写-变桨系统专题", "[基础弯矩表-完整插入，待插入]", "基础弯矩表.xlsx"])
    # 引用文件留空 —— 模板占位，不进取数流程
    ws.append([3, "待填写", "标准文件", "待填写-大件部件运输情况", "[页码域，待填写]", ""])
    path = tmp_path / "现场维护版.xlsx"
    wb.save(path)

    specs = import_specs(path)
    assert len(specs) == 3

    keys = [s["key"] for s in specs]
    assert len(set(keys)) == 3, "占位符内容重复时仍须靠文件名区分，键不得冲突"

    first = specs[0]
    assert first["targetFile"] == "待填写-塔筒设计方案"
    assert first["placeholder"] == "[基础弯矩表-完整插入，待插入]"
    assert first["referenceFile"] == "基础弯矩表.xlsx"
    assert first["label"] == "待填写-塔筒设计方案 [基础弯矩表-完整插入，待插入]"
    assert first["note"] == "待插入"
    assert first["valueRequired"] is True

    blank_ref = specs[2]
    assert blank_ref["sourceKind"] == "template"
    assert blank_ref["valueRequired"] is False


def test_import_specs_error_message_lists_all_supported_headers(tmp_path) -> None:
    """表头不匹配时，报错须同时列出三种受支持表头，便于现场自查。"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["序号", "无关列A", "无关列B"])
    ws.append([1, "x", "y"])
    path = tmp_path / "错表头.xlsx"
    wb.save(path)

    with pytest.raises(FactSpecImportError) as exc:
        import_specs(path)
    message = str(exc.value)
    assert "待填写文件" in message
    assert "现场维护版表头" in message
