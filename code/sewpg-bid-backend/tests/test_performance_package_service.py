from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from docx import Document
from docx.enum.text import WD_BREAK
from docx.shared import Inches

from app.services.performance_package_service import (
    match_contract_chunks_to_items,
    parse_performance_summary_docx,
    render_contract_item_docx,
    split_performance_contract_docx,
)


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


def _offshore_summary_docx_bytes() -> bytes:
    doc = Document()
    doc.add_paragraph("海上8MW及以上机型合同业绩表")
    doc.add_paragraph("投标人8MW及以上机型国内合同业绩台数共计628台，投运容量共计241台。")
    table = doc.add_table(rows=4, cols=10)
    headers = [
        "序号",
        "型号和规格",
        "项目名称",
        "总容量（MW)",
        "台数",
        "买方名称",
        "合同时间",
        "投运时间",
        "投运容量（MW)",
        "联系人及电话",
    ]
    rows = [
        ["1", "SG8.0-167", "长乐外海Ｃ区第一批项目", "200", "25", "福建省福能海峡发电有限公司", "2020年", "2021年", "200", "黄长凤137745142615"],
        ["2", "EW8.0-230 EW8.5-230", "山能渤中海上风电基地B1项目", "100", "4 8", "中国电建集团中南勘测设计研究院有限公司", "2024年", "2025年", "/", "程总17673048550"],
        ["3", "EW8.5-230", "国华山东B2场址项目", "501.5", "59", "国家能源投资集团（济南）新能源有限责任公司", "2022年", "/", "/", "刘欢18615226720"],
    ]
    for index, header in enumerate(headers):
        table.cell(0, index).text = header
    for row_index, row in enumerate(rows, start=1):
        for column_index, value in enumerate(row):
            table.cell(row_index, column_index).text = value
    output = BytesIO()
    doc.save(output)
    return output.getvalue()


def _tiny_png_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05"
        b"\xfe\x02\xfeA\x86\xa7\x9b\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def _contract_bundle_docx_bytes() -> bytes:
    image_stream = BytesIO(_tiny_png_bytes())
    doc = Document()
    doc.add_paragraph("华电新疆喀什 2×66 万千瓦风力发电机组采购合同")
    doc.paragraphs[0].runs[0].font.name = "方正兰亭超细黑简体"
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "封面页"
    table.cell(0, 0).paragraphs[0].runs[0].font.name = "宋体"
    table.cell(0, 1).paragraphs[0].add_run().add_picture(image_stream, width=Inches(0.2))
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    doc.add_paragraph("内蒙古能源察右前旗50万千瓦风光实验实证项目风力发电机组合同")
    image_stream = BytesIO(_tiny_png_bytes())
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "合同范围"
    table.cell(0, 1).paragraphs[0].add_run().add_picture(image_stream, width=Inches(0.2))
    output = BytesIO()
    doc.save(output)
    return output.getvalue()


def _docx_declared_fonts(content: bytes) -> set[str]:
    fonts: set[str] = set()
    font_attrs = {
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}ascii",
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}hAnsi",
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}eastAsia",
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}cs",
    }
    with ZipFile(BytesIO(content)) as zf:
        for name in zf.namelist():
            if not name.startswith("word/") or not name.endswith(".xml"):
                continue
            try:
                root = ET.fromstring(zf.read(name))
            except ET.ParseError:
                continue
            for element in root.iter():
                local_name = element.tag.rsplit("}", 1)[-1]
                if local_name == "rFonts":
                    fonts.update(value for attr, value in element.attrib.items() if attr in font_attrs and value)
                if local_name == "font":
                    font_name = element.attrib.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}name")
                    if font_name:
                        fonts.add(font_name)
                    theme_font_name = element.attrib.get("typeface")
                    if theme_font_name:
                        fonts.add(theme_font_name)
                if local_name in {"latin", "ea", "cs"}:
                    theme_font_name = element.attrib.get("typeface")
                    if theme_font_name:
                        fonts.add(theme_font_name)
    return fonts


def _docx_rfont_non_name_refs(content: bytes) -> set[str]:
    refs: set[str] = set()
    ref_attrs = {
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}asciiTheme",
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}hAnsiTheme",
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}eastAsiaTheme",
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}cstheme",
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}hint",
    }
    with ZipFile(BytesIO(content)) as zf:
        for name in zf.namelist():
            if not name.startswith("word/") or not name.endswith(".xml"):
                continue
            try:
                root = ET.fromstring(zf.read(name))
            except ET.ParseError:
                continue
            for element in root.iter():
                if element.tag.rsplit("}", 1)[-1] == "rFonts":
                    refs.update(value for attr, value in element.attrib.items() if attr in ref_attrs and value)
    return refs


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
    assert parsed["rows"][0]["turbineModels"] == ["11-230"]


def test_parse_performance_summary_docx_normalizes_models_and_time_fields() -> None:
    parsed = parse_performance_summary_docx(_offshore_summary_docx_bytes(), file_name="海上8MW及以上业绩_汇总表.docx")

    assert parsed["categoryName"] == "海上8MW及以上机型合同业绩表"
    assert parsed["scene"] == "海上"
    assert parsed["powerRating"] == "8MW及以上"
    assert parsed["rowCount"] == 3

    first = parsed["rows"][0]
    assert first["turbineModel"] == "SG8.0-167"
    assert first["turbineModels"] == ["SG8.0-167"]
    assert first["deliveryOrOperationTime"] == "2021年"
    assert first["contractYear"] == 2020
    assert first["operationYear"] == 2021
    assert first["timeFacts"]["contractTimeRaw"] == "2020年"
    assert first["timeFacts"]["operationTimeRaw"] == "2021年"

    multi_model = parsed["rows"][1]
    assert multi_model["turbineModel"] == "EW8.0-230 EW8.5-230"
    assert multi_model["turbineModels"] == ["EW8.0-230", "EW8.5-230"]
    assert multi_model["contractYear"] == 2024
    assert multi_model["operationYear"] == 2025

    not_commissioned = parsed["rows"][2]
    assert not_commissioned["contractYear"] == 2022
    assert not_commissioned["operationYear"] is None
    assert not_commissioned["deliveryOrOperationTime"] == ""


def test_split_performance_contract_docx_preserves_item_documents_and_images() -> None:
    chunks = split_performance_contract_docx(_contract_bundle_docx_bytes(), file_name="陆上11MW业绩_合同.docx")

    assert len(chunks) == 2
    assert chunks[0]["title"] == "华电新疆喀什 2×66 万千瓦风力发电机组采购合同"
    assert chunks[1]["title"] == "内蒙古能源察右前旗50万千瓦风光实验实证项目风力发电机组合同"

    first_doc = Document(BytesIO(chunks[0]["content"]))
    second_doc = Document(BytesIO(chunks[1]["content"]))
    assert first_doc.paragraphs[0].text == "华电新疆喀什 2×66 万千瓦风力发电机组"
    assert second_doc.paragraphs[0].text == "内蒙古能源察右前旗50万千瓦风光实验实证项目风力发电机组"
    assert len(first_doc.tables) == 1
    assert len(second_doc.tables) == 1
    assert first_doc.element.xpath('.//*[local-name()="drawing" or local-name()="pict"]')
    assert second_doc.element.xpath('.//*[local-name()="drawing" or local-name()="pict"]')


def test_render_contract_item_docx_uses_short_title_and_table_spacing() -> None:
    chunks = split_performance_contract_docx(_contract_bundle_docx_bytes(), file_name="陆上11MW业绩_合同.docx")
    content = render_contract_item_docx(chunks[0], output_title="华电新疆喀什 2×66 万千瓦")

    rendered = Document(BytesIO(content))
    assert rendered.paragraphs[0].text == "华电新疆喀什 2×66 万千瓦"
    assert all(paragraph.text != "华电新疆喀什 2×66 万千瓦风力发电机组采购合同" for paragraph in rendered.paragraphs)
    table_paragraph = rendered.tables[0].cell(0, 0).paragraphs[0]
    assert table_paragraph.paragraph_format.line_spacing == 1.5
    assert table_paragraph.paragraph_format.space_after.pt == 0
    fonts = _docx_declared_fonts(content)
    assert "Songti SC" in fonts
    assert "Times New Roman" in fonts
    assert "方正兰亭超细黑简体" not in fonts
    assert "宋体" not in fonts
    assert "Angsana New" not in fonts
    assert "Mangal" not in fonts
    assert not any("Theme" in font or font.startswith("major") or font.startswith("minor") for font in fonts)
    assert _docx_rfont_non_name_refs(content) == set()


def test_match_contract_chunks_to_items_prefers_project_name_then_row_order() -> None:
    parsed = parse_performance_summary_docx(_summary_docx_bytes(), file_name="陆上11MW业绩_汇总表.docx")
    chunks = split_performance_contract_docx(_contract_bundle_docx_bytes(), file_name="陆上11MW业绩_合同.docx")
    items = [
        {
            "id": f"PERITEM-{index:04d}",
            "categoryId": "PERCAT-0001",
            **row,
        }
        for index, row in enumerate(parsed["rows"], start=1)
    ]

    matches = match_contract_chunks_to_items(chunks, items)

    assert len(matches) == 2
    assert [match["item"]["projectName"] for match in matches] == [
        "华电新疆喀什 2×66 万千瓦",
        "内蒙古能源察右前旗50万千瓦风光实验实证项目",
    ]
    assert [match["chunk"]["title"] for match in matches] == [
        "华电新疆喀什 2×66 万千瓦风力发电机组采购合同",
        "内蒙古能源察右前旗50万千瓦风光实验实证项目风力发电机组合同",
    ]
    assert all(match["method"] == "project_name" for match in matches)
