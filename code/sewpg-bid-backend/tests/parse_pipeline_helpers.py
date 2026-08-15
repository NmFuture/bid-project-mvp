"""test_parse_* 共享夹具：docx 样本构造、解析输入/完成辅助与带 TestClient 的基类。

由 test_parse_pipeline.py 拆分而来，只搬不改。
"""
from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from docx import Document
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings
from app.services.bid_parse_state import complete_parse_state
from app.services.bid_project_state import project_parse_input_records
from app.services.store import store


def build_docx_bytes(*lines: str) -> bytes:
    file_obj = io.BytesIO()
    doc = Document()
    for line in lines:
        doc.add_paragraph(line)
    doc.save(file_obj)
    return file_obj.getvalue()


def parse_inputs_for_tests(project_id: str):
    project = store.get_project_runtime_state(project_id)
    return project_parse_input_records(project_id, project)


def complete_parse_for_tests(
    project_id: str,
    tender_files: list[dict],
    template_files: list[dict],
    *,
    summary: dict | None = None,
    parse_storage: dict | None = None,
) -> dict:
    project = store.require_project_for_update(project_id)
    payload = complete_parse_state(
        project,
        tender_files,
        template_files,
        summary=summary,
        parse_storage=parse_storage,
    )
    store.persist_project_state(project)
    return payload


def build_docx_blocks_bytes(*blocks: str | list[list[str]]) -> bytes:
    file_obj = io.BytesIO()
    doc = Document()
    for block in blocks:
        if isinstance(block, str):
            doc.add_paragraph(block)
            continue
        if not block:
            continue
        column_count = max(len(row) for row in block)
        table = doc.add_table(rows=len(block), cols=column_count)
        for row_index, row in enumerate(block):
            for col_index in range(column_count):
                table.cell(row_index, col_index).text = row[col_index] if col_index < len(row) else ""
    doc.save(file_obj)
    return file_obj.getvalue()


def build_appendix_docx_bytes() -> bytes:
    file_obj = io.BytesIO()
    doc = Document()
    doc.add_paragraph("附表1：供货范围空表")
    table = doc.add_table(rows=3, cols=3)
    values = [
        ["序号", "设备名称", "投标响应"],
        ["1", "风力发电机组", ""],
        ["2", "塔筒", ""],
    ]
    for row_index, row in enumerate(values):
        for col_index, value in enumerate(row):
            table.cell(row_index, col_index).text = value
    doc.save(file_obj)
    return file_obj.getvalue()


def build_appendix_with_merges_docx_bytes() -> bytes:
    """Build an RFP-like docx whose appendix table uses both horizontal and vertical
    cell merges, so we can assert that the parser preserves these structures end-to-end."""

    file_obj = io.BytesIO()
    doc = Document()
    doc.add_paragraph("附表D.1 标准及风电场空气密度功率曲线")
    table = doc.add_table(rows=4, cols=4)
    table.style = "Table Grid"
    # Row 0 header: merge all 4 cells into one banner
    table.cell(0, 0).text = "机型：投标机型1"
    table.cell(0, 0).merge(table.cell(0, 3))
    # Row 1 sub-header: merge last two columns into "对比图"
    headers = ["风速区间(m/s)", "区间平均风速(m/s)", "标准空气密度下功率(kW)", "对比图"]
    for col_index, value in enumerate(headers):
        table.cell(1, col_index).text = value
    table.cell(1, 3).merge(table.cell(1, 3))
    # Row 2: data row, with cols 2-3 vertically merged into row 3 (vMerge)
    table.cell(2, 0).text = "0.00-0.50"
    table.cell(2, 1).text = "0"
    table.cell(2, 2).text = "/"
    table.cell(2, 3).text = "/"
    # Row 3: another data row; col 3 merged into row 2's col 3 (vertical)
    table.cell(3, 0).text = "0.50-1.00"
    table.cell(3, 1).text = "0.5"
    table.cell(3, 2).text = "/"
    table.cell(3, 3).text = "/"
    table.cell(2, 3).merge(table.cell(3, 3))
    doc.save(file_obj)
    return file_obj.getvalue()


def build_business_attachment_templates_docx_bytes() -> bytes:
    file_obj = io.BytesIO()
    doc = Document()
    doc.add_paragraph("第一章 招标公告")
    doc.add_paragraph("此处为普通正文，不应被提取为商务附件模板。")
    doc.add_paragraph("第六章 投标文件格式")
    doc.add_paragraph("附件1 投标函")
    doc.add_paragraph("致：华能集团")
    doc.add_paragraph("我方已仔细研究招标文件的全部内容，愿意参加本项目投标。")
    doc.add_paragraph("投标人（盖章）：____________")
    doc.add_paragraph("附件2 开标价格表")
    table = doc.add_table(rows=3, cols=3)
    table.style = "Table Grid"
    table.cell(0, 0).text = "开标价格表"
    table.cell(0, 0).merge(table.cell(0, 2))
    values = [
        ["序号", "项目名称", "投标报价"],
        ["1", "", ""],
    ]
    for row_index, row in enumerate(values, start=1):
        for col_index, value in enumerate(row):
            table.cell(row_index, col_index).text = value
    doc.add_paragraph("附件3 法定代表人授权书")
    doc.add_paragraph("本人授权以下代表作为我方合法代理人参加本项目投标。")
    doc.add_paragraph("授权代表签字：____________")
    doc.save(file_obj)
    return file_obj.getvalue()


def build_business_section_tree_docx_bytes() -> bytes:
    file_obj = io.BytesIO()
    doc = Document()
    doc.add_paragraph("目录")
    doc.add_paragraph("第一章 招标公告 1")
    doc.add_paragraph("第二章 供应商须知 8")
    doc.add_paragraph("第三章 评审办法 30")
    doc.add_heading("第一章 招标公告", level=1)
    doc.add_heading("3. 供应商资格要求", level=2)
    doc.add_paragraph("3.1 供应商须为中华人民共和国境内合法注册的独立法人。")
    doc.add_heading("第二章 供应商须知", level=1)
    doc.add_heading("供应商须知前附表", level=2)
    table = doc.add_table(rows=2, cols=3)
    for col, text in enumerate(["条款号", "条款名称", "编列内容"]):
        table.cell(0, col).text = text
    for col, text in enumerate(["1.1.2", "采购人", "示例采购人"]):
        table.cell(1, col).text = text
    doc.add_heading("第三章 评审办法", level=1)
    doc.add_heading("商务评分标准", level=2)
    doc.add_paragraph("企业业绩评分标准。")
    doc.save(file_obj)
    return file_obj.getvalue()


def build_business_section_tree_toc_docx_bytes() -> bytes:
    file_obj = io.BytesIO()
    doc = Document()
    doc.add_paragraph("目录")
    doc.add_paragraph("第一章 招标公告 2")
    doc.add_paragraph("3. 供应商资格要求 5")
    doc.add_paragraph("第二章 供应商须知 8")
    doc.add_paragraph("第一章 招标公告")
    doc.add_paragraph("3. 供应商资格要求")
    doc.add_paragraph("3.1 供应商须为中华人民共和国境内合法注册的独立法人。")
    doc.add_paragraph("第二章 供应商须知")
    doc.add_paragraph("供应商须知前附表")
    doc.save(file_obj)
    return file_obj.getvalue()


def build_business_multilevel_template_cluster_docx_bytes() -> bytes:
    file_obj = io.BytesIO()
    doc = Document()
    doc.add_paragraph("第一章 招标公告")
    doc.add_paragraph("投标文件格式目录")
    doc.add_paragraph("附件2 投标价格表 ........ 12")
    doc.add_page_break()
    doc.add_paragraph("第六章 投标文件格式")
    doc.add_paragraph("附件2 投标价格表")
    doc.add_paragraph("A投标价格总表")
    doc.add_paragraph("表1 A-1  标段一")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "序号"
    table.cell(0, 1).text = "价格"
    table.cell(1, 0).text = "1"
    table.cell(1, 1).text = ""
    doc.add_page_break()
    doc.add_paragraph("D 技术服务的分项报价")
    doc.add_paragraph("D-1除质保期服务外的技术指导")
    next_table = doc.add_table(rows=1, cols=2)
    next_table.cell(0, 0).text = "服务"
    next_table.cell(0, 1).text = "报价"
    doc.save(file_obj)
    return file_obj.getvalue()


def build_business_attachment_templates_with_toc_docx_bytes() -> bytes:
    file_obj = io.BytesIO()
    doc = Document()
    doc.add_paragraph("目录")
    doc.add_paragraph("第六章 投标文件格式 108")
    doc.add_paragraph("附件1 投标函 109")
    doc.add_paragraph("附件3 货物规格一览表 110")
    doc.add_paragraph("附件6 履约保证函格式承诺书和质量保函 111")
    doc.add_paragraph("第一章 招标公告")
    doc.add_paragraph("普通招标公告正文。")
    doc.add_paragraph("第六章 投标文件格式")
    doc.add_paragraph("附件1 投标函")
    doc.add_paragraph("致：华能集团")
    doc.add_paragraph("投标人（盖章）：____________")
    doc.add_paragraph("附件3 货物规格一览表")
    table = doc.add_table(rows=3, cols=4)
    table.style = "Table Grid"
    values = [
        ["序号", "货物名称", "规格型号", "数量"],
        ["1", "风力发电机组", "", ""],
        ["2", "塔筒", "", ""],
    ]
    for row_index, row in enumerate(values):
        for col_index, value in enumerate(row):
            table.cell(row_index, col_index).text = value
    doc.add_paragraph("附件6 履约保证函格式承诺书和质量保函")
    doc.add_paragraph("我方承诺按招标文件要求提交履约保证函并承担质量保函责任。")
    doc.add_paragraph("投标人（盖章）：____________")
    doc.save(file_obj)
    return file_obj.getvalue()


def build_business_fingerprint_only_tables_docx_bytes() -> bytes:
    file_obj = io.BytesIO()
    doc = Document()
    doc.add_paragraph("第一章 招标公告")
    doc.add_paragraph("本章为公告。")
    doc.add_heading("商务标格式", level=1)
    doc.add_paragraph("投标报价明细")
    table = doc.add_table(rows=3, cols=4)
    table.style = "Table Grid"
    values = [
        ["序号", "货物名称", "规格型号", "数量"],
        ["1", "风力发电机组", "", ""],
        ["2", "塔筒", "", ""],
    ]
    for row_index, row in enumerate(values):
        for col_index, value in enumerate(row):
            table.cell(row_index, col_index).text = value
    doc.add_heading("合同条款", level=1)
    doc.add_paragraph("本章不属于投标文件格式。")
    doc.save(file_obj)
    return file_obj.getvalue()


def build_business_commitment_template_alignment_docx_bytes() -> bytes:
    file_obj = io.BytesIO()
    doc = Document()
    doc.add_paragraph("第二章 投标人须知")
    doc.add_paragraph("投标人须无条件承诺在本采购项目第一台合同设备供货前取得本条a和b所述材料，需提供承诺书。")
    doc.add_heading("第六章 投标文件格式", level=1)
    doc.add_paragraph("附件1 材料取得承诺书")
    doc.add_paragraph("我方承诺在本采购项目第一台合同设备供货前取得本条a和b所述材料。")
    doc.add_paragraph("投标人（盖章）：____________")
    doc.save(file_obj)
    return file_obj.getvalue()


def field_by_key(items: list[dict], key: str) -> dict:
    return next(item for item in items if item["key"] == key)


def sample_evaluation_docx_bytes() -> bytes:
    return build_docx_blocks_bytes(
        "第三章 评标办法（综合评估法）",
        "附表2：技术评分标准表",
        [
            ["序号", "评分项", "分值", "得分点", "证明材料要求"],
            ["1", "技术方案", "30分", "总体方案完整、技术路线先进得满分。", "提供技术方案和技术承诺函。"],
            ["2", "供货保障", "10分", "供货计划合理、保障措施充分得满分。", "提供供货计划。"],
        ],
        "附表3：商务评分标准表",
        [
            ["序号", "评分项", "分值", "得分点", "证明材料要求"],
            ["1", "企业业绩", "20分", "近三年同类风电项目业绩满足要求得满分。", "提供合同或中标通知书。"],
            ["2", "财务状况", "10分", "财务状况良好得满分。", "提供审计报告。"],
        ],
        "附表4：投标报价评分标准",
        [
            ["序号", "评分项", "满分", "评分办法"],
            ["1", "投标报价", "100分", "以评标基准价为基础计算报价得分。"],
        ],
        "附表5：投标度电成本评分标准",
        [
            ["序号", "评分项", "满分", "评分办法"],
            ["1", "度电成本", "100分", "按度电成本由低到高计算得分。"],
        ],
        "附表1：符合性审查标准表",
        [
            ["序号", "审查项目", "审查标准", "证明材料要求"],
            ["1", "投标文件签署", "投标文件按招标文件要求签字盖章。", "提供签字盖章页。"],
        ],
    )


def sample_technical_spec_docx_bytes() -> bytes:
    return build_docx_blocks_bytes(
        "第二卷 技术规范书",
        "1.1.1 项目概况",
        [
            ["项目名称", "华能甘肃100MW风电项目"],
            ["招标编号", "HN-2026-001"],
            ["招标人", "华能集团"],
            ["管理单位", "华能甘肃公司"],
            ["标段规模", "100MW"],
            ["交货周期", "2026年10月1日至2027年3月31日"],
            ["质保期", "5年"],
            ["技术承诺", "投标人应承诺满足全部技术规范。"],
        ],
        "招标机型要求",
        [
            ["参数", "要求"],
            ["单机容量", "6.25MW"],
            ["叶轮直径", "200m"],
            ["轮毂高度", "120m"],
            ["叶片最低点距地", "20m"],
            ["塔筒型式", "钢混塔筒"],
            ["箱变型式", "华式箱变"],
            ["安全等级", "IEC IIB"],
            ["空气密度", "1.225kg/m3"],
            ["风速", "8.5m/s"],
            ["湍流强度", "0.14"],
        ],
        "性能保证指标",
        [
            ["指标", "要求"],
            ["功率曲线", "投标人应提供经认证功率曲线。"],
            ["可利用率", "97%"],
            ["发电量", "年上网电量不少于300GWh"],
            ["涉网性能", "满足高低电压穿越要求。"],
        ],
        "环境适应性要求",
        [
            ["要求", "说明"],
            ["抗低温", "满足-30℃低温运行。"],
            ["抗覆冰防凝露", "具备覆冰及防凝露措施。"],
            ["防潮湿", "适应高湿环境。"],
            ["防雷暴", "配置防雷保护。"],
            ["防风沙", "满足风沙环境防护。"],
            ["抗高温", "满足高温环境运行。"],
        ],
        "专题方案：应提供叶片专题、变桨系统专题、主轴专题、齿轮箱专题。",
        "供货范围：风力发电机组、塔筒、箱变及备品备件。",
        "考核条款：发电量考核、可利用率考核、功率曲线考核、部件考核、认证考核。",
    )


if __name__ == "__main__":
    unittest.main()


class ParsePipelineTestBase(unittest.TestCase):

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        settings.uploads_dir = base / "uploads"
        settings.documents_dir = base / "documents"
        settings.parsed_dir = base / "parsed"
        settings.ensure_dirs()

        store.reset_for_tests()
        store._ensure_db()
        self.technical_appendix_sync_patcher = patch(
            "app.services.bid_project_service.sync_technical_parse_appendices",
            new=AsyncMock(return_value={"status": "synced", "syncedCount": 0}),
        )
        self.technical_appendix_sync_patcher.start()
        self.client = TestClient(app, base_url="http://127.0.0.1:8000")



    def tearDown(self) -> None:
        self.client.close()
        self.technical_appendix_sync_patcher.stop()
        self.temp_dir.cleanup()



    def create_project(self) -> str:
        response = self.client.post(
            "/api/technical/projects",
            json={"name": "解析测试项目", "customerName": "测试业主"},
        )
        response.raise_for_status()
        return response.json()["id"]



    def create_business_project(self) -> str:
        response = self.client.post(
            "/api/business/projects",
            json={"name": "商务解析测试项目", "customerName": "测试业主"},
        )
        response.raise_for_status()
        return response.json()["id"]



    def project_url(self, project_id: str) -> str:
        project = store._require(project_id)
        if project.get("bidType") == "商务标":
            return f"/api/business/projects/{project_id}"
        return f"/api/technical/projects/{project_id}"



    def parse_results_url(self, project_id: str, suffix: str = "") -> str:
        return f"{self.project_url(project_id)}/parse-results{suffix}"
