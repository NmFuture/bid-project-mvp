from __future__ import annotations

from io import BytesIO

from docx import Document

from app.services.performance_package_service import parse_performance_summary_docx


def _summary_docx_bytes() -> bytes:
    doc = Document()
    doc.add_paragraph("陆上11MW业绩")
    doc.add_paragraph("合同业绩台数共计69台，已通过240小时试运行台数共计0台，投运容量共计0MW。")
    table = doc.add_table(rows=3, cols=9)
    headers = [
        "序号",
        "型号",
        "项目名称/合同名称",
        "买方名称",
        "合同台数",
        "试运行台数",
        "投运容量(MW)",
        "交货期/投运时间",
        "联系人及 电话",
    ]
    rows = [
        ["1", "11-230", "华电新疆喀什 2×66 万千瓦", "华电喀什能源有限公司哈密分公司", "59", "/", "/", "/", "翟文东0998-5817059"],
        ["2", "11-230", "内蒙古能源察右前旗50万千瓦风光实验实证项目", "内蒙古电力勘测设计院有限责任公司", "10", "/", "/", "/", "安文凭13644843963"],
    ]
    for index, header in enumerate(headers):
        table.cell(0, index).text = header
    for row_index, row in enumerate(rows, start=1):
        for column_index, value in enumerate(row):
            table.cell(row_index, column_index).text = value
    output = BytesIO()
    doc.save(output)
    return output.getvalue()


def test_parse_performance_summary_docx_extracts_category_and_rows() -> None:
    parsed = parse_performance_summary_docx(_summary_docx_bytes(), file_name="陆上11MW业绩_汇总表.docx")

    assert parsed["categoryName"] == "陆上11MW业绩"
    assert parsed["scene"] == "陆上"
    assert parsed["powerRating"] == "11MW"
    assert parsed["rowCount"] == 2
    assert [field["label"] for field in parsed["fieldSchema"]] == [
        "序号",
        "型号",
        "项目名称/合同名称",
        "买方名称",
        "合同台数",
        "试运行台数",
        "投运容量(MW)",
        "交货期/投运时间",
        "联系人及 电话",
    ]
    assert parsed["rows"][0]["projectName"] == "华电新疆喀什 2×66 万千瓦"
    assert parsed["rows"][0]["customerName"] == "华电喀什能源有限公司哈密分公司"
    assert parsed["rows"][0]["contractQuantity"] == "59"
    assert parsed["rows"][0]["trialOperationQuantity"] == ""
