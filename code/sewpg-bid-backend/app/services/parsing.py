from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from app.core.config import settings
from app.services.opencode_client import OpencodeClient

WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
TEXT_PREVIEW_LIMIT = 600
PARSE_SKILL_NAME = "bid-tender-structured-parser"


@dataclass(frozen=True)
class ParseCategory:
    key: str
    label: str
    keywords: tuple[str, ...]


PARSE_CATEGORIES: tuple[ParseCategory, ...] = (
    ParseCategory("scoring_criteria", "评分细则", ("评分", "得分", "分值", "证明材料", "商务评分", "技术评分")),
    ParseCategory(
        "project_basics",
        "项目基础信息",
        (
            "项目名称",
            "招标编号",
            "项目编号",
            "招标人",
            "管理单位",
            "建设单位",
            "业主",
            "标段规模",
            "招标规模",
            "建设规模",
            "交货周期",
            "交货期",
            "质保期",
            "质量保证期",
            "技术承诺",
            "起始日期",
            "开工日期",
            "截止日期",
            "截止时间",
            "结束日期",
        ),
    ),
    ParseCategory(
        "turbine_parameters",
        "风机核心参数",
        (
            "单机容量",
            "叶轮直径",
            "轮毂高度",
            "叶片最低点",
            "塔筒型式",
            "箱变型式",
            "安全等级",
            "空气密度",
            "风速",
            "湍流强度",
        ),
    ),
    ParseCategory(
        "performance_guarantees",
        "性能保证指标",
        ("功率曲线", "可利用率", "发电量", "涉网性能", "保证率", "性能保证"),
    ),
    ParseCategory(
        "environment_adaptation",
        "环境适应性要求",
        ("低温", "覆冰", "防凝露", "潮湿", "防雷暴", "防雷", "风沙", "高温", "环境适应性"),
    ),
    ParseCategory(
        "topic_plans",
        "专题方案要求",
        ("专题方案", "叶片", "变桨系统", "主轴", "齿轮箱", "总体方案", "技术先进性"),
    ),
    ParseCategory("tables_and_scope", "附表和供货范围", ("附表", "供货范围", "供货清单", "供货界面")),
    ParseCategory(
        "assessment_terms",
        "考核条款",
        ("考核", "发电量考核", "可利用率考核", "功率曲线考核", "部件考核", "认证考核"),
    ),
)

DATE_PATTERN = re.compile(
    r"(?P<year>20\d{2})\s*(?:年|[-/.])\s*(?P<month>\d{1,2})\s*(?:月|[-/.])\s*(?P<day>\d{1,2})\s*日?"
)
LABEL_VALUE_PATTERN = re.compile(r"^\s*(?P<label>[^:：]{2,40})\s*[:：]\s*(?P<value>.+?)\s*$")
LEADING_NUMBER_PATTERN = re.compile(r"^\s*(?:第?[一二三四五六七八九十百千0-9]+[章节条]?|[（(]?\d+[）)]?)\s*[、.．\s]+")

START_DATE_KEYWORDS = ("起始日期", "开始日期", "开工日期", "计划开工", "服务期自", "合同开始")
END_DATE_KEYWORDS = ("投标截止", "截止日期", "截止时间", "结束日期", "竣工日期", "完成日期", "服务期至")


def parsed_project_dir(project_id: str) -> Path:
    path = settings.parsed_dir / project_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _normalize_text(raw_text: str) -> str:
    lines = [line.rstrip() for line in raw_text.replace("\r\n", "\n").split("\n")]
    compact: list[str] = []
    previous_blank = False
    for line in lines:
        blank = not line.strip()
        if blank and previous_blank:
            continue
        compact.append(line)
        previous_blank = blank
    return "\n".join(compact).strip()


def extract_docx_text(path: Path) -> str:
    pieces: list[str] = []
    with zipfile.ZipFile(path) as archive:
        with archive.open("word/document.xml") as xml_file:
            for _, element in ET.iterparse(xml_file, events=("end",)):
                if element.tag == f"{WORD_NAMESPACE}t":
                    pieces.append(element.text or "")
                elif element.tag == f"{WORD_NAMESPACE}tab":
                    pieces.append("\t")
                elif element.tag in {f"{WORD_NAMESPACE}br", f"{WORD_NAMESPACE}cr"}:
                    pieces.append("\n")
                elif element.tag == f"{WORD_NAMESPACE}p":
                    pieces.append("\n")
                    element.clear()
    return _normalize_text("".join(pieces))


def extract_pdf_text(path: Path) -> tuple[str, dict[str, Any]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("未安装 pypdf，当前无法解析 PDF。") from exc

    reader = PdfReader(str(path))
    page_count = len(reader.pages)
    empty_pages = 0
    page_texts: list[str] = []
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if not text:
            empty_pages += 1
        page_texts.append(text)

    warnings: list[str] = []
    if page_count and empty_pages == page_count:
        warnings.append("PDF 未提取到文本，疑似扫描件。当前 MVP 暂不支持 OCR。")
    elif empty_pages:
        warnings.append(f"PDF 有 {empty_pages} 页未提取到文本。")

    return _normalize_text("\n\n".join(page_texts)), {
        "pageCount": page_count,
        "warnings": warnings,
    }


def _normalize_date_match(match: re.Match[str]) -> str:
    try:
        parsed = date(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
        )
    except ValueError:
        return ""
    return parsed.isoformat()


def _find_dates(text: str) -> list[str]:
    dates: list[str] = []
    for match in DATE_PATTERN.finditer(text):
        normalized = _normalize_date_match(match)
        if normalized:
            dates.append(normalized)
    return dates


def _strip_leading_number(text: str) -> str:
    return LEADING_NUMBER_PATTERN.sub("", text).strip()


def _split_label_value(line: str, fallback_label: str) -> tuple[str, str]:
    normalized = _strip_leading_number(line)
    match = LABEL_VALUE_PATTERN.match(normalized)
    if match:
        label = _strip_leading_number(match.group("label")).strip()
        value = match.group("value").strip(" ；;。")
        return label or fallback_label, value or normalized
    return fallback_label, normalized


def _first_matching_category(line: str) -> ParseCategory | None:
    for category in PARSE_CATEGORIES:
        if any(keyword in line for keyword in category.keywords):
            return category
    return None


def _record_project_date(line: str, dates: list[str], project_dates: dict[str, str]) -> None:
    if not dates:
        return
    has_start_keyword = any(keyword in line for keyword in START_DATE_KEYWORDS)
    has_end_keyword = any(keyword in line for keyword in END_DATE_KEYWORDS)
    has_range_hint = any(token in line for token in ("至", "到", "止", "~", "—", "-"))

    if has_start_keyword and not project_dates["startDate"]:
        project_dates["startDate"] = dates[0]
    if has_end_keyword and not project_dates["endDate"]:
        project_dates["endDate"] = dates[-1]
    if has_range_hint and len(dates) >= 2:
        if not project_dates["startDate"]:
            project_dates["startDate"] = dates[0]
        if not project_dates["endDate"]:
            project_dates["endDate"] = dates[-1]


def _extract_structured_requirements(documents: list[dict[str, Any]], texts_by_id: dict[str, str]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    category_map: dict[str, list[dict[str, Any]]] = {category.key: [] for category in PARSE_CATEGORIES}
    project_basics: dict[str, str] = {}
    project_dates = {"startDate": "", "endDate": ""}
    date_item_ids: list[str] = []
    seen: set[tuple[str, str, str]] = set()

    for document in documents:
        document_id = str(document.get("id") or "")
        source_file = str(document.get("name") or document_id or "招标文件")
        for line_no, raw_line in enumerate(texts_by_id.get(document_id, "").splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("# "):
                continue

            category = _first_matching_category(line)
            dates = _find_dates(line)
            _record_project_date(line, dates, project_dates)
            if category is None:
                continue

            label, value = _split_label_value(line, category.label)
            dedupe_key = (category.key, source_file, line)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            item = {
                "id": f"REQ-{len(items) + 1:04d}",
                "type": category.label,
                "category": category.key,
                "title": label,
                "keyEntity": label,
                "keyValue": value,
                "value": value,
                "sourceFile": source_file,
                "sourceDocumentId": document_id,
                "evidence": line,
                "evidenceLocation": f"L{line_no}",
                "evidenceLine": line_no,
                "confidence": 0.82,
            }
            if dates:
                item["dates"] = dates
                date_item_ids.append(item["id"])
            items.append(item)
            category_map[category.key].append(item)
            if category.key == "project_basics":
                project_basics.setdefault(label, value)

    categories = [
        {
            "key": category.key,
            "label": category.label,
            "count": len(category_map[category.key]),
            "items": category_map[category.key],
        }
        for category in PARSE_CATEGORIES
        if category_map[category.key]
    ]
    return {
        "items": items,
        "structured": {
            "schemaVersion": "bid-tender-structured-v1",
            "targetSkill": PARSE_SKILL_NAME,
            "mode": "local-structured-parser",
            "projectDates": {
                **project_dates,
                "itemIds": date_item_ids,
            },
            "projectBasics": project_basics,
            "categories": categories,
            "categoryCounts": {category["label"]: category["count"] for category in categories},
        },
    }


def _build_tender_parse_prompt(skill_manifest_path: Path) -> str:
    return f"""
Use the {PARSE_SKILL_NAME} skill.

你现在在做 S1 招标文件结构化解析。请调用解析 Skill 读取 manifest 中的多份招标文件文本，输出可直接给后端使用的结构化 JSON。

manifest：{skill_manifest_path}

请直接调用一次 Bash 工具执行下面命令，Bash 工具 timeout 必须设置为 600000 毫秒或更高。不要先检查工作目录，不要先执行 pwd/ls/cat/read/glob，不要拆成多条命令，不要改写命令或路径。命令会把完整结构化 JSON 写入 manifest.structuredResultPath，并只在 stdout 打印小型摘要 JSON：

s1parse {skill_manifest_path}

只返回命令 stdout 中的小型 JSON，不要返回解释文字，不要使用 Markdown 代码块。
返回格式必须是：
{{
  "schemaVersion": "bid-tender-structured-v1",
  "targetSkill": "{PARSE_SKILL_NAME}",
  "outputFile": "manifest 中的 structuredResultPath",
  "summary": {{"itemCount": 0, "categoryCounts": {{}}, "projectDates": {{"startDate": "", "endDate": ""}}}}
}}

解析目标必须覆盖：
1. 评分细则：评分项、得分点、证明材料要求。
2. 项目基础信息：项目名称、招标编号、招标人/管理单位、规模、交货周期、质保期、技术承诺。
3. 风机核心参数：单机容量、叶轮直径、轮毂高度、叶片最低点距地、塔筒型式、箱变型式、安全等级、空气密度、风速、湍流强度。
4. 性能保证指标：功率曲线、可利用率、发电量、涉网性能。
5. 环境适应性要求：低温、覆冰防凝露、潮湿、防雷暴、防风沙、高温。
6. 专题方案要求：叶片、变桨系统、主轴、齿轮箱等专题。
7. 附表、供货范围和考核条款。
8. 项目起始日期和截止日期。

每条 item 必须保留 sourceFile、sourceDocumentId、evidence、evidenceLocation。
""".strip()


def _resolve_skill_structured_result(
    result: dict[str, Any],
    *,
    local_result: dict[str, Any],
) -> dict[str, Any]:
    output_file = Path(str(result.get("outputFile") or ""))
    if output_file.exists():
        loaded = json.loads(output_file.read_text(encoding="utf-8"))
        if isinstance(loaded, dict) and isinstance(loaded.get("items"), list):
            resolved = loaded
        else:
            resolved = local_result
    elif isinstance(result.get("items"), list):
        resolved = {
            "items": result.get("items") or [],
            "structured": result.get("structured") if isinstance(result.get("structured"), dict) else {},
        }
    else:
        resolved = local_result

    structured = resolved.setdefault("structured", {})
    if isinstance(structured, dict):
        structured["targetSkill"] = PARSE_SKILL_NAME
        structured["mode"] = "opencode-skill"
        structured["opencodeOutput"] = result.get("opencodeOutput") or {}
    return resolved


def _run_parse_skill(
    skill_manifest_path: Path,
    *,
    local_result: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    if not settings.s1_parse_opencode_enabled:
        return local_result, ""
    try:
        result = OpencodeClient().generate_tender_parse_with_trace(_build_tender_parse_prompt(skill_manifest_path))
        return _resolve_skill_structured_result(result, local_result=local_result), ""
    except RuntimeError as exc:
        fallback = json.loads(json.dumps(local_result, ensure_ascii=False))
        structured = fallback.setdefault("structured", {})
        if isinstance(structured, dict):
            structured["mode"] = "local-structured-parser"
            structured["opencodeError"] = str(exc)
        return fallback, f"S1 解析 Skill 调用失败，已使用本地结构化解析兜底：{exc}"


def parse_tender_documents(project_id: str, tender_files: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    project_dir = parsed_project_dir(project_id)
    documents: list[dict[str, Any]] = []
    combined_parts: list[str] = []
    texts_by_id: dict[str, str] = {}
    warnings: list[str] = []

    for file_record in tender_files:
        file_path = Path(str(file_record["path"]))
        extension = file_path.suffix.lower()
        page_count: int | str = "-"
        file_warnings: list[str] = []

        if extension == ".docx":
            text = extract_docx_text(file_path)
        elif extension == ".md":
            text = file_path.read_text(encoding="utf-8", errors="replace")
        elif extension == ".pdf":
            text, pdf_meta = extract_pdf_text(file_path)
            page_count = pdf_meta["pageCount"]
            file_warnings.extend(pdf_meta["warnings"])
        else:
            text = ""
            file_warnings.append(f"当前 MVP 暂不解析 {extension or '未知'} 类型文件。")

        text = _normalize_text(text)
        text_length = len(text)
        text_path = project_dir / f"{file_record['id']}.txt"
        text_path.write_text(text, encoding="utf-8")

        metadata = {
            "id": file_record["id"],
            "name": file_record["name"],
            "textPath": str(text_path),
            "textLength": text_length,
            "pageCount": page_count,
            "warnings": file_warnings,
        }
        documents.append(metadata)
        texts_by_id[str(file_record["id"])] = text
        warnings.extend(file_warnings)

        if text:
            combined_parts.append(f"# 文件：{file_record['name']}\n\n{text}")

    combined_text = _normalize_text("\n\n".join(combined_parts))
    combined_text_path = project_dir / "combined.txt"
    combined_text_path.write_text(combined_text, encoding="utf-8")

    structured_result = _extract_structured_requirements(documents, texts_by_id)
    structured_path = project_dir / "s1_structured_result.json"
    structured_path.write_text(json.dumps(structured_result, ensure_ascii=False, indent=2), encoding="utf-8")
    skill_manifest_path = project_dir / "s1_parse_manifest.json"
    skill_manifest = {
        "projectId": project_id,
        "targetSkill": PARSE_SKILL_NAME,
        "combinedTextPath": str(combined_text_path),
        "structuredResultPath": str(structured_path),
        "documents": documents,
        "targets": [
            "评分细则",
            "项目基础信息",
            "风机核心参数",
            "性能保证指标",
            "环境适应性要求",
            "专题方案要求",
            "附表和供货范围",
            "考核条款",
            "项目起止日期",
        ],
    }
    skill_manifest_path.write_text(json.dumps(skill_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    structured_result, skill_warning = _run_parse_skill(skill_manifest_path, local_result=structured_result)
    if skill_warning:
        warnings.append(skill_warning)
    structured_path.write_text(json.dumps(structured_result, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_path = project_dir / "manifest.json"
    manifest = {
        "projectId": project_id,
        "combinedTextPath": str(combined_text_path),
        "documents": documents,
        "structuredResultPath": str(structured_path),
        "skillManifestPath": str(skill_manifest_path),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    items = structured_result["items"]
    structured = structured_result["structured"]
    project_dates = structured["projectDates"]

    summary = {
        "fileCount": len(tender_files),
        "extractedCount": len(items),
        "textLength": len(combined_text),
        "textPreview": combined_text[:TEXT_PREVIEW_LIMIT],
        "warnings": warnings,
        "targetSkill": PARSE_SKILL_NAME,
        "categoryCounts": structured["categoryCounts"],
        "projectDates": {
            "startDate": project_dates.get("startDate") or "",
            "endDate": project_dates.get("endDate") or "",
        },
    }

    return summary, {
        "projectDir": str(project_dir),
        "combinedTextPath": str(combined_text_path),
        "manifestPath": str(manifest_path),
        "structuredResultPath": str(structured_path),
        "skillManifestPath": str(skill_manifest_path),
        "documents": documents,
        "items": items,
        "structured": structured,
        "projectUpdates": {
            "startDate": project_dates.get("startDate") or "",
            "endDate": project_dates.get("endDate") or "",
            "deadline": project_dates.get("endDate") or "",
        },
    }
