from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


BACKEND_ROOT = Path(__file__).resolve().parents[1]
NUMBERING_FIXER_PATH = (
    BACKEND_ROOT
    / "opencode"
    / "skills"
    / "bid-tech-assembler"
    / "scripts"
    / "numbering_fixer.py"
)


def _load_numbering_fixer():
    spec = importlib.util.spec_from_file_location(
        "numbering_fixer_regression",
        NUMBERING_FIXER_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


COMMITMENT_LETTER_CLAUSES = [
    "2.1上述承诺电量是基于测风塔轮毂高度处代表年平均风速计算。",
    "2.2 上述承诺电量是基于卖方提供的由EW10.0-220-125机型评估得出，轮毂高度125m，"
    "如果发生机型、轮毂高度变更，卖方须重新评估承诺电量。",
    "2.3 上述承诺电量基于买方提供的风资源信息表。若机位排布、海拔高度等风资源发生变更，"
    "将基于新的信息输入重新进行电量核算并编制发电量承诺表。",
    "2.4上述承诺电量计量点为本项目的送出线路关口表。",
    "2.5上述承诺电量不包括由于非卖方机组原因造成的发电量损失（如电网限电、现场阻工、"
    "居民点过近造成限功率运行或停机、业主方计划停机、电网和升压站可靠性损失、线损和厂用电等）。",
    "2.6上述承诺电量不包括由于不可抗力因素导致的发电量损失（如极端天气、地震、雷击、冰冻、洪水等自然灾害）。",
    "2.7若风场周边未来新建风电场对本风场造成尾流影响，双方应协商并评估周边风电场影响。",
    "2.8对于上述承诺电量的考核须建立在考核期内风机设备由卖方运维的前提下，"
    "并且招标方需要保证现场满足按时维护的条件。",
    "2.9发电量保证期为整机质保期，全场所有风机预验收完成证书签署之日起进入发电量保证考核周期，"
    "自发电量保证考核期第一日起，针对发电量保证值每1年考核一次，在合同约定的质保期结束后统一结算。",
]


def _set_num_id(element, value: int) -> None:
    p_pr = element.get_or_add_pPr()
    num_pr = OxmlElement("w:numPr")
    num_id = OxmlElement("w:numId")
    num_id.set(qn("w:val"), str(value))
    num_pr.append(num_id)
    p_pr.append(num_pr)


def _direct_num_id(paragraph) -> str | None:
    p_pr = paragraph._p.find(qn("w:pPr"))
    if p_pr is None:
        return None
    num_pr = p_pr.find(qn("w:numPr"))
    if num_pr is None:
        return None
    num_id = num_pr.find(qn("w:numId"))
    return num_id.get(qn("w:val")) if num_id is not None else None


def _custom_heading_document():
    doc = Document()
    custom_style = doc.styles.add_style("标题6-标书", WD_STYLE_TYPE.PARAGRAPH)
    custom_style.base_style = doc.styles["Heading 6"]
    _set_num_id(custom_style.element, 1)
    return doc, custom_style


def test_heading_injection_preserves_numid_zero_suppression() -> None:
    numbering_fixer = _load_numbering_fixer()
    doc, custom_style = _custom_heading_document()
    heading = doc.add_paragraph("低风速段出力优势", style=custom_style)
    _set_num_id(heading._p, 0)

    numbering_fixer.inject_prefix_to_headings(doc, "1.7")

    assert heading.text == "1.7.1  低风速段出力优势"
    assert _direct_num_id(heading) == "0"


def test_heading_style_numbering_cleanup_follows_based_on_chain() -> None:
    numbering_fixer = _load_numbering_fixer()
    doc, custom_style = _custom_heading_document()
    doc.add_paragraph("低风速段出力优势", style=custom_style)

    assert numbering_fixer.strip_numPr_from_heading_styles(doc) == 1

    custom_p_pr = custom_style.element.find(qn("w:pPr"))
    assert custom_p_pr is not None
    assert custom_p_pr.find(qn("w:numPr")) is None


def test_heading_paragraph_cleanup_keeps_suppression_but_removes_active_numbering() -> None:
    numbering_fixer = _load_numbering_fixer()
    doc, custom_style = _custom_heading_document()
    suppressed = doc.add_paragraph("低风速段出力优势", style=custom_style)
    active = doc.add_paragraph("降载优势", style=custom_style)
    body_list = doc.add_paragraph("正文列表")
    _set_num_id(suppressed._p, 0)
    _set_num_id(active._p, 7)
    _set_num_id(body_list._p, 8)

    assert numbering_fixer.strip_numPr_from_body(doc) == 1

    assert _direct_num_id(suppressed) == "0"
    assert _direct_num_id(active) is None
    assert _direct_num_id(body_list) == "8"


def test_body_strip_keeps_commitment_letter_clause_numbering() -> None:
    """承诺函 2.1~2.9 的条款编号有法律引用意义，不能当成伪标题编号擦掉。

    条款文本取自素材《发电小时数承诺函（承诺保证值）》，覆盖「编号后有空格」与
    「编号后无空格」两种写法——历史上前者被擦、后者保留，同一份文件被擦掉一半。
    """
    numbering_fixer = _load_numbering_fixer()
    doc = Document()
    paragraphs = [doc.add_paragraph(text) for text in COMMITMENT_LETTER_CLAUSES]

    assert numbering_fixer.strip_handwritten_numbering_in_body(doc) == 0
    assert [p.text for p in paragraphs] == COMMITMENT_LETTER_CLAUSES


def test_body_strip_still_removes_pseudo_heading_numbering() -> None:
    numbering_fixer = _load_numbering_fixer()
    doc = Document()
    paragraphs = [
        doc.add_paragraph("7.10 符合招标公告及招标文件要求的业绩情况"),
        doc.add_paragraph("5.1 项目概况"),
    ]

    assert numbering_fixer.strip_handwritten_numbering_in_body(doc) == 2
    assert [p.text for p in paragraphs] == [
        "符合招标公告及招标文件要求的业绩情况",
        "项目概况",
    ]
