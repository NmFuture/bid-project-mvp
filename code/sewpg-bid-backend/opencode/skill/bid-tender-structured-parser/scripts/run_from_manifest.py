from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


SKILL_NAME = "bid-tender-structured-parser"


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    keywords: tuple[str, ...]


CATEGORIES: tuple[Category, ...] = (
    Category("scoring_criteria", "评分细则", ("评分", "得分", "分值", "证明材料", "商务评分", "技术评分")),
    Category(
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
    Category(
        "turbine_parameters",
        "风机核心参数",
        ("单机容量", "叶轮直径", "轮毂高度", "叶片最低点", "塔筒型式", "箱变型式", "安全等级", "空气密度", "风速", "湍流强度"),
    ),
    Category("performance_guarantees", "性能保证指标", ("功率曲线", "可利用率", "发电量", "涉网性能", "保证率", "性能保证")),
    Category("environment_adaptation", "环境适应性要求", ("低温", "覆冰", "防凝露", "潮湿", "防雷暴", "防雷", "风沙", "高温", "环境适应性")),
    Category("topic_plans", "专题方案要求", ("专题方案", "叶片", "变桨系统", "主轴", "齿轮箱", "总体方案", "技术先进性")),
    Category("tables_and_scope", "附表和供货范围", ("附表", "供货范围", "供货清单", "供货界面")),
    Category("assessment_terms", "考核条款", ("考核", "发电量考核", "可利用率考核", "功率曲线考核", "部件考核", "认证考核")),
)


DATE_PATTERN = re.compile(r"(?P<year>20\d{2})\s*(?:年|[-/.])\s*(?P<month>\d{1,2})\s*(?:月|[-/.])\s*(?P<day>\d{1,2})\s*日?")
LABEL_VALUE_PATTERN = re.compile(r"^\s*(?P<label>[^:：]{2,40})\s*[:：]\s*(?P<value>.+?)\s*$")
LEADING_NUMBER_PATTERN = re.compile(r"^\s*(?:第?[一二三四五六七八九十百千0-9]+[章节条]?|[（(]?\d+[）)]?)\s*[、.．\s]+")
START_DATE_KEYWORDS = ("起始日期", "开始日期", "开工日期", "计划开工", "服务期自", "合同开始")
END_DATE_KEYWORDS = ("投标截止", "截止日期", "截止时间", "结束日期", "竣工日期", "完成日期", "服务期至")


def normalize_date(match: re.Match[str]) -> str:
    try:
        return date(int(match.group("year")), int(match.group("month")), int(match.group("day"))).isoformat()
    except ValueError:
        return ""


def find_dates(text: str) -> list[str]:
    return [value for value in (normalize_date(match) for match in DATE_PATTERN.finditer(text)) if value]


def strip_leading_number(text: str) -> str:
    return LEADING_NUMBER_PATTERN.sub("", text).strip()


def split_label_value(line: str, fallback_label: str) -> tuple[str, str]:
    normalized = strip_leading_number(line)
    match = LABEL_VALUE_PATTERN.match(normalized)
    if match:
        label = strip_leading_number(match.group("label")).strip()
        value = match.group("value").strip(" ；;。")
        return label or fallback_label, value or normalized
    return fallback_label, normalized


def first_category(line: str) -> Category | None:
    if "考核" in line:
        return next(category for category in CATEGORIES if category.key == "assessment_terms")
    for category in CATEGORIES:
        if any(keyword in line for keyword in category.keywords):
            return category
    return None


def record_dates(line: str, dates: list[str], project_dates: dict[str, str]) -> None:
    if not dates:
        return
    has_start = any(keyword in line for keyword in START_DATE_KEYWORDS)
    has_end = any(keyword in line for keyword in END_DATE_KEYWORDS)
    has_range = any(token in line for token in ("至", "到", "止", "~", "—", "-"))
    if has_start and not project_dates["startDate"]:
        project_dates["startDate"] = dates[0]
    if has_end and not project_dates["endDate"]:
        project_dates["endDate"] = dates[-1]
    if has_range and len(dates) >= 2:
        project_dates["startDate"] = project_dates["startDate"] or dates[0]
        project_dates["endDate"] = project_dates["endDate"] or dates[-1]


def parse(manifest: dict[str, Any]) -> dict[str, Any]:
    documents = [item for item in manifest.get("documents") or [] if isinstance(item, dict)]
    items: list[dict[str, Any]] = []
    category_map: dict[str, list[dict[str, Any]]] = {category.key: [] for category in CATEGORIES}
    project_basics: dict[str, str] = {}
    project_dates = {"startDate": "", "endDate": ""}
    date_item_ids: list[str] = []
    seen: set[tuple[str, str, str]] = set()

    for document in documents:
        document_id = str(document.get("id") or "")
        source_file = str(document.get("name") or document_id or "招标文件")
        text_path = Path(str(document.get("textPath") or ""))
        if not text_path.exists():
            continue
        for line_no, raw_line in enumerate(text_path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("# "):
                continue
            category = first_category(line)
            dates = find_dates(line)
            record_dates(line, dates, project_dates)
            if category is None:
                continue
            label, value = split_label_value(line, category.label)
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
        {"key": category.key, "label": category.label, "count": len(category_map[category.key]), "items": category_map[category.key]}
        for category in CATEGORIES
        if category_map[category.key]
    ]
    return {
        "items": items,
        "structured": {
            "schemaVersion": "bid-tender-structured-v1",
            "targetSkill": SKILL_NAME,
            "mode": "opencode-skill",
            "projectDates": {**project_dates, "itemIds": date_item_ids},
            "projectBasics": project_basics,
            "categories": categories,
            "categoryCounts": {category["label"]: category["count"] for category in categories},
        },
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: s1parse <manifest>", file=sys.stderr)
        return 64

    manifest_path = Path(sys.argv[1])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output_path = Path(str(manifest.get("structuredResultPath") or manifest_path.with_name("s1_structured_result.json")))
    result = parse(manifest)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "schemaVersion": "bid-tender-structured-v1",
        "targetSkill": SKILL_NAME,
        "outputFile": str(output_path),
        "summary": {
            "itemCount": len(result["items"]),
            "categoryCounts": result["structured"]["categoryCounts"],
            "projectDates": {
                "startDate": result["structured"]["projectDates"].get("startDate") or "",
                "endDate": result["structured"]["projectDates"].get("endDate") or "",
            },
        },
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
