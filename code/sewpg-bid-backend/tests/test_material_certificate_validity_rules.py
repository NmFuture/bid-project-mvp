"""按《证书报告有效期确认.xlsx》规则表完善有效期识别与判断的测试。

规则表（Sheet2）：
- 整机设计认证 CQC：A 长期有效（设计不变）/ B 1年 / D 2年
- 整机型式认证 CQC：A 5年 / B 1年
- 部件型式认证 CQC：A 5年 / B 1年；鉴衡CGC：A 4年 / B 1年
- LVRT/HVRT/电能质量/电网适应性/故障电压连续穿越报告（电科院）：跟随整机型式证
- 机电/电磁暂态模型验证报告（电科院）：长期有效（控制策略不变）
"""

import pytest

from app.services.material_certificate_time import (
    apply_certificate_validity_rules,
    classify_certificate_validity_rule,
    extract_certificate_time_fields,
)


def _apply(text: str, file_name: str = "") -> dict:
    extracted = extract_certificate_time_fields(text)
    return apply_certificate_validity_rules(extracted, text=text, file_name=file_name)


# ---------- 分类识别 ----------


def test_classify_turbine_design_certificate_grade_a_long_term() -> None:
    info = classify_certificate_validity_rule(
        "风力发电机组设计认证证书\n中国质量认证中心（CQC）\n等级：A级",
        "整机设计认证证书.pdf",
    )

    assert info["certCategory"] == "整机设计认证"
    assert info["certAuthority"] == "CQC"
    assert info["certGrade"] == "A"
    assert info["rule"]["mode"] == "long_term"


def test_classify_component_type_certificate_cgc() -> None:
    info = classify_certificate_validity_rule("部件型式认证证书\n北京鉴衡认证中心\nB级")

    assert info["certCategory"] == "部件型式认证"
    assert info["certAuthority"] == "鉴衡CGC"
    assert info["certGrade"] == "B"
    assert info["rule"]["years"] == 1


def test_classify_lvrt_report_follows_turbine_certificate() -> None:
    info = classify_certificate_validity_rule("风电机组低压穿越（LVRT）检测报告\n中国电力科学研究院")

    assert info["certCategory"] == "低压穿越LVRT报告"
    assert info["rule"]["mode"] == "follow_turbine"


def test_classify_does_not_guess_grade_or_authority() -> None:
    # 部件型式认证有两个发证机构（CQC/鉴衡CGC），机构不明时不出规则
    info = classify_certificate_validity_rule("部件型式认证证书\nB级")
    assert info["certCategory"] == "部件型式认证"
    assert info["rule"] is None

    # 设计/型式认证未识别到等级时不猜
    info = classify_certificate_validity_rule("整机型式认证证书\n中国质量认证中心")
    assert info["certCategory"] == "整机型式认证"
    assert info["rule"] is None


# ---------- 有效期判断 ----------


def test_rule_derives_expiry_for_turbine_type_certificate_grade_a() -> None:
    result = _apply("整机型式认证证书（A级）\n中国质量认证中心\n发证日期：2025年4月10日")

    assert result["expiryDate"] == "2030-04-09"  # 5 年 - 1 天
    assert result["longTerm"] is False
    assert result["validityBasis"] == "rule_derived"
    assert "5年" in result["validityNote"]
    assert result["status"] == "extracted"


def test_rule_derives_expiry_for_design_certificate_grade_d() -> None:
    result = _apply("整机设计认证证书\n中国质量认证中心\nD级\n发证日期：2025-04-10")

    assert result["expiryDate"] == "2027-04-09"  # 2 年 - 1 天
    assert result["validityBasis"] == "rule_derived"


def test_rule_marks_long_term_for_design_certificate_grade_a() -> None:
    result = _apply("整机设计认证证书（A级）\n中国质量认证中心\n发证日期：2025年4月10日")

    assert result["expiryDate"] == ""
    assert result["longTerm"] is True
    assert result["validityBasis"] == "rule_long_term"
    assert "设计不变" in result["validityNote"]


def test_rule_marks_follow_turbine_for_grid_reports() -> None:
    for name in ("低压穿越", "高压穿越", "电能质量", "电网适应性", "故障电压连续穿越"):
        result = _apply(f"风电机组{name}检测报告\n中国电力科学研究院\n2025年4月10日")

        assert result["expiryDate"] == "", name
        assert result["longTerm"] is False, name
        assert result["validityBasis"] == "follow_turbine", name
        assert result["validityNote"] == "跟随对应整机型式认证有效期", name


def test_rule_marks_long_term_for_transient_model_reports() -> None:
    for name in ("机电暂态", "电磁暂态"):
        result = _apply(f"风电机组{name}模型验证报告\n中国电力科学研究院")

        assert result["longTerm"] is True, name
        assert result["validityBasis"] == "rule_long_term", name
        assert "控制策略不变" in result["validityNote"], name


def test_explicit_expiry_always_wins_over_rule() -> None:
    result = _apply(
        "整机型式认证证书（A级）\n中国质量认证中心\n发证日期：2025年4月10日\n有效期至：2028年4月9日"
    )

    assert result["expiryDate"] == "2028-04-09"
    assert result["validityBasis"] == "explicit"


def test_text_long_term_conflicting_with_years_rule_gets_warning() -> None:
    result = _apply("整机设计认证证书（B级）\n中国质量认证中心\n发证日期：2025年4月10日\n本证书长期有效")

    assert result["longTerm"] is True
    assert result["validityBasis"] == "text_long_term"
    assert any("标准有效期为1年" in warning for warning in result["warnings"])


def test_years_rule_without_issue_date_is_not_guessed() -> None:
    result = _apply("整机型式认证证书（A级）\n中国质量认证中心\n本证书加盖章有效")

    assert result["expiryDate"] == ""
    assert result["validityBasis"] == "rule_underived"
    assert any("无法按标准有效期5年推算" in warning for warning in result["warnings"])


def test_non_certificate_text_is_untouched() -> None:
    result = _apply("普通技术文件，无日期信息", "说明书.docx")

    assert result["validityBasis"] == ""
    assert result["validityNote"] == ""
    assert result["status"] == "not_found"


# ---------- 误判防护 ----------


def test_equipment_calibration_validity_is_not_certificate_expiry() -> None:
    # 报告内测试设备的“校准/计量有效期”不是证书有效期（RAW-0019 电能质量报告误判案例）
    result = _apply(
        "上海电气电能质量测试报告\n北京鉴衡认证中心（CGC）标准依据\n"
        "A/D采集卡分辨率：24位 校准有效期：2026年05月29日\n签发日期：2025年7月31日"
    )

    assert result["certCategory"] == "电能质量报告"
    assert result["expiryDate"] == ""
    assert result["validityBasis"] == "follow_turbine"


def test_single_authority_category_tolerates_authority_misdetection() -> None:
    # 电能质量报告规则表中只有电科院；OCR 噪声误检到鉴衡CGC 时不拦截规则，但如实保留检测结果
    info = classify_certificate_validity_rule("电能质量测试报告\n北京鉴衡认证中心")

    assert info["certCategory"] == "电能质量报告"
    assert info["certAuthority"] == "鉴衡CGC"
    assert info["rule"]["mode"] == "follow_turbine"


def test_type_certificate_without_component_keyword_uses_folder_fallback() -> None:
    # 文件名只写“型式认证A”时按目录兜底：部件目录→部件型式认证，否则→整机型式认证
    info = classify_certificate_validity_rule(
        "", "CGC2024461310096主轴承型式认证A-20240823.pdf", "技术标/标准文件/EW6.25-220/认证证书/部件认证/主轴承"
    )
    assert info["certCategory"] == "部件型式认证"
    assert info["certGrade"] == "A"

    info = classify_certificate_validity_rule(
        "", "CQC25030495634上海电气型式认证A-20260108更新.pdf", "技术标/标准文件/EW6.25-220/认证证书"
    )
    assert info["certCategory"] == "整机型式认证"
    assert info["certGrade"] == "A"
    assert info["rule"]["years"] == 5
