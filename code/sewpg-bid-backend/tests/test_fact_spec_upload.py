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
    EXPECTED_HEADER,
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


def _build_xlsx(
    path: Path, rows: int = 5, header: list[str] | None = None, row_type: str = "待填写"
) -> Path:
    """每行一个不同字段名，字段名由占位符内容剥离得出。"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header if header is not None else EXPECTED_HEADER)
    for index in range(1, rows + 1):
        ws.append(
            [
                index,
                row_type,
                "标准文件",
                "招标文件-技术规范书",
                f"[上传测试字段{index}，待填写]",
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


def test_upload_payload_counts_spec_and_fillable_totals(client, override_path, tmp_path) -> None:
    xlsx_path = _build_xlsx(tmp_path / "清单.xlsx", rows=3)
    response = _upload(client, xlsx_path)

    assert response.status_code == 200
    payload = response.json()
    assert payload["specTotal"] == 3
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


def test_import_specs_maps_target_and_reference_columns(tmp_path) -> None:
    spec = import_specs(_build_xlsx(tmp_path / "清单.xlsx", rows=1))[0]

    assert spec["targetFile"] == "招标文件-技术规范书"
    assert spec["sourceFile"] == spec["targetFile"]
    assert spec["referenceFile"] == "招标文件/技术规范书"
    assert spec["sourceKind"] == "tender"


def test_import_specs_rejects_bad_seq(tmp_path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(EXPECTED_HEADER)
    ws.append(["不是数字", "待填写", "标准文件", "招标文件", "[字段A，待填写]", "招标文件/x"])
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
    # 序号/类型/文件夹都是可选列：缺了不报错，序号退化成行号
    path = _write_sheet(
        tmp_path / "精简表头.xlsx",
        ["文件名", "占位符内容", "引用文件"],
        [["华能/待填写-塔筒.docx", "[塔筒段数，待填写]", "项目定制-塔架"]],
    )
    spec = import_specs(path)[0]

    assert spec["seq"] == 1
    assert spec["note"] == ""
    assert spec["reviewLabel"] == ""
    assert spec["targetFile"] == "华能/待填写-塔筒.docx"
    assert spec["placeholder"] == "[塔筒段数，待填写]"


def test_import_specs_locates_columns_by_name_not_position(tmp_path) -> None:
    path = _write_sheet(
        tmp_path / "乱序表头.xlsx",
        ["引用文件", "占位符内容", "类型", "文件名"],
        [["项目定制-塔架", "[塔筒段数，待填写]", "待填写", "华能/待填写-塔筒.docx"]],
    )
    spec = import_specs(path)[0]

    assert spec["label"] == "塔筒段数"
    assert spec["targetFile"] == "华能/待填写-塔筒.docx"
    assert spec["referenceFile"] == "项目定制-塔架"
    assert spec["sourceKind"] == "material"


def test_import_specs_rejects_missing_required_column(tmp_path) -> None:
    path = _write_sheet(
        tmp_path / "缺占位符列.xlsx",
        ["序号", "类型", "文件名", "引用文件"],
        [[1, "待填写", "华能/待填写-塔筒.docx", "项目定制-塔架"]],
    )

    with pytest.raises(FactSpecImportError, match="占位符内容"):
        import_specs(path)


def test_import_specs_strips_placeholder_decoration_into_label(tmp_path) -> None:
    """字段名取占位符正文：剥掉方括号（半/全角）与「待填写」类前后缀。"""
    raw_placeholders = [
        "[单台机组功率曲线保证率（%），待填写]",
        "【投标机型，待填写】",
        "[待填写：塔筒段数]",
        "[页码域,待补充]",
        "轮毂高度，待填写",
    ]
    path = _write_sheet(
        tmp_path / "占位符剥离.xlsx",
        EXPECTED_HEADER,
        [
            [index, "待填写", "标准文件", f"待填写-文件{index}.docx", raw, "招标文件/技术规范书"]
            for index, raw in enumerate(raw_placeholders, start=1)
        ],
    )

    assert [spec["label"] for spec in import_specs(path)] == [
        "单台机组功率曲线保证率（%）",
        "投标机型",
        "塔筒段数",
        "页码域",
        "轮毂高度",
    ]
    # 占位符原文必须原样留存，下游要拿它在 Word 里精确匹配
    assert import_specs(path)[0]["placeholder"] == raw_placeholders[0]


def test_import_specs_merges_rows_sharing_one_field_name(tmp_path) -> None:
    """同一事实在多个文件里各填一遍 → 合并成一个 spec，位置存分号多值。"""
    path = _write_sheet(
        tmp_path / "同名合并.xlsx",
        EXPECTED_HEADER,
        [
            [3, "待填写", "标准文件", "待填写-技术方案.docx", "[投标机型，待填写]", ""],
            [7, "待填写", "标准文件", "待填写-塔筒设计.docx", "[投标机型，待填写]", "项目定制-选型表"],
            [9, "待填写", "客户定制-华能", "待填写-变桨专题.docx", "【投标机型，待填写】", "项目定制-选型表"],
            [11, "待填写", "标准文件", "待填写-技术方案.docx", "[轮毂高度，待填写]", "项目定制-选型表"],
        ],
    )
    specs = import_specs(path)

    assert len(specs) == 2
    assert len({spec["key"] for spec in specs}) == 2

    model = next(spec for spec in specs if spec["label"] == "投标机型")
    assert model["targetFile"] == "待填写-技术方案.docx;待填写-塔筒设计.docx;待填写-变桨专题.docx"
    assert model["placeholder"] == "[投标机型，待填写];[投标机型，待填写];【投标机型，待填写】"
    assert model["sourceFile"] == model["targetFile"]
    # 组内取最小序号，排序保持稳定
    assert model["seq"] == 3
    # 首行引用文件留空时由后续同名行补上，否则整字段会被误判成模板占位
    assert model["referenceFile"] == "项目定制-选型表"
    assert model["valueRequired"] is True


def test_import_specs_merges_by_normalized_key_not_raw_label(tmp_path) -> None:
    """写法不同但归一化后同键的行必须并成一个 spec，否则两个 spec 共用一个 key。"""
    path = _write_sheet(
        tmp_path / "归一化合并.xlsx",
        EXPECTED_HEADER,
        [
            [1, "待填写", "标准文件", "待填写-A.docx", "[轮毂高度-m，待填写]", "项目定制-选型表"],
            [2, "待填写", "标准文件", "待填写-B.docx", "[轮毂高度，m，待填写]", "项目定制-选型表"],
        ],
    )
    specs = import_specs(path)

    assert len(specs) == 1
    assert specs[0]["label"] == "轮毂高度-m", "label 取首次出现的写法"
    assert specs[0]["targetFile"] == "待填写-A.docx;待填写-B.docx"


def test_import_specs_skips_embed_rows(tmp_path) -> None:
    """「待插入」是整文件插入指令，走 manifest 的 embedSources 通道，不是事实字段。"""
    path = _write_sheet(
        tmp_path / "含待插入.xlsx",
        EXPECTED_HEADER,
        [
            [1, "待插入", "标准文件", "待填写-塔筒设计.docx", "[基础弯矩表-完整插入，待插入]", "基础弯矩表.xlsx"],
            [2, "待插入", "客户定制-华能", "待填写-变桨专题.docx", "[基础弯矩表-完整插入，待插入]", "基础弯矩表.xlsx"],
            [3, "待填写", "标准文件", "待填写-大件运输.docx", "[页码域，待填写]", ""],
        ],
    )
    specs = import_specs(path)

    assert [spec["label"] for spec in specs] == ["页码域"]
    # 引用文件整格留空 —— 模板占位，不进取数流程
    assert specs[0]["sourceKind"] == "template"
    assert specs[0]["valueRequired"] is False


def test_import_specs_rejects_sheet_with_only_embed_rows(tmp_path) -> None:
    path = _write_sheet(
        tmp_path / "全待插入.xlsx",
        EXPECTED_HEADER,
        [[1, "待插入", "标准文件", "待填写-塔筒设计.docx", "[基础弯矩表-完整插入，待插入]", "基础弯矩表.xlsx"]],
    )

    with pytest.raises(FactSpecImportError, match="未解析出任何字段"):
        import_specs(path)


def test_import_specs_error_message_names_expected_header(tmp_path) -> None:
    """表头不匹配时，报错须列出缺的列与期望表头，便于现场自查。"""
    path = _write_sheet(tmp_path / "错表头.xlsx", ["序号", "无关列A", "无关列B"], [[1, "x", "y"]])

    with pytest.raises(FactSpecImportError) as exc:
        import_specs(path)
    message = str(exc.value)
    assert "文件名" in message
    assert "占位符内容" in message
    assert "期望表头" in message
    assert "实际" in message
