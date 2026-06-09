import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

from app.services.business_template_extractor import (
    build_business_template_boundary_decision_prompt,
    build_business_template_extractor_manifest,
    convert_extractor_appendices,
    run_business_template_extractor,
)


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "opencode" / "skill" / "bid-business-template-extractor" / "scripts" / "run_from_manifest.py"
BTPLBOUND = ROOT / "opencode" / "skill" / "bid-business-template-extractor" / "scripts" / "btplbound_workflow.py"
SKILL_DIR = ROOT / "opencode" / "skill" / "bid-business-template-extractor"
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from scripts.boundary_validator import BoundaryValidationError, validate_boundaries  # noqa: E402


def build_business_format_docx(path: Path) -> None:
    doc = Document()
    doc.add_paragraph("第一章 招标公告")
    doc.add_paragraph("这里不是模板。")
    doc.add_page_break()
    doc.add_paragraph("第六章 投标文件格式")
    doc.add_paragraph("投标函的格式(1A)")
    doc.add_paragraph("致：招标人")
    doc.add_paragraph("投标人(盖公章)：")
    doc.add_paragraph("法定代表人或其委托代理人(签字)：")
    doc.add_paragraph("地址：")
    doc.add_paragraph("电话：")
    doc.add_paragraph("传真：")
    doc.add_paragraph("日期：       年    月   日")
    doc.add_page_break()
    doc.add_paragraph("法定代表人（单位负责人）身份证明：B")
    doc.add_paragraph("姓名：")
    doc.save(path)


def build_boundary_regression_docx(path: Path) -> None:
    doc = Document()
    doc.add_paragraph("第六章 投标文件格式")
    doc.add_paragraph("附件3 货物规格一览表")
    doc.add_paragraph("表3 A")
    doc.add_table(rows=1, cols=2).cell(0, 0).text = "货物名称"
    doc.add_page_break()
    doc.add_paragraph("附件4 商务条款偏差表")
    doc.add_table(rows=1, cols=2).cell(0, 0).text = "条款号"
    doc.add_page_break()
    doc.add_paragraph("附件6 履约保证函格式")
    doc.add_paragraph("履约保证函正文")
    doc.add_page_break()
    doc.add_paragraph("附件7 资格证明文件")
    doc.add_paragraph("附件7A 商务部分摘要表")
    doc.add_table(rows=1, cols=2).cell(0, 0).text = "摘要"
    doc.add_page_break()
    doc.add_paragraph("7D-4表 现金流量表")
    doc.add_table(rows=1, cols=2).cell(0, 0).text = "现金流量"
    doc.add_page_break()
    doc.add_paragraph("附件7E")
    doc.add_paragraph("7E-1表 企业资信等级证书情况")
    doc.add_table(rows=1, cols=2).cell(0, 0).text = "资信"
    doc.add_page_break()
    doc.add_paragraph("开标价格表")
    doc.add_table(rows=1, cols=2).cell(0, 0).text = "开标价"
    doc.add_page_break()
    doc.add_page_break()
    doc.add_paragraph("特殊附件1")
    doc.add_paragraph("保密承诺书")
    doc.add_paragraph("承诺正文")
    doc.save(path)


def build_catalog_listing_regression_docx(path: Path) -> None:
    doc = Document()
    doc.add_paragraph("第六章 投标文件格式")
    doc.add_paragraph("项目名称  （项目名称）")
    doc.add_paragraph("投标文件")
    doc.add_paragraph("投标人：  投标人名称  （盖单位章）")
    paragraph = doc.add_paragraph("法定代表人或其委托代理人：  法定代表人或委托代理人姓名  （签字）")
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in paragraph.runs:
        run.bold = True
    doc.add_paragraph("投标日期")
    doc.add_paragraph("目    录")
    doc.add_paragraph("附件1 投标函、法定代表人（单位负责人）身份证明、法定代表人授权书")
    doc.add_paragraph("附件2 投标价格表")
    paragraph = doc.add_paragraph("附件3 货物规格一览表")
    paragraph.style = "Heading 2"
    doc.add_paragraph("附件4 商务条款偏差表")
    doc.add_paragraph("附件5 投标保证金")
    doc.add_paragraph("附件6 履约保证函")
    doc.add_paragraph("附件7 资格证明文件")
    paragraph = doc.add_paragraph("附件8 开标价格表及报价承诺函")
    paragraph.style = "Heading 2"
    doc.add_paragraph("附件9 投标人需要说明的其他内容")
    doc.add_page_break()
    doc.add_paragraph("附件1 投标函、法定代表人（单位负责人）身份证明、法定代表人授权书格式")
    doc.add_paragraph("投标函的格式(1A)")
    doc.add_paragraph("致：招标人")
    doc.add_paragraph("投标人(盖公章)：")
    doc.add_paragraph("法定代表人或其委托代理人(签字)：")
    doc.add_paragraph("日期：       年    月   日")
    doc.add_page_break()
    doc.add_paragraph("附件3 货物规格一览表")
    paragraph = doc.add_paragraph("表3 A")
    paragraph.style = "Heading 2"
    doc.add_table(rows=1, cols=2).cell(0, 0).text = "货物名称"
    doc.add_page_break()
    doc.add_paragraph("附件8 开标价格表及报价承诺函")
    paragraph = doc.add_paragraph("开标价格表")
    paragraph.style = "Heading 2"
    doc.add_table(rows=1, cols=2).cell(0, 0).text = "开标价"
    doc.save(path)


def build_contract_attachment_and_bid_format_docx(path: Path) -> None:
    doc = Document()
    doc.add_paragraph("第五章 合同条款及格式")
    paragraph = doc.add_paragraph("第三节 合同附件格式")
    paragraph.style = "Heading 1"
    doc.add_paragraph("附件一：合同协议书")
    doc.add_paragraph("合同协议书正文")
    doc.add_page_break()
    doc.add_paragraph("附件二：履约保证金格式")
    doc.add_paragraph("履约保证金正文")
    doc.add_page_break()
    doc.add_paragraph("第六章 投标文件格式")
    doc.add_paragraph("目    录")
    doc.add_paragraph("1. 投标函")
    doc.add_paragraph("2. 法定代表人（单位负责人）身份证明")
    doc.add_page_break()
    paragraph = doc.add_paragraph("投标函")
    paragraph.style = "Heading 1"
    doc.add_paragraph("招标人名称：")
    doc.add_paragraph("投标人：")
    doc.add_paragraph("日期：       年    月   日")
    doc.add_page_break()
    paragraph = doc.add_paragraph("法定代表人（单位负责人）身份证明")
    paragraph.style = "Heading 1"
    doc.add_paragraph("姓名：")
    doc.add_paragraph("职务：")
    doc.save(path)


def build_inline_table_titles_docx(path: Path) -> None:
    doc = Document()
    doc.add_paragraph("第六章 投标文件格式")
    doc.add_page_break()
    paragraph = doc.add_paragraph("投标保证金（如有）")
    paragraph.style = "Heading 1"
    doc.add_paragraph("请提供投标保证金证明材料。")
    doc.add_paragraph("")
    doc.add_paragraph("商务和技术偏差表")
    doc.add_table(rows=1, cols=3).rows[0].cells[0].text = "序号"
    doc.add_paragraph("投标人保证：除偏差表列出的偏差外，响应招标文件全部要求。")
    doc.add_paragraph("")
    doc.add_paragraph("资格审查资料")
    doc.add_paragraph("基本情况表")
    doc.add_table(rows=1, cols=2).rows[0].cells[0].text = "投标人名称"
    doc.add_paragraph("注：投标人应附相关证明材料。")
    doc.add_page_break()
    paragraph = doc.add_paragraph("近年财务状况")
    paragraph.style = "Heading 1"
    doc.add_table(rows=1, cols=2).rows[0].cells[0].text = "年度"
    doc.save(path)


def build_single_block_template_docx(path: Path) -> None:
    doc = Document()
    doc.add_paragraph("第一章 招标公告")
    doc.add_paragraph("这里不是模板。")
    heading = doc.add_paragraph("第六章 投标文件格式")
    heading.style = "Heading 1"

    title_only = doc.add_paragraph("投标人基本情况的其他文件")
    title_only.style = "Heading 1"
    title_only.paragraph_format.page_break_before = True

    next_template = doc.add_paragraph("近年财务状况")
    next_template.style = "Heading 1"
    next_template.paragraph_format.page_break_before = True
    doc.add_table(rows=1, cols=2).rows[0].cells[0].text = "年度"
    doc.add_paragraph("注：投标人应在本表后附相关证明材料。")
    doc.save(path)


def build_appendix_table_title_docx(path: Path) -> None:
    doc = Document()
    doc.add_paragraph("第六章 投标文件格式")
    doc.add_paragraph("附件4 商务条款偏差表")
    doc.add_paragraph("")
    doc.add_table(rows=1, cols=2).rows[0].cells[0].text = "序号"
    doc.add_paragraph("投标人(公章)：")
    doc.save(path)


def build_letter_number_table_title_docx(path: Path) -> None:
    doc = Document()
    doc.add_paragraph("第六章 投标文件格式")
    doc.add_paragraph("7A表 商务部分摘要表")
    doc.add_table(rows=1, cols=2).rows[0].cells[0].text = "评审因素"
    doc.add_paragraph("7B表 股权结构表")
    doc.add_table(rows=1, cols=2).rows[0].cells[0].text = "股东名称"
    doc.save(path)


def build_high_recall_heading_docx(path: Path) -> None:
    doc = Document()
    doc.add_paragraph("第一章 招标公告")
    doc.add_paragraph("这里不是模板。")
    doc.add_page_break()
    heading = doc.add_paragraph("第六章 投标文件格式")
    heading.style = "Heading 1"

    p = doc.add_paragraph("1. 投标函")
    p.style = "Heading 2"
    doc.add_paragraph("致：招标人")

    p = doc.add_paragraph("附件1A 法定代表人身份证明")
    p.style = "Heading 2"
    doc.add_paragraph("姓名：")

    p = doc.add_paragraph("附件1B 授权委托书")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in p.runs:
        run.bold = True
    doc.add_paragraph("委托代理人姓名：")

    doc.add_paragraph("4. 联合体协议书（如有）")
    doc.add_paragraph("所有成员单位自愿组成联合体，共同参加投标。")

    doc.add_paragraph("5. 投标保证金（如有）")
    doc.add_paragraph("请提供投标保证金证明材料。")

    doc.add_paragraph("商务和技术偏差表")
    doc.add_table(rows=1, cols=3).rows[0].cells[0].text = "序号"

    doc.add_paragraph("7. 资格审查资料")
    doc.add_paragraph("基本情况表")
    doc.add_table(rows=1, cols=2).rows[0].cells[0].text = "投标人名称"

    p = doc.add_paragraph("1.1. 近年财务状况")
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    doc.add_table(rows=1, cols=2).rows[0].cells[0].text = "年份"

    doc.add_paragraph("1.2. 近年完成的类似项目情况表")
    doc.add_table(rows=1, cols=2).rows[0].cells[0].text = "项目名称"

    doc.add_paragraph("正在供货和新承接的项目情况表")
    doc.add_table(rows=1, cols=2).rows[0].cells[0].text = "项目名称"

    doc.add_paragraph("近年发生的诉讼及仲裁情况")
    doc.add_table(rows=1, cols=2).rows[0].cells[0].text = "案件名称"

    doc.add_paragraph("7.9. 制造商授权书")
    doc.add_paragraph("制造商授权内容。")

    doc.add_paragraph("8. 其他材料")
    doc.add_paragraph("其他材料正文。")

    doc.add_paragraph("9. 投标设备技术性能指标的详细描述")
    doc.add_paragraph("请详细描述设备技术性能指标。")

    doc.add_paragraph("10. 技术支持资料")
    doc.add_paragraph("请提供技术支持资料。")

    doc.add_paragraph("11. 技术服务和质保期服务计划")
    doc.add_paragraph("请提供技术服务和质保期服务计划。")

    doc.add_paragraph("12. 分项报价表")
    doc.add_table(rows=1, cols=2).rows[0].cells[0].text = "报价项"

    doc.add_paragraph("3.1.1风机设备的分项报价表")
    doc.add_table(rows=1, cols=2).rows[0].cells[0].text = "设备名称"
    doc.save(path)


def docx_text(path: Path) -> str:
    doc = Document(str(path))
    return "\n".join(paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip())


def docx_table_text(path: Path) -> str:
    doc = Document(str(path))
    return "\n".join(cell.text for table in doc.tables for row in table.rows for cell in row.cells)


def docx_edge_summary(path: Path) -> dict[str, object]:
    import zipfile

    from lxml import etree

    word_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    namespaces = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    body = root.find(f"{word_ns}body")
    children = [child for child in (list(body) if body is not None else []) if child.tag != f"{word_ns}sectPr"]

    def text_of(element: object) -> str:
        return "".join(element.xpath(".//w:t/text()", namespaces=namespaces)).strip()

    def is_blank_paragraph(element: object) -> bool:
        return element.tag == f"{word_ns}p" and not text_of(element)

    def has_page_break(element: object) -> bool:
        return bool(element.xpath('.//w:br[@w:type="page"]', namespaces=namespaces))

    def has_page_break_before(element: object) -> bool:
        return bool(element.xpath("./w:pPr/w:pageBreakBefore", namespaces=namespaces))

    def has_paragraph_sect_pr(element: object) -> bool:
        return bool(element.xpath("./w:pPr/w:sectPr", namespaces=namespaces))

    def trailing_blank_count() -> int:
        count = 0
        for child in reversed(children):
            if not is_blank_paragraph(child):
                break
            count += 1
        return count

    content_children = [child for child in children if text_of(child)]

    return {
        "texts": [text_of(child) for child in children if text_of(child)],
        "leadingBlank": bool(children and is_blank_paragraph(children[0])),
        "trailingBlank": bool(children and is_blank_paragraph(children[-1])),
        "trailingBlankCount": trailing_blank_count(),
        "blankParagraphCount": sum(1 for child in children if is_blank_paragraph(child)),
        "firstPageBreakBefore": bool(children and has_page_break_before(children[0])),
        "edgePageBreak": bool(children and (has_page_break(children[0]) or has_page_break(children[-1]))),
        "lastContentHasSectionBreak": bool(content_children and has_paragraph_sect_pr(content_children[-1])),
        "bodySectionBreakCount": len(body.findall(f"{word_ns}sectPr")) if body is not None else 0,
        "bodyPageWidth": (
            body.xpath("./w:sectPr/w:pgSz/@w:w", namespaces=namespaces)[0]
            if body is not None and body.xpath("./w:sectPr/w:pgSz/@w:w", namespaces=namespaces)
            else ""
        ),
    }


def write_manifest(path: Path, *, output_dir: Path, source: Path, **extra: object) -> None:
    payload = {
        "projectId": "proj-test",
        "outputDir": str(output_dir),
        "documents": [
            {
                "id": "DOC-1",
                "name": source.name,
                "sourcePath": str(source),
            }
        ],
    }
    payload.update(extra)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_manifest(manifest: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNNER), str(manifest)],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )


def run_btplbound(*args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(BTPLBOUND), *(str(arg) for arg in args)],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )


def stdout_json(completed: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(completed.stdout)


def block_id_by_text(blocks: list[dict], text_part: str) -> int:
    return next(int(block["blockId"]) for block in blocks if text_part in str(block.get("text") or ""))


def write_heading_role_decisions_for_boundary_reference_test(
    temp_dir: Path,
    manifest: Path,
    output_dir: Path,
) -> None:
    candidates = json.loads((output_dir / "DOC-1" / "candidate_templates.json").read_text(encoding="utf-8"))

    def role_for(text: str) -> tuple[bool, str, str]:
        if any(
            title in text
            for title in (
                "制造商授权书",
                "投标设备技术性能指标的详细描述",
                "技术支持资料",
                "技术服务和质保期服务计划",
                "分项报价表",
            )
        ):
            return True, "template_start", ""
        if "资格审查资料" in text:
            return False, "section_container", ""
        if "其他材料" in text:
            return False, "boundary_only", ""
        return False, "reject", "非测试关注标题"

    by_id = {item["candidateId"]: item for item in candidates}
    while True:
        status = stdout_json(run_btplbound("status", manifest))
        if status["candidate"]["decided"] == status["candidate"]["total"]:
            break
        batch = stdout_json(run_btplbound("candidate-batch", manifest, "next"))
        decision_path = temp_dir / f"candidate-{batch['batchNo']}.json"
        decisions = []
        for item in batch["candidates"]:
            is_template, heading_role, reject_reason = role_for(item["text"])
            decisions.append(
                {
                    "candidateId": item["candidateId"],
                    "isTemplateStart": is_template,
                    "headingRole": heading_role,
                    "rejectReason": reject_reason,
                    "templateTitle": by_id[item["candidateId"]]["text"],
                    "templateType": "business_template" if is_template else "",
                    "confidence": 0.9,
                    "reason": "测试边界参考集合",
                    "needsReview": False,
                }
            )
        decision_path.write_text(json.dumps({"decisions": decisions}, ensure_ascii=False), encoding="utf-8")
        completed = run_btplbound("candidate-decision", manifest, batch["batchNo"], decision_path)
        if completed.returncode != 0:
            raise AssertionError(completed.stderr)


def write_wenxi_heading_role_decisions(temp_dir: Path, manifest: Path, output_dir: Path) -> None:
    template_titles = (
        "联合体协议书（如有）",
        "投标保证金（如有）",
        "商务和技术偏差表",
        "基本情况表",
        "近年财务状况",
        "近年完成的类似项目情况表",
        "正在供货和新承接的项目情况表",
        "近年发生的诉讼及仲裁情况",
        "制造商授权书",
        "投标设备技术性能指标的详细描述",
        "技术支持资料",
        "技术服务和质保期服务计划",
        "分项报价表",
        "3.1.1风机设备的分项报价表",
    )
    candidates = json.loads((output_dir / "DOC-1" / "candidate_templates.json").read_text(encoding="utf-8"))
    by_id = {item["candidateId"]: item for item in candidates}

    def template_title(text: str) -> str:
        for title in template_titles:
            if title in text:
                return title
        return text

    while True:
        status = stdout_json(run_btplbound("status", manifest))
        if status["candidate"]["decided"] == status["candidate"]["total"]:
            break
        batch = stdout_json(run_btplbound("candidate-batch", manifest, "next"))
        decision_path = temp_dir / f"wenxi-candidate-{batch['batchNo']}.json"
        decisions = []
        for item in batch["candidates"]:
            text = item["text"]
            is_template = any(title in text for title in template_titles)
            is_section = "资格审查资料" in text
            is_boundary = "其他材料" in text
            decisions.append(
                {
                    "candidateId": item["candidateId"],
                    "isTemplateStart": is_template,
                    "headingRole": "template_start" if is_template else "section_container" if is_section else "boundary_only" if is_boundary else "reject",
                    "rejectReason": "" if (is_template or is_section or is_boundary) else "非闻喜回归关注标题",
                    "templateTitle": template_title(by_id[item["candidateId"]]["text"]),
                    "templateType": "business_template" if is_template else "",
                    "confidence": 0.9,
                    "reason": "闻喜型回归模拟 AI 标题角色裁决",
                    "needsReview": False,
                }
            )
        decision_path.write_text(json.dumps({"decisions": decisions}, ensure_ascii=False), encoding="utf-8")
        completed = run_btplbound("candidate-decision", manifest, batch["batchNo"], decision_path)
        if completed.returncode != 0:
            raise AssertionError(completed.stderr)


def write_valid_boundary_decisions_for_all_batches(temp_dir: Path, manifest: Path) -> None:
    while True:
        status = stdout_json(run_btplbound("status", manifest))
        if status["boundary"]["decided"] == status["boundary"]["total"]:
            break
        batch = stdout_json(run_btplbound("boundary-batch", manifest, "next"))
        decision_path = temp_dir / f"boundary-{batch['batchNo']}.json"
        decisions = []
        for template in batch["templates"]:
            decisions.append(
                {
                    "candidateId": template["candidateId"],
                    "startBlockId": template["suggestedStartBlockId"],
                    "endBlockId": template["maxEndBlockId"],
                    "confidence": 0.9,
                    "reason": "测试使用最大允许边界，验证不会跨越边界参考标题",
                    "needsReview": False,
                }
            )
        decision_path.write_text(json.dumps({"decisions": decisions}, ensure_ascii=False), encoding="utf-8")
        completed = run_btplbound("boundary-decision", manifest, batch["batchNo"], decision_path)
        if completed.returncode != 0:
            raise AssertionError(completed.stderr)


class BusinessTemplateExtractorSkillScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="business-template-extractor-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_prepare_writes_candidate_artifacts_and_does_not_slice(self) -> None:
        source = self.temp_dir / "prepare.docx"
        output_dir = self.temp_dir / "prepare-output"
        manifest = self.temp_dir / "prepare-manifest.json"
        build_business_format_docx(source)
        write_manifest(manifest, output_dir=output_dir, source=source, stage="prepare")

        completed = run_manifest(manifest)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads((output_dir / "business_template_extraction.json").read_text(encoding="utf-8"))
        document_output = output_dir / "DOC-1"
        self.assertTrue((document_output / "blocks.json").is_file())
        self.assertTrue((document_output / "regions.json").is_file())
        self.assertTrue((document_output / "excluded_regions.json").is_file())
        self.assertTrue((document_output / "candidate_templates.json").is_file())
        self.assertTrue((document_output / "candidate_windows.json").is_file())
        self.assertFalse((document_output / "boundaries.json").exists())
        self.assertFalse((document_output / "templates").exists())
        self.assertEqual(payload["appendices"], [])
        self.assertEqual(payload["summary"]["templateCount"], 0)
        candidates = json.loads((document_output / "candidate_templates.json").read_text(encoding="utf-8"))
        windows = json.loads((document_output / "candidate_windows.json").read_text(encoding="utf-8"))
        self.assertTrue(any("投标函" in item["text"] for item in candidates), candidates)
        self.assertTrue(all(item.get("candidateId") for item in windows), windows)
        self.assertEqual(
            [item["candidateId"] for item in windows],
            [item["candidateId"] for item in candidates],
        )

    def test_prepare_exposes_high_recall_headings_for_ai_decision(self) -> None:
        source = self.temp_dir / "high-recall-headings.docx"
        output_dir = self.temp_dir / "high-recall-output"
        manifest = self.temp_dir / "high-recall-manifest.json"
        build_high_recall_heading_docx(source)
        write_manifest(manifest, output_dir=output_dir, source=source, stage="prepare")

        completed = run_manifest(manifest)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        candidates = json.loads((output_dir / "DOC-1" / "candidate_templates.json").read_text(encoding="utf-8"))
        texts = [item["text"] for item in candidates]
        expected = [
            "联合体协议书（如有）",
            "投标保证金（如有）",
            "商务和技术偏差表",
            "资格审查资料",
            "基本情况表",
            "近年财务状况",
            "近年完成的类似项目情况表",
            "正在供货和新承接的项目情况表",
            "近年发生的诉讼及仲裁情况",
            "制造商授权书",
            "其他材料",
            "投标设备技术性能指标的详细描述",
            "技术支持资料",
            "技术服务和质保期服务计划",
            "分项报价表",
            "3.1.1风机设备的分项报价表",
        ]
        for title in expected:
            self.assertTrue(any(title in text for text in texts), title)

    def test_finalize_without_agent_decisions_does_not_slice_by_default(self) -> None:
        source = self.temp_dir / "missing-decisions.docx"
        output_dir = self.temp_dir / "missing-decisions-output"
        manifest = self.temp_dir / "missing-decisions-manifest.json"
        build_business_format_docx(source)
        write_manifest(manifest, output_dir=output_dir, source=source)

        completed = run_manifest(manifest)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads((output_dir / "business_template_extraction.json").read_text(encoding="utf-8"))
        document_output = output_dir / "DOC-1"
        self.assertEqual(payload["appendices"], [])
        self.assertEqual(payload["summary"]["templateCount"], 0)
        self.assertFalse((document_output / "templates").exists())
        self.assertTrue(any("缺少 agent 裁决" in item["message"] for item in payload["warnings"]))
        self.assertFalse(payload["quality"]["scriptFallbackUsed"])

    def test_runner_accepts_utf8_bom_manifest(self) -> None:
        source = self.temp_dir / "bom-manifest.docx"
        output_dir = self.temp_dir / "bom-manifest-output"
        manifest = self.temp_dir / "bom-manifest.json"
        build_business_format_docx(source)
        payload = {
            "projectId": "proj-bom",
            "outputDir": str(output_dir),
            "stage": "prepare",
            "documents": [
                {
                    "id": "DOC-1",
                    "name": source.name,
                    "sourcePath": str(source),
                }
            ],
        }
        manifest.write_bytes(b"\xef\xbb\xbf" + json.dumps(payload, ensure_ascii=False).encode("utf-8"))

        completed = run_manifest(manifest)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue((output_dir / "business_template_extraction.json").is_file())

    def test_finalize_uses_agent_decisions_instead_of_script_boundaries(self) -> None:
        source = self.temp_dir / "agent-decisions.docx"
        output_dir = self.temp_dir / "agent-decisions-output"
        prepare_manifest = self.temp_dir / "agent-decisions-prepare.json"
        finalize_manifest = self.temp_dir / "agent-decisions-finalize.json"
        build_business_format_docx(source)
        write_manifest(prepare_manifest, output_dir=output_dir, source=source, stage="prepare")
        self.assertEqual(run_manifest(prepare_manifest).returncode, 0)

        document_output = output_dir / "DOC-1"
        blocks = json.loads((document_output / "blocks.json").read_text(encoding="utf-8"))
        candidates = json.loads((document_output / "candidate_templates.json").read_text(encoding="utf-8"))
        candidate = next(item for item in candidates if "投标函" in item["text"])
        decision = {
            "schemaVersion": "bid-business-template-extractor-boundary-decisions-v1",
            "decider": "executing_agent",
            "decisions": [
                {
                    "candidateId": "CAND-CATALOG",
                    "candidateBlockId": block_id_by_text(blocks, "第六章 投标文件格式"),
                    "isTemplateStart": False,
                    "rejectReason": "目录项不是模板。",
                    "templateTitle": "附件2 投标价格表",
                    "templateType": "",
                    "startBlockId": None,
                    "endBlockId": None,
                    "confidence": 0.8,
                    "reason": "目录项不是模板。",
                    "needsReview": False,
                },
                {
                    "candidateId": candidate["candidateId"],
                    "candidateBlockId": candidate["candidateBlockId"],
                    "isTemplateStart": True,
                    "rejectReason": "",
                    "templateTitle": "AGENT裁决投标函",
                    "templateType": "bid_letter",
                    "startBlockId": block_id_by_text(blocks, "投标函的格式"),
                    "endBlockId": block_id_by_text(blocks, "日期："),
                    "confidence": 0.92,
                    "reason": "标题后有正文和签章字段，遇到下一个模板标题前截断。",
                    "needsReview": False,
                }
            ],
        }
        (document_output / "llm_boundary_decisions.json").write_text(
            json.dumps(decision, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        write_manifest(finalize_manifest, output_dir=output_dir, source=source, stage="finalize")

        completed = run_manifest(finalize_manifest)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads((output_dir / "business_template_extraction.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["summary"]["templateCount"], 1)
        self.assertEqual(payload["appendices"][0]["title"], "AGENT裁决投标函")
        self.assertEqual(payload["quality"]["agentDecisionCount"], 2)
        self.assertEqual(payload["quality"]["agentRejectedCount"], 1)
        self.assertEqual(payload["quality"]["catalogRejectedCount"], 1)
        self.assertFalse(payload["quality"]["scriptFallbackUsed"])
        boundaries = json.loads((document_output / "boundaries.json").read_text(encoding="utf-8"))
        self.assertEqual(boundaries["templates"][0]["decisionSource"], "executing_agent")
        self.assertEqual(boundaries["templates"][0]["endBlockId"], block_id_by_text(blocks, "日期："))

    def test_btplbound_batches_candidate_and_boundary_decisions_then_finalizes(self) -> None:
        source = self.temp_dir / "btplbound.docx"
        output_dir = self.temp_dir / "btplbound-output"
        manifest = self.temp_dir / "btplbound-manifest.json"
        build_business_format_docx(source)
        write_manifest(manifest, output_dir=output_dir, source=source, stage="prepare")
        self.assertEqual(run_manifest(manifest).returncode, 0)

        status = stdout_json(run_btplbound("status", manifest))
        self.assertGreaterEqual(status["candidate"]["total"], 2)
        self.assertEqual(status["candidate"]["decided"], 0)
        self.assertEqual(status["boundary"]["decided"], 0)

        candidate_batch = stdout_json(run_btplbound("candidate-batch", manifest, "next"))
        self.assertEqual(candidate_batch["batchNo"], 1)
        self.assertEqual(len(candidate_batch["candidates"]), min(status["candidate"]["total"], candidate_batch["batchSize"]))
        self.assertLessEqual(candidate_batch["batchSize"], 8)
        first_candidate = candidate_batch["candidates"][0]
        self.assertTrue(any("投标函" in item["text"] for item in candidate_batch["candidates"]))
        self.assertIn("evidenceBlocks", first_candidate)
        self.assertNotIn("candidateWindows", candidate_batch)

        candidate_decision = self.temp_dir / "candidate-decision.json"
        candidate_decision.write_text(
            json.dumps(
                {
                    "decisions": [
                        {
                            "candidateId": first_candidate["candidateId"],
                            "isTemplateStart": True,
                            "templateTitle": "Agent Bid Letter",
                            "templateType": "bid_letter",
                            "confidence": 0.92,
                            "reason": "title has body fields",
                            "needsReview": False,
                        },
                        {
                            "candidateId": candidate_batch["candidates"][1]["candidateId"],
                            "isTemplateStart": False,
                            "rejectReason": "catalog-only or weak evidence",
                            "templateTitle": candidate_batch["candidates"][1]["text"],
                            "templateType": "",
                            "confidence": 0.81,
                            "reason": "not a standalone template",
                            "needsReview": False,
                        },
                        *[
                            {
                                "candidateId": item["candidateId"],
                                "isTemplateStart": False,
                                "rejectReason": "not used in this compatibility test",
                                "templateTitle": item["text"],
                                "templateType": "",
                                "confidence": 0.8,
                                "reason": "not a standalone template in this test",
                                "needsReview": False,
                            }
                            for item in candidate_batch["candidates"][2:]
                        ],
                    ]
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        saved_candidate = stdout_json(run_btplbound("candidate-decision", manifest, 1, candidate_decision))
        self.assertEqual(saved_candidate["acceptedCount"], 1)
        self.assertEqual(saved_candidate["rejectedCount"], len(candidate_batch["candidates"]) - 1)

        boundary_batch = stdout_json(run_btplbound("boundary-batch", manifest, "next"))
        self.assertEqual(boundary_batch["batchNo"], 1)
        self.assertEqual(len(boundary_batch["templates"]), 1)
        template = boundary_batch["templates"][0]
        self.assertEqual(template["candidateId"], first_candidate["candidateId"])
        self.assertIn("boundaryEvidenceBlocks", template)

        boundary_decision = self.temp_dir / "boundary-decision.json"
        boundary_decision.write_text(
            json.dumps(
                {
                    "decisions": [
                        {
                            "candidateId": first_candidate["candidateId"],
                            "startBlockId": template["candidateBlockId"],
                            "endBlockId": template["candidateBlockId"] + 7,
                            "confidence": 0.9,
                            "reason": "ends before next true template",
                            "needsReview": False,
                        }
                    ]
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        saved_boundary = stdout_json(run_btplbound("boundary-decision", manifest, 1, boundary_decision))
        self.assertEqual(saved_boundary["acceptedCount"], 1)

        final = stdout_json(run_btplbound("finalize", manifest))
        self.assertEqual(final["schemaVersion"], "bid-business-template-extractor-boundary-decisions-v1")
        self.assertEqual(final["summary"]["decisionCount"], status["candidate"]["total"])
        self.assertEqual(final["summary"]["acceptedTemplateCount"], 1)
        decision_file = Path(final["decisionFiles"][0])
        self.assertTrue(decision_file.is_file())
        decisions = json.loads(decision_file.read_text(encoding="utf-8"))
        self.assertEqual(decisions["decider"], "executing_agent")
        accepted = [item for item in decisions["decisions"] if item["isTemplateStart"]]
        rejected = [item for item in decisions["decisions"] if not item["isTemplateStart"]]
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(rejected), status["candidate"]["total"] - 1)
        self.assertEqual(accepted[0]["templateTitle"], "Agent Bid Letter")
        self.assertGreaterEqual(accepted[0]["endBlockId"], accepted[0]["startBlockId"])

    def test_btplbound_accepts_single_block_title_only_template(self) -> None:
        source = self.temp_dir / "single-block-template.docx"
        output_dir = self.temp_dir / "single-block-template-output"
        manifest = self.temp_dir / "single-block-template-manifest.json"
        build_single_block_template_docx(source)
        write_manifest(manifest, output_dir=output_dir, source=source, stage="prepare")
        self.assertEqual(run_manifest(manifest).returncode, 0)

        document_output = output_dir / "DOC-1"
        candidates = json.loads((document_output / "candidate_templates.json").read_text(encoding="utf-8"))
        title_only = next(item for item in candidates if "投标人基本情况的其他文件" in item["text"])
        financial = next(item for item in candidates if "近年财务状况" in item["text"])

        while True:
            status = stdout_json(run_btplbound("status", manifest))
            if status["candidate"]["decided"] == status["candidate"]["total"]:
                break
            batch = stdout_json(run_btplbound("candidate-batch", manifest, "next"))
            decision_path = self.temp_dir / f"single-block-candidate-{batch['batchNo']}.json"
            decisions = []
            for item in batch["candidates"]:
                is_title_only = item["candidateId"] == title_only["candidateId"]
                is_financial = item["candidateId"] == financial["candidateId"]
                decisions.append(
                    {
                        "candidateId": item["candidateId"],
                        "isTemplateStart": is_title_only or is_financial,
                        "headingRole": "template_start" if (is_title_only or is_financial) else "reject",
                        "rejectReason": "" if (is_title_only or is_financial) else "非模板标题",
                        "templateTitle": item["text"],
                        "templateType": "attachment_placeholder" if is_title_only else "financial_status_table" if is_financial else "",
                        "confidence": 0.95,
                        "reason": "单块标题模板可作为附件占位模板" if is_title_only else "后接财务表格" if is_financial else "非测试关注标题",
                        "needsReview": False,
                    }
                )
            decision_path.write_text(json.dumps({"decisions": decisions}, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(run_btplbound("candidate-decision", manifest, batch["batchNo"], decision_path).returncode, 0)

        boundary_batch = stdout_json(run_btplbound("boundary-batch", manifest, "next"))
        title_template = next(item for item in boundary_batch["templates"] if item["candidateId"] == title_only["candidateId"])
        self.assertEqual(title_template["suggestedStartBlockId"], title_template["maxEndBlockId"])

        boundary_path = self.temp_dir / "single-block-boundary.json"
        boundary_path.write_text(
            json.dumps(
                {
                    "decisions": [
                        {
                            "candidateId": template["candidateId"],
                            "startBlockId": template["suggestedStartBlockId"],
                            "endBlockId": template["maxEndBlockId"],
                            "confidence": 0.95,
                            "reason": "使用 btplbound 给出的最大合法边界，单块标题模板允许 start=end",
                            "needsReview": False,
                        }
                        for template in boundary_batch["templates"]
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        saved_boundary = stdout_json(run_btplbound("boundary-decision", manifest, boundary_batch["batchNo"], boundary_path))
        self.assertGreaterEqual(saved_boundary["acceptedCount"], 1)
        final = stdout_json(run_btplbound("finalize", manifest))
        decision_file = Path(final["decisionFiles"][0])
        self.assertTrue(decision_file.is_file())
        decisions = json.loads(decision_file.read_text(encoding="utf-8"))["decisions"]
        single_decision = next(item for item in decisions if item["candidateId"] == title_only["candidateId"])
        self.assertEqual(single_decision["startBlockId"], single_decision["endBlockId"])

        finalize_manifest = self.temp_dir / "single-block-finalize.json"
        write_manifest(finalize_manifest, output_dir=output_dir, source=source, stage="finalize")
        completed = run_manifest(finalize_manifest)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads((output_dir / "business_template_extraction.json").read_text(encoding="utf-8"))
        titles = [item["title"] for item in payload["appendices"]]
        self.assertIn("投标人基本情况的其他文件", titles)
        boundaries = json.loads((document_output / "boundaries.json").read_text(encoding="utf-8"))
        single_template = next(item for item in boundaries["templates"] if item["title"] == "投标人基本情况的其他文件")
        self.assertEqual(single_template["blockCount"], 1)
        self.assertTrue((document_output / single_template["outputPath"]).is_file())

    def test_btplbound_candidate_decision_preserves_heading_roles(self) -> None:
        source = self.temp_dir / "heading-roles.docx"
        output_dir = self.temp_dir / "heading-roles-output"
        manifest = self.temp_dir / "heading-roles-manifest.json"
        build_high_recall_heading_docx(source)
        write_manifest(manifest, output_dir=output_dir, source=source, stage="prepare")
        self.assertEqual(run_manifest(manifest).returncode, 0)

        total_boundary_references = 0
        while True:
            status = stdout_json(run_btplbound("status", manifest))
            if status["candidate"]["decided"] == status["candidate"]["total"]:
                break
            batch = stdout_json(run_btplbound("candidate-batch", manifest, "next"))
            decision_file = self.temp_dir / f"heading-role-decision-{batch['batchNo']}.json"
            decision_file.write_text(
                json.dumps(
                    {
                        "decisions": [
                            {
                                "candidateId": item["candidateId"],
                                "isTemplateStart": "基本情况表" in item["text"],
                                "headingRole": (
                                    "section_container" if "资格审查资料" in item["text"]
                                    else "boundary_only" if "其他材料" in item["text"]
                                    else "template_start" if "基本情况表" in item["text"]
                                    else "reject"
                                ),
                                "rejectReason": "" if (
                                    "基本情况表" in item["text"]
                                    or "资格审查资料" in item["text"]
                                    or "其他材料" in item["text"]
                                ) else "不是本测试关注标题",
                                "templateTitle": item["text"],
                                "templateType": "business_template" if "基本情况表" in item["text"] else "",
                                "confidence": 0.86,
                                "reason": "测试标题角色裁决保存",
                                "needsReview": False,
                            }
                            for item in batch["candidates"]
                        ]
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            saved = stdout_json(run_btplbound("candidate-decision", manifest, batch["batchNo"], decision_file))
            total_boundary_references += saved["boundaryReferenceCount"]

        roles = []
        for path in (output_dir / "DOC-1" / "agent_decision_batches").glob("candidate_decision_batch_*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            roles.extend(item["headingRole"] for item in payload["decisions"])

        self.assertGreaterEqual(total_boundary_references, 3)
        self.assertIn("template_start", roles)
        self.assertIn("section_container", roles)
        self.assertIn("boundary_only", roles)
        self.assertIn("reject", roles)

    def test_boundary_batch_uses_boundary_only_heading_to_stop_previous_template(self) -> None:
        source = self.temp_dir / "boundary-reference.docx"
        output_dir = self.temp_dir / "boundary-reference-output"
        manifest = self.temp_dir / "boundary-reference-manifest.json"
        build_high_recall_heading_docx(source)
        write_manifest(manifest, output_dir=output_dir, source=source, stage="prepare")
        self.assertEqual(run_manifest(manifest).returncode, 0)

        all_candidates = json.loads((output_dir / "DOC-1" / "candidate_templates.json").read_text(encoding="utf-8"))

        def candidate_containing(text: str) -> dict:
            return next(item for item in all_candidates if text in item["text"])

        manufacturer = candidate_containing("制造商授权书")
        other = candidate_containing("其他材料")
        commitment = candidate_containing("投标设备技术性能指标的详细描述")

        while True:
            status = stdout_json(run_btplbound("status", manifest))
            if status["candidate"]["decided"] == status["candidate"]["total"]:
                break
            batch = stdout_json(run_btplbound("candidate-batch", manifest, "next"))
            decision_path = self.temp_dir / f"candidate-{batch['batchNo']}.json"
            decisions = []
            for item in batch["candidates"]:
                is_manufacturer = item["candidateId"] == manufacturer["candidateId"]
                is_other = item["candidateId"] == other["candidateId"]
                is_commitment = item["candidateId"] == commitment["candidateId"]
                decisions.append(
                    {
                        "candidateId": item["candidateId"],
                        "isTemplateStart": is_manufacturer or is_commitment,
                        "headingRole": "template_start" if (is_manufacturer or is_commitment) else "boundary_only" if is_other else "reject",
                        "rejectReason": "" if (is_manufacturer or is_commitment or is_other) else "非测试关注标题",
                        "templateTitle": item["text"],
                        "templateType": "business_template" if (is_manufacturer or is_commitment) else "",
                        "confidence": 0.9,
                        "reason": "测试边界参考集合",
                        "needsReview": False,
                    }
                )
            decision_path.write_text(json.dumps({"decisions": decisions}, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(run_btplbound("candidate-decision", manifest, batch["batchNo"], decision_path).returncode, 0)

        boundary_batch = stdout_json(run_btplbound("boundary-batch", manifest, "next"))
        manufacturer_template = next(item for item in boundary_batch["templates"] if item["candidateId"] == manufacturer["candidateId"])

        self.assertLess(manufacturer_template["maxEndBlockId"], int(other["candidateBlockId"]))

    def test_boundary_batch_includes_next_boundary_reference_summary(self) -> None:
        source = self.temp_dir / "boundary-summary.docx"
        output_dir = self.temp_dir / "boundary-summary-output"
        manifest = self.temp_dir / "boundary-summary-manifest.json"
        build_high_recall_heading_docx(source)
        write_manifest(manifest, output_dir=output_dir, source=source, stage="prepare")
        self.assertEqual(run_manifest(manifest).returncode, 0)

        write_heading_role_decisions_for_boundary_reference_test(self.temp_dir, manifest, output_dir)

        boundary_batch = stdout_json(run_btplbound("boundary-batch", manifest, "next"))
        manufacturer_template = next(item for item in boundary_batch["templates"] if "制造商授权书" in item["templateTitle"])

        self.assertIn("nextBoundaryReference", manufacturer_template)
        self.assertIn("其他材料", manufacturer_template["nextBoundaryReference"]["text"])

    def test_finalize_reports_boundary_reference_counts(self) -> None:
        source = self.temp_dir / "finalize-boundary-reference.docx"
        output_dir = self.temp_dir / "finalize-boundary-reference-output"
        manifest = self.temp_dir / "finalize-boundary-reference-manifest.json"
        build_high_recall_heading_docx(source)
        write_manifest(manifest, output_dir=output_dir, source=source, stage="prepare")
        self.assertEqual(run_manifest(manifest).returncode, 0)

        write_heading_role_decisions_for_boundary_reference_test(self.temp_dir, manifest, output_dir)
        write_valid_boundary_decisions_for_all_batches(self.temp_dir, manifest)

        final = stdout_json(run_btplbound("finalize", manifest))

        self.assertIn("boundaryReferenceCount", final["summary"])
        self.assertGreater(final["summary"]["boundaryReferenceCount"], final["summary"]["acceptedTemplateCount"])

    def test_wenxi_like_ai_heading_roles_extract_expected_templates_without_merging(self) -> None:
        source = self.temp_dir / "wenxi-like.docx"
        output_dir = self.temp_dir / "wenxi-like-output"
        manifest = self.temp_dir / "wenxi-like-manifest.json"
        build_high_recall_heading_docx(source)
        write_manifest(manifest, output_dir=output_dir, source=source, stage="prepare")
        self.assertEqual(run_manifest(manifest).returncode, 0)

        write_wenxi_heading_role_decisions(self.temp_dir, manifest, output_dir)
        write_valid_boundary_decisions_for_all_batches(self.temp_dir, manifest)
        self.assertEqual(run_btplbound("finalize", manifest).returncode, 0)

        finalize_manifest = self.temp_dir / "wenxi-like-finalize.json"
        write_manifest(finalize_manifest, output_dir=output_dir, source=source, stage="finalize")
        completed = run_manifest(finalize_manifest)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads((output_dir / "business_template_extraction.json").read_text(encoding="utf-8"))
        titles = [item["title"] for item in payload["appendices"]]
        self.assertIn("联合体协议书（如有）", titles)
        self.assertIn("投标保证金（如有）", titles)
        self.assertIn("商务和技术偏差表", titles)
        self.assertIn("基本情况表", titles)
        self.assertIn("近年完成的类似项目情况表", titles)
        self.assertIn("正在供货和新承接的项目情况表", titles)
        self.assertIn("投标设备技术性能指标的详细描述", titles)
        self.assertIn("技术支持资料", titles)
        self.assertIn("技术服务和质保期服务计划", titles)
        self.assertIn("分项报价表", titles)

        document_output = output_dir / "DOC-1"
        blocks = json.loads((document_output / "blocks.json").read_text(encoding="utf-8"))
        boundaries = json.loads((document_output / "boundaries.json").read_text(encoding="utf-8"))
        by_title = {item["title"]: item for item in boundaries["templates"]}
        self.assertLess(by_title["制造商授权书"]["endBlockId"], block_id_by_text(blocks, "其他材料"))

    def test_btplbound_rejects_invalid_boundary_decision_before_final_file(self) -> None:
        source = self.temp_dir / "btplbound-invalid.docx"
        output_dir = self.temp_dir / "btplbound-invalid-output"
        manifest = self.temp_dir / "btplbound-invalid-manifest.json"
        build_business_format_docx(source)
        write_manifest(manifest, output_dir=output_dir, source=source, stage="prepare")
        self.assertEqual(run_manifest(manifest).returncode, 0)

        candidate_batch = stdout_json(run_btplbound("candidate-batch", manifest, "next"))
        first_candidate = candidate_batch["candidates"][0]
        candidate_decision = self.temp_dir / "invalid-candidate-decision.json"
        candidate_decision.write_text(
            json.dumps(
                {
                    "decisions": [
                        {
                            "candidateId": first_candidate["candidateId"],
                            "isTemplateStart": True,
                            "templateTitle": "Agent Bid Letter",
                            "templateType": "bid_letter",
                            "confidence": 0.92,
                            "reason": "title has body fields",
                            "needsReview": False,
                        },
                        *[
                            {
                                "candidateId": item["candidateId"],
                                "isTemplateStart": False,
                                "rejectReason": "not used in this validation case",
                                "templateTitle": item["text"],
                                "templateType": "",
                                "confidence": 0.8,
                                "reason": "not a standalone template",
                                "needsReview": False,
                            }
                            for item in candidate_batch["candidates"][1:]
                        ],
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.assertEqual(run_btplbound("candidate-decision", manifest, 1, candidate_decision).returncode, 0)

        boundary_decision = self.temp_dir / "invalid-boundary-decision.json"
        boundary_decision.write_text(
            json.dumps(
                {
                    "decisions": [
                        {
                            "candidateId": first_candidate["candidateId"],
                            "startBlockId": first_candidate["candidateBlockId"],
                            "endBlockId": first_candidate["candidateBlockId"] - 1,
                            "confidence": 0.9,
                            "reason": "invalid end",
                            "needsReview": False,
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        completed = run_btplbound("boundary-decision", manifest, 1, boundary_decision)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("endBlockId", completed.stderr)
        document_output = output_dir / "DOC-1"
        self.assertFalse((document_output / "llm_boundary_decisions.json").exists())

    def test_low_confidence_agent_decision_goes_to_review_without_docx_slice(self) -> None:
        source = self.temp_dir / "low-confidence.docx"
        output_dir = self.temp_dir / "low-confidence-output"
        prepare_manifest = self.temp_dir / "low-confidence-prepare.json"
        finalize_manifest = self.temp_dir / "low-confidence-finalize.json"
        build_business_format_docx(source)
        write_manifest(prepare_manifest, output_dir=output_dir, source=source, stage="prepare")
        self.assertEqual(run_manifest(prepare_manifest).returncode, 0)

        document_output = output_dir / "DOC-1"
        blocks = json.loads((document_output / "blocks.json").read_text(encoding="utf-8"))
        candidates = json.loads((document_output / "candidate_templates.json").read_text(encoding="utf-8"))
        candidate = next(item for item in candidates if "投标函" in item["text"])
        (document_output / "llm_boundary_decisions.json").write_text(
            json.dumps(
                {
                    "schemaVersion": "bid-business-template-extractor-boundary-decisions-v1",
                    "decider": "executing_agent",
                    "decisions": [
                        {
                            "candidateId": candidate["candidateId"],
                            "candidateBlockId": candidate["candidateBlockId"],
                            "isTemplateStart": True,
                            "rejectReason": "",
                            "templateTitle": "低置信度投标函",
                            "templateType": "bid_letter",
                            "startBlockId": block_id_by_text(blocks, "投标函的格式"),
                            "endBlockId": block_id_by_text(blocks, "日期："),
                            "confidence": 0.7,
                            "reason": "标题和正文较弱，需人工复核。",
                            "needsReview": True,
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        write_manifest(finalize_manifest, output_dir=output_dir, source=source, stage="finalize")

        completed = run_manifest(finalize_manifest)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads((output_dir / "business_template_extraction.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["appendices"], [])
        self.assertEqual(payload["quality"]["lowConfidenceCount"], 1)
        self.assertFalse((document_output / "templates").exists())
        review = (document_output / "review.md").read_text(encoding="utf-8")
        self.assertIn("低置信度投标函", review)
        self.assertIn("低置信度", review)

    def test_needs_review_agent_decision_goes_to_review_without_docx_slice(self) -> None:
        source = self.temp_dir / "needs-review.docx"
        output_dir = self.temp_dir / "needs-review-output"
        prepare_manifest = self.temp_dir / "needs-review-prepare.json"
        finalize_manifest = self.temp_dir / "needs-review-finalize.json"
        build_business_format_docx(source)
        write_manifest(prepare_manifest, output_dir=output_dir, source=source, stage="prepare")
        self.assertEqual(run_manifest(prepare_manifest).returncode, 0)

        document_output = output_dir / "DOC-1"
        blocks = json.loads((document_output / "blocks.json").read_text(encoding="utf-8"))
        candidates = json.loads((document_output / "candidate_templates.json").read_text(encoding="utf-8"))
        candidate = next(item for item in candidates if "投标函" in item["text"])
        (document_output / "llm_boundary_decisions.json").write_text(
            json.dumps(
                {
                    "schemaVersion": "bid-business-template-extractor-boundary-decisions-v1",
                    "decider": "executing_agent",
                    "decisions": [
                        {
                            "candidateId": candidate["candidateId"],
                            "candidateBlockId": candidate["candidateBlockId"],
                            "isTemplateStart": True,
                            "rejectReason": "",
                            "templateTitle": "需复核投标函",
                            "templateType": "bid_letter",
                            "startBlockId": block_id_by_text(blocks, "投标函的格式"),
                            "endBlockId": block_id_by_text(blocks, "日期："),
                            "confidence": 0.9,
                            "reason": "边界疑似跨越说明文字，需人工复核。",
                            "needsReview": True,
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        write_manifest(finalize_manifest, output_dir=output_dir, source=source, stage="finalize")

        completed = run_manifest(finalize_manifest)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads((output_dir / "business_template_extraction.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["appendices"], [])
        self.assertEqual(payload["quality"]["lowConfidenceCount"], 0)
        self.assertEqual(payload["quality"]["needsReviewCount"], 1)
        self.assertFalse((document_output / "templates").exists())
        review = (document_output / "review.md").read_text(encoding="utf-8")
        self.assertIn("需复核投标函", review)

    def test_finalize_rejects_boundary_decisions_without_executing_agent_decider(self) -> None:
        source = self.temp_dir / "invalid-decider.docx"
        output_dir = self.temp_dir / "invalid-decider-output"
        prepare_manifest = self.temp_dir / "invalid-decider-prepare.json"
        finalize_manifest = self.temp_dir / "invalid-decider-finalize.json"
        build_business_format_docx(source)
        write_manifest(prepare_manifest, output_dir=output_dir, source=source, stage="prepare")
        self.assertEqual(run_manifest(prepare_manifest).returncode, 0)

        document_output = output_dir / "DOC-1"
        (document_output / "llm_boundary_decisions.json").write_text(
            json.dumps(
                {
                    "schemaVersion": "bid-business-template-extractor-boundary-decisions-v1",
                    "decider": "external_api",
                    "decisions": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        write_manifest(finalize_manifest, output_dir=output_dir, source=source, stage="finalize")

        completed = run_manifest(finalize_manifest)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads((output_dir / "business_template_extraction.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["appendices"], [])
        self.assertTrue(any("decider" in item["message"] for item in payload["warnings"]))
        self.assertFalse((document_output / "templates").exists())

    def test_finalize_rejects_decisions_missing_required_fields(self) -> None:
        source = self.temp_dir / "missing-decision-fields.docx"
        output_dir = self.temp_dir / "missing-decision-fields-output"
        prepare_manifest = self.temp_dir / "missing-decision-fields-prepare.json"
        finalize_manifest = self.temp_dir / "missing-decision-fields-finalize.json"
        build_business_format_docx(source)
        write_manifest(prepare_manifest, output_dir=output_dir, source=source, stage="prepare")
        self.assertEqual(run_manifest(prepare_manifest).returncode, 0)

        document_output = output_dir / "DOC-1"
        (document_output / "llm_boundary_decisions.json").write_text(
            json.dumps(
                {
                    "schemaVersion": "bid-business-template-extractor-boundary-decisions-v1",
                    "decider": "executing_agent",
                    "decisions": [{"candidateId": "CAND-0001", "isTemplateStart": True}],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        write_manifest(finalize_manifest, output_dir=output_dir, source=source, stage="finalize")

        completed = run_manifest(finalize_manifest)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads((output_dir / "business_template_extraction.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["appendices"], [])
        self.assertTrue(any("缺少字段" in item["message"] for item in payload["warnings"]))
        self.assertFalse((document_output / "templates").exists())

    def test_finalize_rejects_boundary_decisions_without_decisions_array(self) -> None:
        source = self.temp_dir / "missing-decisions-array.docx"
        output_dir = self.temp_dir / "missing-decisions-array-output"
        prepare_manifest = self.temp_dir / "missing-decisions-array-prepare.json"
        finalize_manifest = self.temp_dir / "missing-decisions-array-finalize.json"
        build_business_format_docx(source)
        write_manifest(prepare_manifest, output_dir=output_dir, source=source, stage="prepare")
        self.assertEqual(run_manifest(prepare_manifest).returncode, 0)

        document_output = output_dir / "DOC-1"
        (document_output / "llm_boundary_decisions.json").write_text(
            json.dumps(
                {
                    "schemaVersion": "bid-business-template-extractor-boundary-decisions-v1",
                    "decider": "executing_agent",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        write_manifest(finalize_manifest, output_dir=output_dir, source=source, stage="finalize")

        completed = run_manifest(finalize_manifest)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads((output_dir / "business_template_extraction.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["appendices"], [])
        self.assertTrue(any("decisions" in item["message"] for item in payload["warnings"]))
        self.assertFalse((document_output / "templates").exists())

    def test_finalize_removes_stale_templates_when_agent_outputs_no_valid_templates(self) -> None:
        source = self.temp_dir / "stale-templates.docx"
        output_dir = self.temp_dir / "stale-templates-output"
        prepare_manifest = self.temp_dir / "stale-templates-prepare.json"
        fallback_manifest = self.temp_dir / "stale-templates-fallback.json"
        finalize_manifest = self.temp_dir / "stale-templates-finalize.json"
        build_business_format_docx(source)
        write_manifest(prepare_manifest, output_dir=output_dir, source=source, stage="prepare")
        self.assertEqual(run_manifest(prepare_manifest).returncode, 0)
        write_manifest(fallback_manifest, output_dir=output_dir, source=source, stage="finalize", fallbackMode="script")
        self.assertEqual(run_manifest(fallback_manifest).returncode, 0)
        document_output = output_dir / "DOC-1"
        self.assertTrue((document_output / "templates").exists())

        candidates = json.loads((document_output / "candidate_templates.json").read_text(encoding="utf-8"))
        (document_output / "llm_boundary_decisions.json").write_text(
            json.dumps(
                {
                    "schemaVersion": "bid-business-template-extractor-boundary-decisions-v1",
                    "decider": "executing_agent",
                    "decisions": [
                        {
                            "candidateId": item["candidateId"],
                            "candidateBlockId": item["candidateBlockId"],
                            "isTemplateStart": False,
                            "rejectReason": "目录项不是模板。",
                            "templateTitle": item["text"],
                            "templateType": "",
                            "startBlockId": None,
                            "endBlockId": None,
                            "confidence": 0.8,
                            "reason": "目录项不是模板。",
                            "needsReview": False,
                        }
                        for item in candidates
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        write_manifest(finalize_manifest, output_dir=output_dir, source=source, stage="finalize")

        completed = run_manifest(finalize_manifest)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads((output_dir / "business_template_extraction.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["appendices"], [])
        self.assertFalse((document_output / "templates").exists())

    def test_slicer_cleans_blank_page_paragraphs_at_template_edges(self) -> None:
        from scripts.docx_slicer import slice_docx_by_boundaries  # noqa: PLC0415

        source = self.temp_dir / "edge-blank-pages.docx"
        output_dir = self.temp_dir / "edge-blank-pages-output"
        doc = Document()
        doc.add_page_break()
        title = doc.add_paragraph("模板标题")
        title.paragraph_format.page_break_before = True
        doc.add_paragraph("模板正文")
        doc.add_page_break()
        doc.add_paragraph("")
        doc.save(source)

        result = slice_docx_by_boundaries(
            source,
            [
                {"blockId": 1, "bodyIndex": 0},
                {"blockId": 2, "bodyIndex": 1},
                {"blockId": 3, "bodyIndex": 2},
                {"blockId": 4, "bodyIndex": 3},
                {"blockId": 5, "bodyIndex": 4},
            ],
            {
                "templates": [
                    {
                        "id": "TPL-0001",
                        "title": "模板标题",
                        "startBlockId": 1,
                        "endBlockId": 5,
                    }
                ]
            },
            output_dir,
        )

        target = output_dir / result["templates"][0]["outputPath"]
        summary = docx_edge_summary(target)
        self.assertEqual(summary["texts"], ["模板标题", "模板正文"])
        self.assertFalse(summary["leadingBlank"])
        self.assertFalse(summary["trailingBlank"])
        self.assertFalse(summary["firstPageBreakBefore"])
        self.assertFalse(summary["edgePageBreak"])

    def test_slicer_moves_last_content_section_break_to_body_section(self) -> None:
        from docx.oxml import OxmlElement  # noqa: PLC0415
        from docx.oxml.ns import qn  # noqa: PLC0415
        from scripts.docx_slicer import slice_docx_by_boundaries  # noqa: PLC0415

        source = self.temp_dir / "last-content-section-break.docx"
        output_dir = self.temp_dir / "last-content-section-break-output"
        doc = Document()
        doc.add_paragraph("Template title")
        final_paragraph = doc.add_paragraph("Seal and signature")
        p_pr = final_paragraph._p.get_or_add_pPr()
        sect_pr = OxmlElement("w:sectPr")
        section_type = OxmlElement("w:type")
        section_type.set(qn("w:val"), "nextPage")
        sect_pr.append(section_type)
        page_size = OxmlElement("w:pgSz")
        page_size.set(qn("w:w"), "16838")
        page_size.set(qn("w:h"), "11906")
        sect_pr.append(page_size)
        p_pr.append(sect_pr)
        doc.save(source)

        result = slice_docx_by_boundaries(
            source,
            [
                {"blockId": 1, "bodyIndex": 0},
                {"blockId": 2, "bodyIndex": 1},
            ],
            {
                "templates": [
                    {
                        "id": "TPL-0001",
                        "title": "Template title",
                        "startBlockId": 1,
                        "endBlockId": 2,
                    }
                ]
            },
            output_dir,
        )

        target = output_dir / result["templates"][0]["outputPath"]
        summary = docx_edge_summary(target)
        self.assertEqual(summary["texts"], ["Template title", "Seal and signature"])
        self.assertFalse(summary["lastContentHasSectionBreak"])
        self.assertEqual(summary["bodySectionBreakCount"], 1)
        self.assertEqual(summary["bodyPageWidth"], "16838")

    def test_slicer_removes_only_trailing_plain_blank_paragraphs(self) -> None:
        from scripts.docx_slicer import slice_docx_by_boundaries  # noqa: PLC0415

        source = self.temp_dir / "trailing-plain-blank-paragraphs.docx"
        output_dir = self.temp_dir / "trailing-plain-blank-paragraphs-output"
        doc = Document()
        doc.add_paragraph("Template title")
        doc.add_paragraph("Intro text")
        doc.add_paragraph("")
        doc.add_paragraph("Commitment text")
        doc.add_paragraph("Date line")
        doc.add_paragraph("")
        doc.add_paragraph("")
        doc.add_paragraph("")
        doc.save(source)

        result = slice_docx_by_boundaries(
            source,
            [
                {"blockId": 1, "bodyIndex": 0},
                {"blockId": 2, "bodyIndex": 1},
                {"blockId": 3, "bodyIndex": 2},
                {"blockId": 4, "bodyIndex": 3},
                {"blockId": 5, "bodyIndex": 4},
                {"blockId": 6, "bodyIndex": 5},
                {"blockId": 7, "bodyIndex": 6},
                {"blockId": 8, "bodyIndex": 7},
            ],
            {
                "templates": [
                    {
                        "id": "TPL-0001",
                        "title": "Template title",
                        "startBlockId": 1,
                        "endBlockId": 8,
                    }
                ]
            },
            output_dir,
        )

        target = output_dir / result["templates"][0]["outputPath"]
        summary = docx_edge_summary(target)
        self.assertEqual(summary["texts"], ["Template title", "Intro text", "Commitment text", "Date line"])
        self.assertFalse(summary["trailingBlank"])
        self.assertEqual(summary["trailingBlankCount"], 0)
        self.assertEqual(summary["blankParagraphCount"], 1)

    def test_runner_writes_appendices_and_preserves_bid_letter_tail(self) -> None:
        source = self.temp_dir / "招标文件.docx"
        output_dir = self.temp_dir / "output"
        manifest = self.temp_dir / "manifest.json"
        build_business_format_docx(source)
        manifest.write_text(
            json.dumps(
                {
                    "projectId": "proj-test",
                    "outputDir": str(output_dir),
                    "fallbackMode": "script",
                    "documents": [
                        {
                            "id": "DOC-1",
                            "name": "招标文件.docx",
                            "sourcePath": str(source),
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        completed = subprocess.run(
            [sys.executable, str(RUNNER), str(manifest)],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads((output_dir / "business_template_extraction.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["schemaVersion"], "bid-business-template-extractor-v1")
        self.assertEqual(payload["skillName"], "bid-business-template-extractor")
        self.assertEqual(payload["summary"]["templateCount"], len(payload["appendices"]))
        self.assertTrue(payload["quality"]["scriptFallbackUsed"])
        bid_letter = next(item for item in payload["appendices"] if "投标函" in item["title"])
        self.assertEqual(bid_letter["artifactType"], "business_attachment_template")
        self.assertEqual(bid_letter["sourceDocumentId"], "DOC-1")
        self.assertTrue(Path(bid_letter["docxPath"]).is_file())
        text = docx_text(Path(bid_letter["docxPath"]))
        self.assertIn("投标人(盖公章)：", text)
        self.assertIn("法定代表人或其委托代理人(签字)：", text)
        self.assertIn("日期：       年    月   日", text)
        self.assertNotIn("法定代表人（单位负责人）身份证明：B", text)

    def test_runner_regression_boundaries_do_not_swallow_next_template_clusters(self) -> None:
        source = self.temp_dir / "边界回归.docx"
        output_dir = self.temp_dir / "regression-output"
        manifest = self.temp_dir / "regression-manifest.json"
        build_boundary_regression_docx(source)
        manifest.write_text(
            json.dumps(
                {
                    "projectId": "proj-regression",
                    "outputDir": str(output_dir),
                    "fallbackMode": "script",
                    "documents": [
                        {
                            "id": "DOC-1",
                            "name": "边界回归.docx",
                            "sourcePath": str(source),
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        completed = subprocess.run(
            [sys.executable, str(RUNNER), str(manifest)],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads((output_dir / "business_template_extraction.json").read_text(encoding="utf-8"))
        titles = [item["title"] for item in payload["appendices"]]
        self.assertTrue(any("附件3 货物规格一览表" in title and "表3 A" in title for title in titles))
        self.assertTrue(any("附件4 商务条款偏差表" in title for title in titles))
        self.assertTrue(any("附件7 资格证明文件" in title for title in titles))
        self.assertTrue(any("7D-4" in title for title in titles))
        self.assertTrue(any("7E-1" in title for title in titles))
        self.assertTrue(any("保密承诺书" in title for title in titles))

        def item_text(title_part: str) -> str:
            item = next(item for item in payload["appendices"] if title_part in item["title"])
            return docx_text(Path(item["docxPath"]))

        self.assertNotIn("附件4 商务条款偏差表", item_text("表3 A"))
        self.assertNotIn("附件7 资格证明文件", item_text("履约保证函格式"))
        self.assertNotIn("附件7E", item_text("7D-4"))
        self.assertNotIn("特殊附件1", item_text("开标价格表"))
        self.assertTrue(item_text("保密承诺书").startswith("特殊附件1\n保密承诺书"))


    def test_runner_ignores_catalog_listing_before_real_templates(self) -> None:
        source = self.temp_dir / "catalog-listing.docx"
        output_dir = self.temp_dir / "catalog-listing-output"
        manifest = self.temp_dir / "catalog-listing-manifest.json"
        build_catalog_listing_regression_docx(source)
        manifest.write_text(
            json.dumps(
                {
                    "projectId": "proj-catalog-listing",
                    "outputDir": str(output_dir),
                    "fallbackMode": "script",
                    "documents": [
                        {
                            "id": "DOC-1",
                            "name": "catalog-listing.docx",
                            "sourcePath": str(source),
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        completed = subprocess.run(
            [sys.executable, str(RUNNER), str(manifest)],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads((output_dir / "business_template_extraction.json").read_text(encoding="utf-8"))
        document_output = output_dir / "DOC-1"
        boundaries = json.loads((document_output / "boundaries.json").read_text(encoding="utf-8"))
        blocks = json.loads((document_output / "blocks.json").read_text(encoding="utf-8"))
        catalog_heading_id = next(int(block["blockId"]) for block in blocks if block.get("text") == "目    录")
        catalog_end_id = next(
            int(block["blockId"])
            for block in blocks
            if int(block["blockId"]) > catalog_heading_id and block.get("hasPageBreakAfter")
        )
        catalog_listing_ids = {
            int(block["blockId"])
            for block in blocks
            if catalog_heading_id < int(block["blockId"]) < catalog_end_id and str(block.get("text") or "").startswith("附件")
        }
        self.assertFalse(
            any(int(item["startBlockId"]) in catalog_listing_ids for item in boundaries["templates"]),
            boundaries["templates"],
        )

        titles = [item["title"] for item in payload["appendices"]]
        self.assertTrue(any("表3 A" in title for title in titles))
        self.assertTrue(any("开标价格表" in title for title in titles))

    def test_runner_extracts_only_bid_file_format_region_not_contract_attachments(self) -> None:
        source = self.temp_dir / "contract-and-bid-format.docx"
        output_dir = self.temp_dir / "contract-and-bid-format-output"
        manifest = self.temp_dir / "contract-and-bid-format-manifest.json"
        build_contract_attachment_and_bid_format_docx(source)
        manifest.write_text(
            json.dumps(
                {
                    "projectId": "proj-contract-and-bid-format",
                    "outputDir": str(output_dir),
                    "fallbackMode": "script",
                    "documents": [
                        {
                            "id": "DOC-1",
                            "name": "contract-and-bid-format.docx",
                            "sourcePath": str(source),
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        completed = subprocess.run(
            [sys.executable, str(RUNNER), str(manifest)],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads((output_dir / "business_template_extraction.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["formatRegions"][0]["title"], "第六章 投标文件格式")
        self.assertTrue(any(region["title"] == "第三节 合同附件格式" for region in payload["excludedRegions"]))
        self.assertGreaterEqual(payload["quality"]["excludedRegionCount"], 1)
        titles = [item["title"] for item in payload["appendices"]]
        self.assertTrue(any("投标函" in title for title in titles), titles)
        self.assertTrue(any("法定代表人" in title for title in titles), titles)
        self.assertNotIn("1. 投标函", titles)
        self.assertNotIn("2. 法定代表人（单位负责人）身份证明", titles)
        self.assertFalse(any("法定代表人或其委托代理人" in title for title in titles), titles)
        self.assertFalse(any("合同协议书" in title for title in titles), titles)
        self.assertFalse(any("履约保证金" in title for title in titles), titles)

        document_output = output_dir / "DOC-1"
        regions = json.loads((document_output / "regions.json").read_text(encoding="utf-8"))
        self.assertEqual([region["title"] for region in regions], ["第六章 投标文件格式"])

    def test_runner_splits_inline_table_titles_inside_format_region(self) -> None:
        source = self.temp_dir / "inline-table-titles.docx"
        output_dir = self.temp_dir / "inline-table-titles-output"
        manifest = self.temp_dir / "inline-table-titles-manifest.json"
        build_inline_table_titles_docx(source)
        manifest.write_text(
            json.dumps(
                {
                    "projectId": "proj-inline-table-titles",
                    "outputDir": str(output_dir),
                    "fallbackMode": "script",
                    "documents": [
                        {
                            "id": "DOC-1",
                            "name": "inline-table-titles.docx",
                            "sourcePath": str(source),
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        completed = subprocess.run(
            [sys.executable, str(RUNNER), str(manifest)],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads((output_dir / "business_template_extraction.json").read_text(encoding="utf-8"))
        titles = [item["title"] for item in payload["appendices"]]
        self.assertTrue(any("投标保证金" in title for title in titles), titles)
        self.assertTrue(any("商务和技术偏差表" in title for title in titles), titles)
        self.assertTrue(any("基本情况表" in title for title in titles), titles)
        self.assertTrue(any("近年财务状况" in title for title in titles), titles)

        def item_text(title_part: str) -> str:
            item = next(item for item in payload["appendices"] if title_part in item["title"])
            return docx_text(Path(item["docxPath"]))

        self.assertNotIn("商务和技术偏差表", item_text("投标保证金"))
        self.assertNotIn("基本情况表", item_text("商务和技术偏差表"))
        basic_info = next(item for item in payload["appendices"] if "基本情况表" in item["title"])
        self.assertIn("投标人名称", docx_table_text(Path(basic_info["docxPath"])))

    def test_runner_recalls_appendix_prefixed_table_title_before_table(self) -> None:
        source = self.temp_dir / "appendix-table-title.docx"
        output_dir = self.temp_dir / "appendix-table-title-output"
        manifest = self.temp_dir / "appendix-table-title-manifest.json"
        build_appendix_table_title_docx(source)
        write_manifest(manifest, output_dir=output_dir, source=source, fallbackMode="script")

        completed = run_manifest(manifest)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads((output_dir / "business_template_extraction.json").read_text(encoding="utf-8"))
        titles = [item["title"] for item in payload["appendices"]]
        self.assertTrue(any("商务条款偏差表" in title for title in titles), titles)

    def test_runner_recalls_letter_number_table_titles_before_tables(self) -> None:
        source = self.temp_dir / "letter-number-table-title.docx"
        output_dir = self.temp_dir / "letter-number-table-title-output"
        manifest = self.temp_dir / "letter-number-table-title-manifest.json"
        build_letter_number_table_title_docx(source)
        write_manifest(manifest, output_dir=output_dir, source=source, fallbackMode="script")

        completed = run_manifest(manifest)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads((output_dir / "business_template_extraction.json").read_text(encoding="utf-8"))
        titles = [item["title"] for item in payload["appendices"]]
        self.assertTrue(any("7A表 商务部分摘要表" in title for title in titles), titles)
        self.assertTrue(any("7B表 股权结构表" in title for title in titles), titles)

    def test_boundary_validator_rejects_catalog_contaminated_template(self) -> None:
        blocks = [
            {
                "blockId": 1,
                "type": "paragraph",
                "text": "第六章 投标文件格式",
            },
            {
                "blockId": 2,
                "type": "paragraph",
                "text": "法定代表人或其委托代理人：  法定代表人或委托代理人姓名  （签字）",
            },
            {
                "blockId": 3,
                "type": "paragraph",
                "text": "投标日期",
            },
            {
                "blockId": 4,
                "type": "paragraph",
                "text": "目    录",
            },
        ]
        regions = [{"id": "REG-0001", "title": "第六章 投标文件格式", "startBlockId": 1, "endBlockId": 4}]
        boundaries = {
            "templates": [
                {
                    "id": "TPL-0001",
                    "title": "法定代表人或其委托代理人：  法定代表人或委托代理人姓名  （签字）",
                    "regionId": "REG-0001",
                    "startBlockId": 2,
                    "endBlockId": 4,
                }
            ]
        }

        with self.assertRaisesRegex(BoundaryValidationError, "未生成任何有效模板边界"):
            validate_boundaries(blocks, regions, boundaries)

    def test_boundary_validator_records_invalid_overlap_and_outside_boundaries(self) -> None:
        blocks = [
            {"blockId": 1, "type": "paragraph", "text": "第六章 投标文件格式"},
            {"blockId": 2, "type": "paragraph", "text": "投标函"},
            {"blockId": 3, "type": "paragraph", "text": "投标人："},
            {"blockId": 4, "type": "paragraph", "text": "授权委托书"},
            {"blockId": 5, "type": "paragraph", "text": "委托代理人："},
            {"blockId": 6, "type": "paragraph", "text": "第七章 技术规范"},
        ]
        regions = [{"id": "REG-0001", "title": "第六章 投标文件格式", "startBlockId": 1, "endBlockId": 5}]
        boundaries = {
            "templates": [
                {
                    "id": "TPL-0001",
                    "title": "投标函",
                    "regionId": "REG-0001",
                    "startBlockId": 2,
                    "endBlockId": 3,
                    "confidence": 0.9,
                },
                {
                    "id": "TPL-0002",
                    "title": "重叠模板",
                    "regionId": "REG-0001",
                    "startBlockId": 3,
                    "endBlockId": 4,
                    "confidence": 0.9,
                },
                {
                    "id": "TPL-0003",
                    "title": "无效边界",
                    "regionId": "REG-0001",
                    "startBlockId": 5,
                    "endBlockId": 4,
                    "confidence": 0.9,
                },
                {
                    "id": "TPL-0004",
                    "title": "越界模板",
                    "regionId": "REG-0001",
                    "startBlockId": 4,
                    "endBlockId": 6,
                    "confidence": 0.9,
                },
            ]
        }

        result = validate_boundaries(blocks, regions, boundaries, strict=False, raise_on_empty=False)

        self.assertEqual(len(result["templates"]), 1)
        reject_codes = [item["rejectCode"] for item in result["rejectedTemplates"]]
        self.assertIn("overlap", reject_codes)
        self.assertIn("invalid_boundary", reject_codes)
        self.assertIn("outside_format_region", reject_codes)

    def test_excluded_contract_related_format_headings_do_not_enter_candidate_regions(self) -> None:
        from scripts.region_detector import detect_excluded_format_regions, detect_format_regions  # noqa: PLC0415

        blocks = [
            {
                "blockId": 1,
                "type": "paragraph",
                "text": "第六章 合同价格组成",
                "styleName": "Heading 1",
                "isLikelyHeading": True,
                "isCentered": False,
                "isPageFirstNonEmpty": True,
            },
            {
                "blockId": 2,
                "type": "paragraph",
                "text": "价格组成正文",
                "styleName": "",
                "isLikelyHeading": False,
                "isCentered": False,
                "isPageFirstNonEmpty": False,
            },
            {
                "blockId": 3,
                "type": "paragraph",
                "text": "履约保证金格式",
                "styleName": "Heading 1",
                "isLikelyHeading": True,
                "isCentered": False,
                "isPageFirstNonEmpty": True,
            },
            {
                "blockId": 4,
                "type": "paragraph",
                "text": "保证金格式正文",
                "styleName": "",
                "isLikelyHeading": False,
                "isCentered": False,
                "isPageFirstNonEmpty": False,
            },
        ]

        self.assertEqual(detect_format_regions(blocks), [])
        excluded_titles = [region["title"] for region in detect_excluded_format_regions(blocks)]
        self.assertEqual(excluded_titles, ["第六章 合同价格组成", "履约保证金格式"])


class BusinessTemplateExtractorWrapperTests(unittest.TestCase):
    def test_build_manifest_keeps_only_docx_sources_and_output_dir(self) -> None:
        output_dir = Path("C:/tmp/business-template-output")
        manifest = build_business_template_extractor_manifest(
            project_id="proj-1",
            documents=[
                {"id": "DOC-1", "name": "招标.docx", "sourcePath": "C:/tmp/招标.docx"},
                {"id": "DOC-2", "name": "说明.txt", "sourcePath": "C:/tmp/说明.txt"},
            ],
            output_dir=output_dir,
        )

        self.assertEqual(manifest["projectId"], "proj-1")
        self.assertEqual(manifest["outputDir"], str(output_dir))
        self.assertEqual(manifest["stage"], "prepare")
        self.assertNotIn("fallbackMode", manifest)
        self.assertEqual(len(manifest["documents"]), 1)
        self.assertEqual(manifest["documents"][0]["id"], "DOC-1")

    def test_boundary_decision_prompt_uses_btplbound_flow_without_inline_window_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            output_dir = project_dir / "business_template_extraction"
            document_output = output_dir / "DOC-1"
            document_output.mkdir(parents=True)
            (document_output / "candidate_templates.json").write_text(
                json.dumps(
                    [
                        {
                            "candidateId": "CAND-0001",
                            "candidateBlockId": 10,
                            "text": "Bid Letter",
                            "regionTitle": "Formats",
                            "score": 99,
                            "signals": ["template_word"],
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (document_output / "candidate_windows.json").write_text(
                json.dumps(
                    [
                        {
                            "candidateId": "CAND-0001",
                            "blocks": [{"blockId": 10, "text": "VERY_LONG_INLINE_EVIDENCE_SHOULD_NOT_BE_IN_PROMPT"}],
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            prepare_payload = {"documents": [{"id": "DOC-1", "outputDir": str(document_output)}]}

            prompt = build_business_template_boundary_decision_prompt(
                project_id="PRJ-1",
                manifest_path=project_dir / "business_template_extraction_manifest.json",
                output_dir=output_dir,
                prepare_payload=prepare_payload,
            )

        self.assertIn("btplbound status", prompt)
        self.assertIn("btplbound candidate-batch", prompt)
        self.assertIn("btplbound finalize", prompt)
        self.assertIn("candidate_templates.json", prompt)
        self.assertIn("candidate_windows.json", prompt)
        self.assertIn("llm_boundary_decisions.json", prompt)
        self.assertIn("CAND-0001", prompt)
        self.assertNotIn("VERY_LONG_INLINE_EVIDENCE_SHOULD_NOT_BE_IN_PROMPT", prompt)
        self.assertNotIn('"candidateWindows"', prompt)

    def test_boundary_decision_prompt_describes_high_recall_heading_role_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp_dir = Path(tmp)
            output_dir = temp_dir / "prompt-output"
            document_output = output_dir / "DOC-1"
            document_output.mkdir(parents=True)
            (document_output / "candidate_templates.json").write_text("[]", encoding="utf-8")
            (document_output / "candidate_windows.json").write_text("[]", encoding="utf-8")
            (document_output / "blocks.json").write_text("[]", encoding="utf-8")
            (document_output / "regions.json").write_text("[]", encoding="utf-8")
            prepare_payload = {
                "documents": [
                    {
                        "id": "DOC-1",
                        "outputDir": str(document_output),
                        "summary": {"candidateCount": 0},
                    }
                ]
            }

            prompt = build_business_template_boundary_decision_prompt(
                project_id="proj",
                manifest_path=temp_dir / "manifest.json",
                output_dir=output_dir,
                prepare_payload=prepare_payload,
            )

        self.assertIn("高召回疑似标题", prompt)
        self.assertIn("template_start", prompt)
        self.assertIn("boundary_only", prompt)
        self.assertIn("section_container", prompt)
        self.assertIn("不要直接读取完整 blocks.json", prompt)
        self.assertIn("btplbound candidate-batch", prompt)
        self.assertIn("btplbound boundary-batch", prompt)

    def test_boundary_decision_prompt_keeps_template_role_rules_brief_but_specific(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp_dir = Path(tmp)
            output_dir = temp_dir / "prompt-output"
            document_output = output_dir / "DOC-1"
            document_output.mkdir(parents=True)
            (document_output / "candidate_templates.json").write_text("[]", encoding="utf-8")
            (document_output / "candidate_windows.json").write_text("[]", encoding="utf-8")
            (document_output / "blocks.json").write_text("[]", encoding="utf-8")
            (document_output / "regions.json").write_text("[]", encoding="utf-8")
            prepare_payload = {
                "documents": [
                    {
                        "id": "DOC-1",
                        "outputDir": str(document_output),
                        "summary": {"candidateCount": 0},
                    }
                ]
            }

            prompt = build_business_template_boundary_decision_prompt(
                project_id="proj",
                manifest_path=temp_dir / "manifest.json",
                output_dir=output_dir,
                prepare_payload=prepare_payload,
            )

        self.assertIn("sub_table_code + near_following_table", prompt)
        self.assertIn("只有编号或编号+标段", prompt)
        self.assertIn("归入最近的父级业务标题", prompt)
        self.assertIn("含清晰业务名称", prompt)
        self.assertIn("承诺书/声明函/保密承诺书/保证函格式", prompt)
        self.assertIn("父级容器不能让整组子模板消失", prompt)

    def test_run_extractor_uses_agent_decisions_before_finalize_without_script_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            source = project_dir / "招标文件.docx"
            source.write_bytes(b"fake-docx")
            calls: list[dict[str, object]] = []
            test_case = self

            def fake_subprocess_run(args, **kwargs):  # type: ignore[no-untyped-def]
                if len(args) >= 4 and str(args[1]).endswith("btplbound_workflow.py"):
                    command = str(args[2])
                    manifest_path = Path(args[3])
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    calls.append({"command": command})
                    output_dir = Path(manifest["outputDir"])
                    document_output = output_dir / "DOC-1"
                    decision_path = document_output / "llm_boundary_decisions.json"

                    class Completed:
                        returncode = 0
                        stderr = ""

                        def __init__(self, stdout: str) -> None:
                            self.stdout = stdout

                    if command == "status":
                        ready = decision_path.is_file()
                        return Completed(
                            json.dumps(
                                {
                                    "schemaVersion": "bid-business-template-extractor-btplbound-v1",
                                    "status": "ready" if ready else "waiting",
                                    "candidate": {
                                        "total": 1,
                                        "decided": 1 if ready else 0,
                                        "batchCount": 1,
                                        "decidedBatchCount": 1 if ready else 0,
                                        "pendingBatchCount": 0 if ready else 1,
                                    },
                                    "boundary": {
                                        "total": 1 if ready else 0,
                                        "decided": 1 if ready else 0,
                                        "batchCount": 1 if ready else 0,
                                        "decidedBatchCount": 1 if ready else 0,
                                        "pendingBatchCount": 0,
                                    },
                                },
                                ensure_ascii=False,
                            )
                        )
                    if command == "finalize":
                        return Completed(
                            json.dumps(
                                {
                                    "schemaVersion": "bid-business-template-extractor-boundary-decisions-v1",
                                    "decisionFiles": [str(decision_path)],
                                    "summary": {"documentCount": 1, "decisionCount": 1, "acceptedTemplateCount": 1},
                                },
                                ensure_ascii=False,
                            )
                        )
                    return Completed("{}")

                manifest_path = Path(args[-1])
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                calls.append(
                    {
                        "stage": manifest.get("stage"),
                        "fallbackMode": manifest.get("fallbackMode"),
                    }
                )
                output_dir = Path(manifest["outputDir"])
                document_output = output_dir / "DOC-1"
                document_output.mkdir(parents=True, exist_ok=True)
                if manifest["stage"] == "prepare":
                    (document_output / "candidate_templates.json").write_text(
                        json.dumps(
                            [
                                {
                                    "candidateId": "CAND-0001",
                                    "candidateBlockId": 10,
                                    "title": "投标函",
                                }
                            ],
                            ensure_ascii=False,
                        ),
                        encoding="utf-8",
                    )
                    (document_output / "candidate_windows.json").write_text("[]", encoding="utf-8")
                    (output_dir / "business_template_extraction.json").write_text(
                        json.dumps({"stage": "prepare", "documents": [{"id": "DOC-1", "outputDir": str(document_output)}]}),
                        encoding="utf-8",
                    )
                else:
                    self.assertNotEqual(manifest.get("fallbackMode"), "script")
                    self.assertTrue((document_output / "llm_boundary_decisions.json").is_file())
                    (output_dir / "business_template_extraction.json").write_text(
                        json.dumps(
                            {
                                "stage": "finalize",
                                "appendices": [
                                    {
                                        "id": "APPX-0001",
                                        "title": "投标函",
                                        "artifactType": "business_attachment_template",
                                        "docxPath": str(document_output / "templates" / "TPL-0001.docx"),
                                        "sourceDocumentId": "DOC-1",
                                    }
                                ],
                                "quality": {
                                    "agentDecisionCount": 1,
                                    "agentRejectedCount": 0,
                                    "scriptFallbackUsed": False,
                                },
                            },
                            ensure_ascii=False,
                        ),
                        encoding="utf-8",
                    )

                class Completed:
                    returncode = 0
                    stdout = "{}"
                    stderr = ""

                return Completed()

            def fake_agent(_client, prompt: str):  # type: ignore[no-untyped-def]
                test_case.assertIn("candidate_templates.json", prompt)
                test_case.assertIn("llm_boundary_decisions.json", prompt)
                decision_path = project_dir / "business_template_extraction" / "DOC-1" / "llm_boundary_decisions.json"
                decision_path.write_text(
                    json.dumps(
                        {
                            "schemaVersion": "bid-business-template-extractor-boundary-decisions-v1",
                            "decider": "executing_agent",
                            "decisions": [
                                {
                                    "candidateId": "CAND-0001",
                                    "candidateBlockId": 10,
                                    "isTemplateStart": True,
                                    "rejectReason": "",
                                    "templateTitle": "投标函",
                                    "templateType": "bid_letter",
                                    "startBlockId": 10,
                                    "endBlockId": 20,
                                    "confidence": 0.95,
                                    "reason": "标题后存在正文与签章字段。",
                                    "needsReview": False,
                                }
                            ],
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                return {"opencodeOutput": {"sessionId": "ses-template", "status": "received"}}

            with (
                patch("app.services.business_template_extractor.subprocess.run", side_effect=fake_subprocess_run),
                patch(
                    "app.services.business_template_extractor.OpencodeClient.decide_business_template_boundaries_with_trace",
                    new=fake_agent,
                ),
            ):
                appendices, payload, warning = run_business_template_extractor(
                    project_id="PRJ-1",
                    documents=[{"id": "DOC-1", "name": "招标文件.docx", "sourcePath": str(source)}],
                    project_dir=project_dir,
                )

        self.assertEqual(warning, "")
        stage_calls = [call for call in calls if "stage" in call]
        self.assertEqual([call["stage"] for call in stage_calls], ["prepare", "finalize"])
        self.assertEqual([call["fallbackMode"] for call in stage_calls], [None, None])
        self.assertEqual(len(appendices), 1)
        self.assertEqual(appendices[0]["extractionMode"], "business_template_extractor_skill")
        self.assertFalse((payload or {})["quality"]["scriptFallbackUsed"])

    def test_run_extractor_records_agent_failure_without_script_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            source = project_dir / "agent-failure.docx"
            source.write_bytes(b"fake-docx")
            calls: list[dict[str, object]] = []

            def fake_subprocess_run(args, **kwargs):  # type: ignore[no-untyped-def]
                if len(args) >= 4 and str(args[1]).endswith("btplbound_workflow.py"):
                    command = str(args[2])
                    manifest_path = Path(args[3])
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    calls.append({"command": command})
                    output_dir = Path(manifest["outputDir"])
                    document_output = output_dir / "DOC-1"
                    decision_path = document_output / "llm_boundary_decisions.json"

                    class Completed:
                        returncode = 0
                        stderr = ""

                        def __init__(self, stdout: str) -> None:
                            self.stdout = stdout

                    if command == "status":
                        ready = decision_path.is_file()
                        return Completed(
                            json.dumps(
                                {
                                    "schemaVersion": "bid-business-template-extractor-btplbound-v1",
                                    "status": "ready" if ready else "waiting",
                                    "candidate": {
                                        "total": 1,
                                        "decided": 1 if ready else 0,
                                        "batchCount": 1,
                                        "decidedBatchCount": 1 if ready else 0,
                                        "pendingBatchCount": 0 if ready else 1,
                                    },
                                    "boundary": {
                                        "total": 0,
                                        "decided": 0,
                                        "batchCount": 0,
                                        "decidedBatchCount": 0,
                                        "pendingBatchCount": 0,
                                    },
                                },
                                ensure_ascii=False,
                            )
                        )
                    return Completed("{}")

                manifest_path = Path(args[-1])
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                calls.append({"stage": manifest.get("stage"), "fallbackMode": manifest.get("fallbackMode")})
                output_dir = Path(manifest["outputDir"])
                document_output = output_dir / "DOC-1"
                document_output.mkdir(parents=True, exist_ok=True)
                if manifest["stage"] == "prepare":
                    (document_output / "candidate_templates.json").write_text(
                        json.dumps([{"candidateId": "CAND-0001", "candidateBlockId": 10, "title": "Bid Letter"}]),
                        encoding="utf-8",
                    )
                    (document_output / "candidate_windows.json").write_text("[]", encoding="utf-8")
                    (output_dir / "business_template_extraction.json").write_text(
                        json.dumps({"stage": "prepare", "documents": [{"id": "DOC-1", "outputDir": str(document_output)}]}),
                        encoding="utf-8",
                    )
                else:
                    self.assertNotEqual(manifest.get("fallbackMode"), "script")
                    (output_dir / "business_template_extraction.json").write_text(
                        json.dumps(
                            {
                                "stage": "finalize",
                                "appendices": [],
                                "warnings": [],
                                "quality": {"scriptFallbackUsed": False},
                            },
                            ensure_ascii=False,
                        ),
                        encoding="utf-8",
                    )

                class Completed:
                    returncode = 0
                    stdout = "{}"
                    stderr = ""

                return Completed()

            with (
                patch("app.services.business_template_extractor.subprocess.run", side_effect=fake_subprocess_run),
                patch(
                    "app.services.business_template_extractor.OpencodeClient.decide_business_template_boundaries_with_trace",
                    side_effect=RuntimeError("agent stopped before finalize"),
                ),
            ):
                appendices, payload, warning = run_business_template_extractor(
                    project_id="PRJ-1",
                    documents=[{"id": "DOC-1", "name": "agent-failure.docx", "sourcePath": str(source)}],
                    project_dir=project_dir,
                )

        self.assertEqual(appendices, [])
        self.assertIn("未识别到模板", warning)
        stage_calls = [call for call in calls if "stage" in call]
        self.assertEqual([call["fallbackMode"] for call in stage_calls], [None, None])
        self.assertFalse((payload or {})["quality"]["scriptFallbackUsed"])
        self.assertIn("agent stopped before finalize", (payload or {})["quality"]["agentFallbackReason"])
        self.assertTrue(any(item["code"] == "template_boundary_agent_failed" for item in (payload or {})["warnings"]))

    def test_run_extractor_retries_boundary_agent_and_resumes_existing_batches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            source = project_dir / "resume-agent.docx"
            source.write_bytes(b"fake-docx")
            calls: list[dict[str, object]] = []
            agent_prompts: list[str] = []

            def completed(stdout: str = "{}", returncode: int = 0, stderr: str = ""):
                class Completed:
                    pass

                item = Completed()
                item.returncode = returncode
                item.stdout = stdout
                item.stderr = stderr
                return item

            def fake_btplbound_status(manifest_path: Path) -> dict[str, object]:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                output_dir = Path(manifest["outputDir"])
                document_output = output_dir / "DOC-1"
                partial_batch = document_output / "agent_decision_batches" / "candidate_decision_batch_0001.json"
                final_decisions = document_output / "llm_boundary_decisions.json"
                if final_decisions.is_file():
                    return {
                        "schemaVersion": "bid-business-template-extractor-btplbound-v1",
                        "status": "ready",
                        "candidate": {"total": 16, "decided": 16, "batchCount": 2, "decidedBatchCount": 2, "pendingBatchCount": 0},
                        "boundary": {"total": 1, "decided": 1, "batchCount": 1, "decidedBatchCount": 1, "pendingBatchCount": 0},
                    }
                decided_batches = 1 if partial_batch.is_file() else 0
                decided = 8 if partial_batch.is_file() else 0
                return {
                    "schemaVersion": "bid-business-template-extractor-btplbound-v1",
                    "status": "waiting",
                    "candidate": {"total": 16, "decided": decided, "batchCount": 2, "decidedBatchCount": decided_batches, "pendingBatchCount": 2 - decided_batches},
                    "boundary": {"total": 0, "decided": 0, "batchCount": 0, "decidedBatchCount": 0, "pendingBatchCount": 0},
                }

            def fake_subprocess_run(args, **kwargs):  # type: ignore[no-untyped-def]
                if len(args) >= 4 and str(args[1]).endswith("btplbound_workflow.py"):
                    command = str(args[2])
                    manifest_path = Path(args[3])
                    calls.append({"command": command})
                    if command == "status":
                        return completed(json.dumps(fake_btplbound_status(manifest_path), ensure_ascii=False))
                    if command == "finalize":
                        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                        output_dir = Path(manifest["outputDir"])
                        document_output = output_dir / "DOC-1"
                        decision_path = document_output / "llm_boundary_decisions.json"
                        if not decision_path.is_file():
                            decision_path.write_text(
                                json.dumps(
                                    {
                                        "schemaVersion": "bid-business-template-extractor-boundary-decisions-v1",
                                        "decider": "executing_agent",
                                        "decisions": [],
                                    },
                                    ensure_ascii=False,
                                ),
                                encoding="utf-8",
                            )
                        return completed(
                            json.dumps(
                                {
                                    "schemaVersion": "bid-business-template-extractor-boundary-decisions-v1",
                                    "decisionFiles": [str(decision_path)],
                                    "summary": {"documentCount": 1, "decisionCount": 1, "acceptedTemplateCount": 1},
                                },
                                ensure_ascii=False,
                            )
                        )
                    return completed()

                manifest_path = Path(args[-1])
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                calls.append({"stage": manifest.get("stage"), "fallbackMode": manifest.get("fallbackMode")})
                output_dir = Path(manifest["outputDir"])
                document_output = output_dir / "DOC-1"
                document_output.mkdir(parents=True, exist_ok=True)
                if manifest["stage"] == "prepare":
                    (document_output / "candidate_templates.json").write_text(
                        json.dumps(
                            [
                                {"candidateId": "CAND-0001", "candidateBlockId": 10, "text": "Bid Letter"},
                                {"candidateId": "CAND-0002", "candidateBlockId": 20, "text": "Authorization"},
                            ],
                            ensure_ascii=False,
                        ),
                        encoding="utf-8",
                    )
                    (document_output / "candidate_windows.json").write_text("[]", encoding="utf-8")
                    (output_dir / "business_template_extraction.json").write_text(
                        json.dumps({"stage": "prepare", "documents": [{"id": "DOC-1", "outputDir": str(document_output)}]}),
                        encoding="utf-8",
                    )
                else:
                    self.assertNotEqual(manifest.get("fallbackMode"), "script")
                    if (document_output / "llm_boundary_decisions.json").is_file():
                        (output_dir / "business_template_extraction.json").write_text(
                            json.dumps(
                                {
                                    "stage": "finalize",
                                    "outputDir": str(output_dir),
                                    "appendices": [
                                        {
                                            "id": "APPX-0001",
                                            "title": "Bid Letter",
                                            "artifactType": "business_attachment_template",
                                            "docxPath": str(document_output / "templates" / "TPL-0001.docx"),
                                            "sourceDocumentId": "DOC-1",
                                        }
                                    ],
                                    "quality": {"scriptFallbackUsed": False},
                                },
                                ensure_ascii=False,
                            ),
                            encoding="utf-8",
                        )
                    else:
                        (output_dir / "business_template_extraction.json").write_text(
                            json.dumps({"stage": "finalize", "outputDir": str(output_dir), "appendices": [], "warnings": [], "quality": {"scriptFallbackUsed": False}}),
                            encoding="utf-8",
                        )
                return completed()

            def fake_agent(_client, prompt: str):  # type: ignore[no-untyped-def]
                agent_prompts.append(prompt)
                document_output = project_dir / "business_template_extraction" / "DOC-1"
                batch_dir = document_output / "agent_decision_batches"
                batch_dir.mkdir(parents=True, exist_ok=True)
                if len(agent_prompts) == 1:
                    (batch_dir / "candidate_decision_batch_0001.json").write_text(
                        json.dumps({"phase": "candidate", "batchNo": 1, "decisions": [{"candidateId": "CAND-0001"}]}, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    raise RuntimeError("opencode disconnected after candidate batch 1")

                self.assertTrue((batch_dir / "candidate_decision_batch_0001.json").is_file())
                self.assertIn("btplbound status", prompt)
                (document_output / "llm_boundary_decisions.json").write_text(
                    json.dumps(
                        {
                            "schemaVersion": "bid-business-template-extractor-boundary-decisions-v1",
                            "decider": "executing_agent",
                            "decisions": [
                                {
                                    "candidateId": "CAND-0001",
                                    "candidateBlockId": 10,
                                    "isTemplateStart": True,
                                    "headingRole": "template_start",
                                    "templateTitle": "Bid Letter",
                                    "templateType": "bid_letter",
                                    "startBlockId": 10,
                                    "endBlockId": 19,
                                    "confidence": 0.95,
                                    "reason": "resumed from existing batch decisions",
                                    "needsReview": False,
                                }
                            ],
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                return {"opencodeOutput": {"sessionId": "ses-resumed", "status": "received"}}

            with (
                patch("app.services.business_template_extractor.subprocess.run", side_effect=fake_subprocess_run),
                patch(
                    "app.services.business_template_extractor.OpencodeClient.decide_business_template_boundaries_with_trace",
                    new=fake_agent,
                ),
            ):
                appendices, payload, warning = run_business_template_extractor(
                    project_id="PRJ-1",
                    documents=[{"id": "DOC-1", "name": "resume-agent.docx", "sourcePath": str(source)}],
                    project_dir=project_dir,
                )

        self.assertEqual(warning, "")
        self.assertEqual(len(agent_prompts), 2)
        self.assertEqual(len(appendices), 1)
        self.assertEqual(appendices[0]["title"], "Bid Letter")
        self.assertFalse((payload or {})["quality"]["scriptFallbackUsed"])
        self.assertEqual((payload or {})["opencodeOutput"]["sessionId"], "ses-resumed")
        self.assertGreaterEqual([call.get("command") for call in calls].count("status"), 2)

    def test_convert_extractor_appendices_preserves_docx_path_for_prepare_outputs(self) -> None:
        payload = {
            "appendices": [
                {
                    "id": "APPX-0007",
                    "title": "附件2 投标价格表\nA投标价格总表\n表1 A-1  标段一",
                    "artifactType": "business_attachment_template",
                    "templateType": "business_template",
                    "templateSectionTitle": "第六章 投标文件格式",
                    "status": "generated",
                    "docxPath": "C:/tmp/TPL-0001.docx",
                    "sourceDocumentId": "DOC-1",
                    "sourceDocumentName": "招标.docx",
                }
            ]
        }

        appendices = convert_extractor_appendices(payload)

        self.assertEqual(len(appendices), 1)
        self.assertEqual(appendices[0]["id"], "APPX-0007")
        self.assertEqual(appendices[0]["title"], "附件2 投标价格表\nA投标价格总表\n表1 A-1  标段一")
        self.assertEqual(appendices[0]["artifactType"], "business_attachment_template")
        self.assertEqual(appendices[0]["extractionMode"], "business_template_extractor_skill")
        self.assertEqual(appendices[0]["docxPath"], "C:/tmp/TPL-0001.docx")
        self.assertEqual(appendices[0]["workspacePath"], "")


if __name__ == "__main__":
    unittest.main()
