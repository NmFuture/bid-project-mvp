from __future__ import annotations

"""素材类别映射（清单驱动）测试：referenceFile 归一、素材分类、归属项目解析、必需类别聚合对账。"""

from app.services.technical_fact_field_specs import fillable_specs, load_specs
from app.services.technical_fact_material_classes import (
    classify_material,
    material_class_of,
    material_home_project,
    required_material_classes,
)


def _spec(reference_file: str) -> dict:
    return {"key": "K", "referenceFile": reference_file}


# ---------------------------------------------------------------- referenceFile 归一


def test_material_class_of_normalizes_reference_file() -> None:
    assert material_class_of(_spec("项目定制-风资源报告")) == "wind_resource"
    assert material_class_of(_spec("项目定制-塔架与基础工程量")) == "tower_quantity"
    assert material_class_of(_spec("项目定制-发电小时数承诺函")) == "hours_commitment"
    assert material_class_of(_spec("项目定制-项目生产制造基地专题")) == "production_base"
    assert material_class_of(_spec("认证证书（优先使用型式认证数据，如没有型式认证，其次使用设计认证数据）")) == "cert"
    assert material_class_of(_spec("招标文件")) == "tender"
    assert material_class_of(_spec("平台输入")) == "platform"
    assert material_class_of(_spec("自动生成")) == "derived"
    assert material_class_of(_spec("/")) == "none"


def test_material_class_of_handles_bending_moment_typo() -> None:
    # 清单原文 typo「基础弯矩表表」必须归一到 bending_moment
    assert material_class_of(_spec("项目定制-基础弯矩表表")) == "bending_moment"
    assert material_class_of(_spec("项目定制-基础弯矩表")) == "bending_moment"


def test_material_class_of_multiline_wind_resource_wins_over_tender() -> None:
    # 多行指路牌「风资源报告\n招标文件」归风资源（wind_resource 优先级高于 tender）
    assert material_class_of(_spec("项目定制-风资源报告\n招标文件")) == "wind_resource"


# ---------------------------------------------------------------- 素材分类正反例


def test_classify_material_positive() -> None:
    cases = [
        ({"name": "某项目风资源评估报告.docx"}, "wind_resource"),
        ({"name": "测风塔数据分析.pdf"}, "wind_resource"),
        ({"name": "塔架与基础工程量清单.xlsx"}, "tower_quantity"),
        ({"name": "基础弯矩表.xlsx"}, "bending_moment"),
        ({"name": "发电小时数承诺函.docx"}, "hours_commitment"),
        ({"name": "项目生产制造基地专题.docx"}, "production_base"),
        ({"name": "机组型式认证证书.pdf"}, "cert"),
        # 文件名不命中时按清洗文件名匹配
        ({"name": "附件2.xlsx", "cleanedFileName": "工程量汇总.xlsx"}, "tower_quantity"),
    ]
    for material, expected in cases:
        assert classify_material(material) == expected, material


def test_classify_material_negative() -> None:
    assert classify_material({"name": "会议纪要.docx", "folderPath": "技术标/标准库/通用"}) is None
    assert classify_material({"name": ""}) is None
    assert classify_material({}) is None


def test_classify_material_ignores_folder_path() -> None:
    """folderPath 不参与类别匹配：项目名/目录名里的关键词（如「不含塔架」）不能替文件归类。"""
    assert classify_material({"name": "附件1.docx", "folderPath": "技术标/项目定制/甲项目/风资源报告"}) is None
    assert classify_material({"name": "附表1.docx", "folderPath": "技术标/项目定制/甲项目不含塔架"}) is None


def test_classify_material_excludes_fill_templates() -> None:
    """「待填写」前缀的附表模板是要填的目标表格，即使名字含类别关键词也不归类。"""
    assert classify_material({"name": "待填写-附表1 塔架与基础工程量.docx"}) is None
    assert classify_material({"name": "待填写-风资源数据表.docx"}) is None
    assert classify_material({"name": "待填写、待用印-项目技术承诺函.docx"}) is None


# ---------------------------------------------------------------- 归属项目解析


def test_material_home_project_parses_third_segment() -> None:
    assert (
        material_home_project({"folderPath": "技术标/项目定制/甲项目/风资源报告/a.docx"}) == "甲项目"
    )
    assert material_home_project({"folderPath": "技术标/项目定制/乙项目"}) == "乙项目"
    assert material_home_project({"folderPath": "技术标/标准库/通用/a.docx"}) == ""
    assert material_home_project({"folderPath": ""}) == ""
    assert material_home_project({}) == ""


# ---------------------------------------------------------------- 必需类别聚合（与 spec 148/128 对账）


def test_required_material_classes_aggregation_matches_specs() -> None:
    specs = load_specs()
    fillable = fillable_specs()
    assert len(specs) == 148
    assert len(fillable) == 128

    required = required_material_classes()
    counts = {key: value["fieldCount"] for key, value in required.items()}
    assert counts == {
        "wind_resource": 26,  # 25 条风资源报告 + 1 条「风资源报告\n招标文件」多行指路牌
        "tower_quantity": 38,
        "bending_moment": 18,  # 含 typo「基础弯矩表表」
        "hours_commitment": 1,
        "production_base": 4,
        "cert": 4,
    }
    # tender(34)/platform(2)/derived(1) 无需素材，不计入；fieldKeys 条数与 fieldCount 一致
    assert sum(counts.values()) == 91
    for value in required.values():
        assert len(value["fieldKeys"]) == value["fieldCount"]
