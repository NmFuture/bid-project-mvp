import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

REQUIRED_TOP_LEVEL = ["schema_version", "document_name", "outline_source", "context", "sections", "review_items"]
REQUIRED_OUTLINE_SOURCE = ["section_title", "source_text", "confidence"]
REQUIRED_SECTION = ["id", "title", "level", "required_status", "source_text", "children"]
REQUIRED_REVIEW_ITEM = ["message", "source_text", "suggested_section_id", "required_status"]
VALID_REQUIRED_STATUS = {"必要", "可选", "待确认"}
VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_OUTLINE_SOURCE_TYPE = {
    "history_bid_auto_toc",
    "history_bid_toc",
    "history_bid_headings",
    "history_bid_unknown",
    "tender_matched",
    "tender_format_toc",
}


def type_name(value):
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return type(value).__name__


def require_keys(obj, keys, path, errors):
    if not isinstance(obj, dict):
        errors.append(f"{path}: expected object, got {type_name(obj)}")
        return
    for key in keys:
        if key not in obj:
            errors.append(f"{path}.{key}: missing required field")


def validate_outline_source(value, errors):
    require_keys(value, REQUIRED_OUTLINE_SOURCE, "outline_source", errors)
    if not isinstance(value, dict):
        return
    confidence = value.get("confidence")
    if confidence not in VALID_CONFIDENCE:
        errors.append("outline_source.confidence: must be one of high/medium/low")
    for key in ["section_title", "source_text"]:
        if key in value and not isinstance(value[key], str):
            errors.append(f"outline_source.{key}: expected string")
    source_type = value.get("source_type")
    if source_type is not None and source_type not in VALID_OUTLINE_SOURCE_TYPE:
        errors.append("outline_source.source_type: unsupported value")
    history_document_name = value.get("history_document_name")
    if history_document_name is not None and not isinstance(history_document_name, str):
        errors.append("outline_source.history_document_name: expected string")


def validate_section(section, path, errors, section_ids):
    require_keys(section, REQUIRED_SECTION, path, errors)
    if not isinstance(section, dict):
        return
    section_id = section.get("id")
    if not isinstance(section_id, str) or not section_id:
        errors.append(f"{path}.id: expected non-empty string")
    elif section_id in section_ids:
        errors.append(f"{path}.id: duplicate section id {section_id}")
    else:
        section_ids.add(section_id)
    for key in ["title", "source_text"]:
        if key in section and not isinstance(section[key], str):
            errors.append(f"{path}.{key}: expected string")
    if "level" in section and not isinstance(section["level"], int):
        errors.append(f"{path}.level: expected integer")
    if section.get("required_status") not in VALID_REQUIRED_STATUS:
        errors.append(f"{path}.required_status: must be one of 必要/可选/待确认")
    children = section.get("children")
    if not isinstance(children, list):
        errors.append(f"{path}.children: expected array")
        return
    for index, child in enumerate(children):
        validate_section(child, f"{path}.children[{index}]", errors, section_ids)


def validate_review_item(item, path, errors, section_ids):
    require_keys(item, REQUIRED_REVIEW_ITEM, path, errors)
    if not isinstance(item, dict):
        return
    for key in ["message", "source_text"]:
        if key in item and not isinstance(item[key], str):
            errors.append(f"{path}.{key}: expected string")
    if item.get("required_status") not in VALID_REQUIRED_STATUS:
        errors.append(f"{path}.required_status: must be one of 必要/可选/待确认")
    suggested = item.get("suggested_section_id")
    if suggested is not None and suggested not in section_ids:
        errors.append(f"{path}.suggested_section_id: must be an existing section id or null")


def validate(data):
    errors = []
    require_keys(data, REQUIRED_TOP_LEVEL, "$", errors)
    if not isinstance(data, dict):
        return errors
    if data.get("schema_version") != "business_bid_outline.v1":
        errors.append("schema_version: must equal business_bid_outline.v1")
    if "document_name" in data and not isinstance(data["document_name"], str):
        errors.append("document_name: expected string")
    validate_outline_source(data.get("outline_source"), errors)
    if "context" in data and not isinstance(data["context"], dict):
        errors.append("context: expected object")
    sections = data.get("sections")
    section_ids = set()
    if not isinstance(sections, list):
        errors.append("sections: expected array")
    else:
        for index, section in enumerate(sections):
            validate_section(section, f"sections[{index}]", errors, section_ids)
    review_items = data.get("review_items")
    if not isinstance(review_items, list):
        errors.append("review_items: expected array")
    else:
        for index, item in enumerate(review_items):
            validate_review_item(item, f"review_items[{index}]", errors, section_ids)
    return errors


def main():
    parser = argparse.ArgumentParser(description="Validate business_bid_outline.v1 outline.json.")
    parser.add_argument("outline_json", help="Path to outline.json")
    args = parser.parse_args()

    try:
        data = json.loads(Path(args.outline_json).read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}")
        return 1
    errors = validate(data)
    if errors:
        print("ERROR")
        for error in errors:
            print(f"- {error}")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
