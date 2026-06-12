import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape


SCRIPT = Path(__file__).with_name("prepare_history_bid_outline_inputs.py")


DOCX_WRAPPERS = {
    "[Content_Types].xml": """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">
  <Default Extension=\"xml\" ContentType=\"application/xml\"/>
  <Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>
  <Override PartName=\"/word/styles.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml\"/>
</Types>""",
    "_rels/.rels": """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"/>""",
}


def paragraph(text, style=None, outline_level=None, runs=None):
    style_xml = ""
    if style:
        style_xml += f'<w:pStyle w:val="{escape(style)}"/>'
    if outline_level is not None:
        style_xml += f'<w:outlineLvl w:val="{outline_level}"/>'
    ppr_xml = f"<w:pPr>{style_xml}</w:pPr>" if style_xml else ""
    run_xml = "".join(runs) if runs is not None else f"<w:r><w:t>{escape(text)}</w:t></w:r>"
    return f"<w:p>{ppr_xml}{run_xml}</w:p>"


def run_text(text):
    return f"<w:r><w:t>{escape(text)}</w:t></w:r>"


def field_begin():
    return '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'


def field_separate():
    return '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'


def field_end():
    return '<w:r><w:fldChar w:fldCharType="end"/></w:r>'


def instr(text):
    return f"<w:r><w:instrText>{escape(text)}</w:instrText></w:r>"


def hyperlink(anchor, text):
    return f'<w:hyperlink w:anchor="{escape(anchor)}">{run_text(text)}</w:hyperlink>'


def bookmark_start(name):
    return f'<w:bookmarkStart w:id="1" w:name="{escape(name)}"/>'


def styles_xml(style_names):
    styles = []
    for style_id, name in style_names.items():
        styles.append(f'<w:style w:type="paragraph" w:styleId="{escape(style_id)}"><w:name w:val="{escape(name)}"/></w:style>')
    return """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<w:styles xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">%s</w:styles>""" % "".join(styles)


def auto_toc_sdt(items):
    paragraphs = [paragraph("", runs=[field_begin(), instr(' TOC \\o "1-3" \\h \\z \\u '), field_separate()])]
    for item in items:
        style = item.get("style", "TOC1")
        bookmark = item["bookmark"]
        title = item["title"]
        page = item["page"]
        paragraphs.append(paragraph("", style=style, runs=[
            field_begin(),
            instr(f' HYPERLINK \\l "{bookmark}" '),
            field_separate(),
            hyperlink(bookmark, title),
            field_end(),
            run_text("\t"),
            field_begin(),
            instr(f" PAGEREF {bookmark} \\h "),
            field_separate(),
            run_text(str(page)),
            field_end(),
        ]))
    paragraphs.append(paragraph("", runs=[field_end()]))
    return """
<w:sdt>
  <w:sdtPr><w:docPartObj><w:docPartGallery w:val="Table of Contents"/></w:docPartObj></w:sdtPr>
  <w:sdtContent>%s</w:sdtContent>
</w:sdt>""" % "\n".join(paragraphs)


def auto_toc_sdt_with_field_result_runs(items):
    paragraphs = [paragraph("目录"), paragraph("", runs=[field_begin(), instr(' TOC \\o "1-3" \\h \\z \\u '), field_separate()])]
    for item in items:
        bookmark = item["bookmark"]
        title = item["title"]
        page = item["page"]
        paragraphs.append(paragraph("", runs=[
            field_begin(),
            instr(f' HYPERLINK \\l "{bookmark}" '),
            field_separate(),
            run_text("\t"),
            run_text(title),
            field_end(),
            run_text("\t"),
            field_begin(),
            instr(f" PAGEREF {bookmark} \\h "),
            field_separate(),
            run_text(str(page)),
            field_end(),
        ]))
    paragraphs.append(paragraph("", runs=[field_end()]))
    return """
<w:sdt>
  <w:sdtPr><w:docPartObj><w:docPartGallery w:val="Table of Contents"/></w:docPartObj></w:sdtPr>
  <w:sdtContent>%s</w:sdtContent>
</w:sdt>""" % "\n".join(paragraphs)


def make_docx(path, body_elements, styles=None):
    document = """<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">
  <w:body>
    %s
  </w:body>
</w:document>""" % "\n".join(body_elements)
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in DOCX_WRAPPERS.items():
            archive.writestr(name, content)
        archive.writestr("word/document.xml", document)
        if styles is not None:
            archive.writestr("word/styles.xml", styles)


class PrepareHistoryBidOutlineInputsTest(unittest.TestCase):
    def run_script(self, body_elements, styles=None):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            docx_path = tmpdir / "历史商务标投标文件.docx"
            output_path = tmpdir / "history_bid_outline_inputs.json"
            make_docx(docx_path, body_elements, styles)
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(docx_path), "--output", str(output_path)],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            return json.loads(output_path.read_text(encoding="utf-8"))

    def test_extracts_candidates_from_word_automatic_toc_control_only(self):
        output = self.run_script([
            paragraph("封面"),
            auto_toc_sdt([
                {"title": "商务评分索引表", "bookmark": "_Toc1001", "page": 1, "style": "TOC1"},
                {"title": "供货保障专题", "bookmark": "_Toc1002", "page": 2, "style": "TOC1"},
                {"title": "供应链说明", "bookmark": "_Toc1003", "page": 3, "style": "TOC2"},
            ]),
            paragraph("商务评分索引表", outline_level=0, runs=[bookmark_start("_Toc1001"), run_text("商务评分索引表")]),
            paragraph("1.1 投标函"),
            paragraph("7.9.2.100 华能某项目正文内容"),
        ])

        self.assertEqual(output["outline_source"]["source_type"], "history_bid_auto_toc")
        candidates = output["outline_candidates"]
        self.assertEqual([candidate["title_hint"] for candidate in candidates], ["商务评分索引表", "供货保障专题", "供应链说明"])
        self.assertEqual([candidate["level"] for candidate in candidates], [1, 1, 2])
        self.assertEqual(candidates[0]["bookmark_name"], "_Toc1001")
        self.assertIn("商务评分索引表", candidates[0]["source_text"])
        self.assertIn("1", candidates[0]["source_text"])
        self.assertNotIn("1.1 投标函", [candidate["source_text"] for candidate in candidates])

    def test_extracts_automatic_toc_field_result_text_without_hyperlink_element(self):
        output = self.run_script([
            paragraph("封面"),
            auto_toc_sdt_with_field_result_runs([
                {"title": "商务评分索引表", "bookmark": "_Toc2001", "page": 6},
                {"title": "供货保障专题", "bookmark": "_Toc2002", "page": 14},
                {"title": "供应链说明", "bookmark": "_Toc2003", "page": 15},
            ]),
            paragraph("商务评分索引表", outline_level=0, runs=[bookmark_start("_Toc2001"), run_text("商务评分索引表")]),
            paragraph("供货保障专题", outline_level=0, runs=[bookmark_start("_Toc2002"), run_text("供货保障专题")]),
            paragraph("供应链说明", outline_level=1, runs=[bookmark_start("_Toc2003"), run_text("供应链说明")]),
            paragraph("1.1 投标函"),
        ])

        self.assertEqual(output["outline_source"]["source_type"], "history_bid_auto_toc")
        candidates = output["outline_candidates"]
        self.assertEqual([candidate["title_hint"] for candidate in candidates], ["商务评分索引表", "供货保障专题", "供应链说明"])
        self.assertEqual([candidate["level"] for candidate in candidates], [1, 1, 2])
        self.assertEqual(candidates[2]["matched_body_block_id"], "hb-0008")

    def test_uses_style_name_mapping_for_numeric_auto_toc_styles(self):
        output = self.run_script([
            paragraph("封面"),
            auto_toc_sdt([
                {"title": "投标函及授权文件", "bookmark": "_Toc3001", "page": 1, "style": "59"},
                {"title": "1.1 投标函", "bookmark": "_Toc3002", "page": 2, "style": "74"},
                {"title": "1.2 法定代表人授权委托书", "bookmark": "_Toc3003", "page": 3, "style": "74"},
            ]),
        ], styles_xml({"59": "toc 1", "74": "toc 2"}))

        self.assertEqual(output["outline_source"]["source_type"], "history_bid_auto_toc")
        self.assertEqual([candidate["level"] for candidate in output["outline_candidates"]], [1, 2, 2])
        self.assertEqual([candidate["number"] for candidate in output["outline_candidates"]], [None, "1.1", "1.2"])
        self.assertEqual([candidate["title_hint"] for candidate in output["outline_candidates"]], ["投标函及授权文件", "投标函", "法定代表人授权委托书"])

    def test_dot_number_depth_overrides_toc_style_for_fourth_level(self):
        output = self.run_script([
            paragraph("封面"),
            auto_toc_sdt([
                {"title": "7 资格证明文件", "bookmark": "_Toc4001", "page": 1, "style": "TOC1"},
                {"title": "7.2 认证证书", "bookmark": "_Toc4002", "page": 2, "style": "TOC2"},
                {"title": "7.2.2 机型认证", "bookmark": "_Toc4003", "page": 3, "style": "TOC3"},
                {"title": "7.2.2.1 EW10.0-220 设计认证证书", "bookmark": "_Toc4004", "page": 4, "style": "TOC3"},
            ]),
        ])

        self.assertEqual(
            [(candidate["number"], candidate["level"], candidate["title_hint"]) for candidate in output["outline_candidates"]],
            [
                ("7", 1, "资格证明文件"),
                ("7.2", 2, "认证证书"),
                ("7.2.2", 3, "机型认证"),
                ("7.2.2.1", 4, "EW10.0-220 设计认证证书"),
            ],
        )

    def test_backfills_fourth_level_body_headings_when_auto_toc_stops_at_third_level(self):
        output = self.run_script([
            paragraph("封面"),
            auto_toc_sdt([
                {"title": "7 资格证明文件", "bookmark": "_Toc5001", "page": 1, "style": "TOC1"},
                {"title": "7.1 资格证明材料", "bookmark": "_Toc5002", "page": 2, "style": "TOC2"},
                {"title": "7.1.1 认证证书", "bookmark": "_Toc5003", "page": 3, "style": "TOC3"},
                {"title": "8 商务偏差表", "bookmark": "_Toc5004", "page": 8, "style": "TOC1"},
            ]),
            paragraph("7 资格证明文件", outline_level=0, runs=[bookmark_start("_Toc5001"), run_text("7 资格证明文件")]),
            paragraph("7.1 资格证明材料", outline_level=1, runs=[bookmark_start("_Toc5002"), run_text("7.1 资格证明材料")]),
            paragraph("7.1.1 认证证书", outline_level=2, runs=[bookmark_start("_Toc5003"), run_text("7.1.1 认证证书")]),
            paragraph("7.1.1.1 EW10.0-220 设计认证证书", outline_level=3),
            paragraph("7.1.1.2 EW6.25-220 型式认证证书", outline_level=3),
            paragraph("8 商务偏差表", outline_level=0, runs=[bookmark_start("_Toc5004"), run_text("8 商务偏差表")]),
            paragraph("7.9.2.100 这是正文编号，不应进入目录"),
        ])

        self.assertEqual(
            [(candidate["number"], candidate["level"], candidate["title_hint"]) for candidate in output["outline_candidates"]],
            [
                ("7", 1, "资格证明文件"),
                ("7.1", 2, "资格证明材料"),
                ("7.1.1", 3, "认证证书"),
                ("7.1.1.1", 4, "EW10.0-220 设计认证证书"),
                ("7.1.1.2", 4, "EW6.25-220 型式认证证书"),
                ("8", 1, "商务偏差表"),
            ],
        )
        self.assertNotIn("这是正文编号", "\n".join(candidate["title_hint"] for candidate in output["outline_candidates"]))


    def test_extracts_outline_candidates_from_plain_toc_page_and_stops_at_body(self):
        output = self.run_script([
            paragraph("封面"),
            paragraph("目 录"),
            paragraph("一、投标函及授权文件	1"),
            paragraph("（一）投标函	2"),
            paragraph("（二）法定代表人授权委托书	3"),
            paragraph("二、资格证明文件 4"),
            paragraph("1. 营业执照 5"),
            paragraph("三、商务偏差表 6"),
            paragraph("商务评分索引表", "Heading1"),
            paragraph("7.9.2.100 华能某项目正文内容 7"),
        ])

        self.assertEqual(output["document_name"], "历史商务标投标文件.docx")
        self.assertEqual(output["outline_source"]["source_type"], "history_bid_toc")
        self.assertEqual(output["outline_source"]["history_document_name"], "历史商务标投标文件.docx")
        self.assertIn("一、投标函及授权文件	1", output["outline_source"]["source_text"])

        candidates = output["outline_candidates"]
        self.assertEqual([candidate["title_hint"] for candidate in candidates], [
            "投标函及授权文件",
            "投标函",
            "法定代表人授权委托书",
            "资格证明文件",
            "营业执照",
            "商务偏差表",
        ])
        self.assertEqual([candidate["number"] for candidate in candidates], [
            "一、",
            "（一）",
            "（二）",
            "二、",
            "1.",
            "三、",
        ])
        self.assertEqual([candidate["level"] for candidate in candidates], [1, 2, 2, 1, 2, 1])
        self.assertNotIn("商务评分索引表", [candidate["title_hint"] for candidate in candidates])
        self.assertNotIn("华能某项目正文内容", "\n".join(candidate["source_text"] for candidate in candidates))

    def test_does_not_treat_numbered_body_paragraphs_as_headings_without_docx_evidence(self):
        output = self.run_script([
            paragraph("封面"),
            paragraph("1.1 投标函"),
            paragraph("3.2 签订产能协议"),
            paragraph("7.9.2.100 华能某项目"),
            paragraph("一、某段正文"),
        ])

        self.assertEqual(output["outline_source"]["source_type"], "history_bid_unknown")
        self.assertEqual(output["outline_candidates"], [])

    def test_falls_back_to_explicit_heading_structure_when_no_toc_exists(self):
        output = self.run_script([
            paragraph("投标函及授权文件", "Heading1"),
            paragraph("投标函", "Heading2"),
            paragraph("法定代表人授权委托书", "Heading2"),
            paragraph("资格证明文件", "Heading1"),
            paragraph("营业执照", "Heading2"),
        ])

        self.assertEqual(output["outline_source"]["source_type"], "history_bid_headings")
        self.assertEqual([candidate["title_hint"] for candidate in output["outline_candidates"]], [
            "投标函及授权文件",
            "投标函",
            "法定代表人授权委托书",
            "资格证明文件",
            "营业执照",
        ])
        self.assertEqual([candidate["number"] for candidate in output["outline_candidates"]], [None, None, None, None, None])
        self.assertEqual([candidate["level"] for candidate in output["outline_candidates"]], [1, 2, 2, 1, 2])
        self.assertEqual(output["outline_candidates"][1]["source_text"], "投标函")

    def test_extracts_heading_numbers_from_explicit_heading_structure(self):
        output = self.run_script([
            paragraph("一、投标函及授权文件", "Heading1"),
            paragraph("1.1 投标函", "Heading2"),
            paragraph("商务评分索引表", "Heading1"),
        ])

        candidates = output["outline_candidates"]
        self.assertEqual([candidate["title_hint"] for candidate in candidates], ["投标函及授权文件", "投标函", "商务评分索引表"])
        self.assertEqual([candidate["number"] for candidate in candidates], ["一、", "1.1", None])

    def test_falls_back_to_outline_level_headings_when_no_toc_exists(self):
        output = self.run_script([
            paragraph("商务评分索引表", outline_level=0),
            paragraph("供货保障专题", outline_level=0),
            paragraph("供应链说明", outline_level=1),
            paragraph("1.1 投标函"),
            paragraph("7.9.2.100 华能某项目正文内容"),
        ])

        self.assertEqual(output["outline_source"]["source_type"], "history_bid_headings")
        self.assertEqual([candidate["title_hint"] for candidate in output["outline_candidates"]], [
            "商务评分索引表",
            "供货保障专题",
            "供应链说明",
        ])
        self.assertEqual([candidate["number"] for candidate in output["outline_candidates"]], [None, None, None])
        self.assertEqual([candidate["level"] for candidate in output["outline_candidates"]], [1, 1, 2])

    def test_candidate_ids_are_unique_after_auto_toc_deep_heading_backfill(self):
        output = self.run_script([
            paragraph("封面"),
            auto_toc_sdt([
                {"title": "7 资格证明文件", "bookmark": "_Toc6001", "page": 1, "style": "TOC1"},
                {"title": "7.1 资格证明材料", "bookmark": "_Toc6002", "page": 2, "style": "TOC2"},
                {"title": "8 商务偏差表", "bookmark": "_Toc6003", "page": 8, "style": "TOC1"},
                {"title": "9 其他材料", "bookmark": "_Toc6004", "page": 9, "style": "TOC1"},
            ]),
            paragraph("7 资格证明文件", outline_level=0, runs=[bookmark_start("_Toc6001"), run_text("7 资格证明文件")]),
            paragraph("7.1 资格证明材料", outline_level=1, runs=[bookmark_start("_Toc6002"), run_text("7.1 资格证明材料")]),
            paragraph("7.1.1.1 EW10.0-220 设计认证证书", outline_level=3),
            paragraph("7.1.1.2 EW6.25-220 型式认证证书", outline_level=3),
            paragraph("8 商务偏差表", outline_level=0, runs=[bookmark_start("_Toc6003"), run_text("8 商务偏差表")]),
            paragraph("9 其他材料", outline_level=0, runs=[bookmark_start("_Toc6004"), run_text("9 其他材料")]),
        ])

        ids = [candidate["candidate_id"] for candidate in output["outline_candidates"]]

        self.assertEqual(ids, [f"hist-cand-{index:03d}" for index in range(1, len(ids) + 1)])
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
