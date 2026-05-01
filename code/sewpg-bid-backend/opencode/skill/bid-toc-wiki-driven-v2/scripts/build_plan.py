#!/usr/bin/env python3
"""build_plan.py — 组合 template/tender/attach/wiki 输入，生成最终 JSON 总目录

输入：
- --template  extract_template.py 输出的 JSON（模板 H1/H2 骨架）
- --tender    extract_tender.py 输出的 JSON（项目参数）
- --attach    extract_attach.py 输出的 JSON（附表 outline，可选）
- --wiki      wiki 根目录（用 wiki_lookup.py 取素材清单）
- --title     文档标题（可选，缺省从 tender 组装）
- --output    输出 JSON 路径

输出：JSON（document_title + project + source_files + summary + items），
items[i] = {order, level, number, title, annotation, source, reason}

V2 标签体系：
1. [保留]：模板/wiki 章节可直接沿用。
2. [适配]：章节保留，但后续内容需替换项目、业主、编号、业绩、承诺值等。
3. [新增-招标要求]：招标 specials 明确要求，但模板/wiki 未覆盖。
4. [新增-素材库建议]：wiki/rules 条件触发且模板未覆盖，建议新增。
5. [删除建议]：规则判定不适用，但保留在标注版给人审。
6. [素材内置标题]：素材 merge 时自带的 Heading，已展开为总目录子目录。
"""
import argparse
import copy
import json
import re
import subprocess
import sys
from pathlib import Path
from collections import Counter, defaultdict

SCRIPT_DIR = Path(__file__).parent

TAG_KEEP = "保留"
TAG_ADAPT = "适配"
TAG_TENDER_ADD = "新增-招标要求"
TAG_WIKI_ADD = "新增-素材库建议"
TAG_DELETE = "删除建议"
TAG_INTERNAL = "素材内置标题"
ALL_TAGS = [TAG_KEEP, TAG_ADAPT, TAG_TENDER_ADD, TAG_WIKI_ADD, TAG_DELETE, TAG_INTERNAL]


def load_json(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def load_wiki(wiki_root: Path):
    """调 wiki_lookup.py --list-by-section"""
    r = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "wiki_lookup.py"), "--wiki", str(wiki_root), "--list-by-section"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return json.loads(r.stdout)


def normalize_identity_text(value) -> str:
    return re.sub(r"[\s　,，、.。:：;；()（）\[\]【】{}<>《》\"'`·_\-—/\\|]+", "", str(value or "")).lower()


def split_aliases(value) -> list[str]:
    if isinstance(value, list):
        values = value
    else:
        values = re.split(r"[、,，;/；]+", str(value or ""))
    out = []
    seen = set()
    for item in values:
        text = str(item or "").strip()
        key = normalize_identity_text(text)
        if text and key and key not in seen:
            seen.add(key)
            out.append(text)
    return out


def identity_keys(*values) -> set[str]:
    keys = set()
    for value in values:
        if isinstance(value, (list, tuple, set)):
            keys.update(identity_keys(*value))
            continue
        key = normalize_identity_text(value)
        if key:
            keys.add(key)
    return keys


def material_scope(item: dict) -> str:
    ref = item.get("material_ref") if isinstance(item.get("material_ref"), dict) else {}
    scope = str(item.get("identity_scope") or ref.get("identity_scope") or "").strip().lower()
    if scope:
        return scope
    if str(item.get("scope") or "") == "通用":
        return "general"
    return ""


def filter_wiki_by_project_identity(wiki_items: list[dict], project_identity: dict, tender: dict) -> list[dict]:
    """Filter AI-facing wiki cards by canonical project/customer identity.

    Legacy cards without identity_scope are kept so old wiki data still works.
    """
    if not isinstance(project_identity, dict):
        project_identity = {}
    project_keys = identity_keys(
        project_identity.get("projectId"),
        project_identity.get("projectCode"),
        project_identity.get("projectName"),
        tender.get("code"),
        tender.get("project"),
    )
    customer_keys = identity_keys(
        project_identity.get("customerId"),
        project_identity.get("customerName"),
        project_identity.get("customerCanonicalName"),
        project_identity.get("customerAliases") or [],
        project_identity.get("owner"),
        tender.get("owner"),
    )

    filtered = []
    for item in wiki_items:
        scope = material_scope(item)
        ref = item.get("material_ref") if isinstance(item.get("material_ref"), dict) else {}
        if scope in {"", "general", "通用"}:
            filtered.append(item)
            continue
        if scope == "customer":
            material_customer_keys = identity_keys(
                item.get("customer_id"),
                item.get("customer_name"),
                split_aliases(item.get("customer_aliases")),
                ref.get("customer_id"),
                ref.get("customer_name"),
                split_aliases(ref.get("customer_aliases")),
            )
            if not material_customer_keys or material_customer_keys & customer_keys:
                filtered.append(item)
            continue
        if scope == "project":
            material_project_keys = identity_keys(
                item.get("project_id"),
                item.get("project_code"),
                ref.get("project_id"),
                ref.get("project_code"),
            )
            if not material_project_keys or material_project_keys & project_keys:
                filtered.append(item)
            continue
        filtered.append(item)
    return filtered


def activation_reason(item: dict, tender: dict) -> str:
    """返回空表示激活；非空表示建议删除的原因。"""
    name = item["display_name"]
    owner = tender.get("owner", "")
    site = tender.get("site_flags", {})
    model = tender.get("model_flags", {})
    plot = tender.get("plot_flags", {})

    import re as _re
    m = _re.search(r"与([\u4e00-\u9fa5]{1,8}?)(?:集团|公司|新能源)", name)
    if m:
        expected = m.group(1)
        if expected and expected not in owner:
            return f"业主非{expected}"

    if "齿轮箱" in name and model.get("强制直驱"):
        return "直驱机型不适用齿轮箱专题"

    env_map = {
        "抗低温设计": "低温",
        "抗高温设计": "高温",
        "抗覆冰防凝露设计": "覆冰",
        "抗潮湿防腐蚀设计": "潮湿",
        "防风沙设计": "风沙",
        "防雷保护设计": "雷暴",
        "电气绝缘方案": "高海拔",
        "防紫外线、抗老化、电离辐射设计": "紫外",
        "抗盐雾设计": "盐雾",
        "防盐雾设计": "盐雾",
    }
    if name in env_map:
        key = env_map[name]
        if not site.get(key, False):
            return f"场址未命中{key}"

    if "混塔" in name and not any(s["keyword"] == "混塔" for s in tender.get("specials", [])):
        return "招标未触发混塔要求"

    if "北区" in name and not plot.get("北区"):
        return "地块未命中北区"
    if "南区" in name and not plot.get("南区"):
        return "地块未命中南区"

    return ""


def is_activated(item: dict, tender: dict) -> bool:
    """根据 tender 参数决定 wiki 素材是否激活。"""
    return activation_reason(item, tender) == ""


def tag_for(item: dict) -> str:
    name = item["display_name"]
    if item.get("_delete_reason"):
        return TAG_DELETE
    if item.get("_tag_override"):
        return item["_tag_override"]
    if item.get("scope") == "定制":
        return TAG_ADAPT
    if any(k in name for k in ("业绩", "担保", "关键数据", "技术参数", "承诺", "性能指标", "交货进度")):
        return TAG_ADAPT
    return TAG_KEEP


def template_ref(item: dict) -> dict:
    ref_type = "directory_template" if item.get("source_kind") == "directory_template" else "template"
    ref = {
        "type": ref_type,
        "raw_text": str(item.get("raw_text") or ""),
    }
    if ref_type == "directory_template":
        ref["template_id"] = str(item.get("template_id") or "")
        ref["template_name"] = str(item.get("template_name") or "")
    for key in ("page", "style", "source_kind"):
        value = item.get(key)
        if value not in (None, ""):
            ref[key] = value
    return ref


def template_source(item: dict) -> str:
    return "directory_template" if item.get("source_kind") == "directory_template" else "template"


def wiki_ref(item: dict) -> dict:
    ref = {
        "type": "wiki",
        "path": str(item.get("path") or ""),
        "source_name": str(item.get("source_name") or item.get("display_name") or ""),
        "section": str(item.get("section") or ""),
        "condition": str(item.get("condition") or ""),
    }
    material = item.get("material_ref")
    if isinstance(material, dict):
        ref["material"] = material
    return ref


def tender_special_ref(tender: dict, keyword: str) -> list[dict]:
    refs = []
    for special in tender.get("specials", []):
        if special.get("keyword") != keyword:
            continue
        refs.append(
            {
                "type": "tender_special",
                "keyword": keyword,
                "hint_section": str(special.get("hint_section") or ""),
                "confidence": special.get("confidence", ""),
                "evidence": special.get("evidence") or [],
            }
        )
    return refs


def material_ref(item: dict) -> dict:
    material = item.get("material_ref")
    if isinstance(material, dict):
        return material
    return {
        "id": "",
        "docx": "",
        "usage": "",
        "attach": "",
        "skeleton": str(item.get("section") or ""),
        "fields": "",
    }


def make_item(
    *,
    level: int,
    number: str,
    title: str,
    annotation: str,
    source: str,
    reason: str = "",
    source_refs: list[dict] | None = None,
    material_refs: list[dict] | None = None,
) -> dict:
    item = {
        "level": level,
        "number": number,
        "title": title,
        "annotation": annotation,
        "source": source,
        "reason": reason,
    }
    if source_refs:
        item["source_refs"] = source_refs
    if material_refs:
        item["material_refs"] = material_refs
    return item


def template_tag(title: str, wiki_names: set[str]) -> str:
    if any(_title_match(wn, title) for wn in wiki_names):
        return TAG_ADAPT
    if any(k in title for k in ("业绩", "担保", "关键数据", "技术参数", "承诺", "性能指标", "交货进度", "项目", "招标", "投标人")):
        return TAG_ADAPT
    return TAG_KEEP


def is_attach_type(item: dict) -> bool:
    return item.get("scope") == "定制" and any(k in item["display_name"] for k in ("基础工程量", "基础弯矩"))


def is_check_report(item: dict) -> bool:
    return item.get("scope") == "定制" and any(k in item["display_name"] for k in ("校核", "复核"))


def merge_group(group: list):
    """同 section 分组：通用主 + 通用次 + 校核类作“附”。"""
    generals = [g for g in group if g.get("scope") == "通用"]
    checks = [g for g in group if is_check_report(g)]
    custom_mains = [g for g in group if g.get("scope") == "定制" and not is_check_report(g) and not is_attach_type(g)]
    mains = generals + custom_mains
    seen_names = set()
    dedup_mains = []
    for m in mains:
        if m["display_name"] in seen_names:
            continue
        seen_names.add(m["display_name"])
        dedup_mains.append(m)
    return dedup_mains, checks


def with_activation_marks(group: list, tender: dict) -> list:
    out = []
    for item in group:
        copied = dict(item)
        copied["_delete_reason"] = activation_reason(item, tender)
        out.append(copied)
    return out


def add_internal_heading_items(items: list, parent_item: dict, parent_number: str, parent_level: int):
    """把素材内部 Heading 树按层级展开为总目录子目录。"""
    headings = parent_item.get("internal_headings", [])
    if not headings or int(parent_item.get("heading_count") or 0) <= 0:
        return

    parent_title = parent_item.get("display_name", "")
    shift = int(parent_item.get("shift") or 0)
    counters = defaultdict(int)
    last_level = parent_level

    for heading in headings:
        title = heading.get("title", "").strip()
        if not title or _title_match(title, parent_title):
            continue

        try:
            raw_level = int(heading.get("level") or parent_level + 1)
        except (TypeError, ValueError):
            raw_level = parent_level + 1
        level = raw_level + shift
        level = min(max(level, parent_level + 1), 6)
        if level > last_level + 1:
            level = last_level + 1

        counters[level] += 1
        for deeper in range(level + 1, 7):
            counters.pop(deeper, None)
        suffix = ".".join(str(counters[l]) for l in range(parent_level + 1, level + 1) if counters.get(l))
        number = f"{parent_number}.{suffix}" if suffix else parent_number
        last_level = level

        items.append(
            make_item(
                level=level,
                number=number,
                title=title,
                annotation=TAG_INTERNAL,
                source="internal_heading",
                reason="素材自带标题，已展开为总目录子目录",
                source_refs=[wiki_ref(parent_item)],
                material_refs=[material_ref(parent_item)],
            )
        )


def build_plan(
    tpl: dict,
    tender: dict,
    attach: dict,
    wiki_items: list,
    title: str,
    *,
    directory_templates: list[dict] | None = None,
) -> dict:
    tpl = apply_directory_templates(tpl, directory_templates or [])
    template_title_sections = template_section_map(tpl)
    by_section = defaultdict(list)
    for it in wiki_items:
        copied = dict(it)
        matched_section = template_title_sections.get(title_key(copied.get("display_name", "")))
        if matched_section:
            copied["section"] = matched_section
        by_section[str(copied["section"])].append(copied)

    items = []

    prologue = with_activation_marks(by_section.get("前言", []), tender)
    for it in prologue:
        items.append(
            make_item(
                level=1,
                number="前言",
                title=it["display_name"],
                annotation=tag_for(it),
                source="wiki",
                reason=it.get("_delete_reason", ""),
                source_refs=[wiki_ref(it)],
                material_refs=[material_ref(it)],
            )
        )
        if tag_for(it) != TAG_DELETE:
            add_internal_heading_items(items, it, "前言", 1)

    chapter_cn = {"1": "第一章", "2": "第二章", "3": "第三章", "4": "第四章",
                  "5": "第五章", "6": "第六章", "7": "第七章", "8": "第八章", "9": "第九章"}

    for chap in tpl.get("chapters", []):
        cnum = chap["num"]
        ctitle = chap["title"]
        items.append(
            make_item(
                level=1,
                number=chapter_cn.get(cnum, cnum),
                title=ctitle,
                annotation=TAG_KEEP,
                source=template_source(chap),
                source_refs=[template_ref(chap)],
            )
        )

        wiki_under_chapter = {
            sec: with_activation_marks([it for it in by_section[sec] if not is_attach_type(it)], tender)
            for sec in by_section
            if sec == cnum or sec.startswith(cnum + ".")
        }
        wiki_under_chapter = {k: v for k, v in wiki_under_chapter.items() if v}
        active_wiki_under = {k: [it for it in v if not it.get("_delete_reason")] for k, v in wiki_under_chapter.items()}
        active_wiki_under = {k: v for k, v in active_wiki_under.items() if v}
        mark_wiki_suggestions_not_in_template(chap, active_wiki_under)

        template_has_h2 = bool(chap.get("h2s"))

        if template_has_h2:
            emit_from_template_h2(items, chap, active_wiki_under)
            emit_chapter_level_deletions(items, cnum, wiki_under_chapter)
        elif wiki_under_chapter:
            emit_with_wiki(items, cnum, wiki_under_chapter, ctitle)

        inject_specials(items, tender, active_wiki_under, cnum)

    if attach and attach.get("classes"):
        items.append(make_item(level=1, number="附表", title="", annotation=TAG_KEEP, source="attach"))
        for cls in attach["classes"]:
            items.append(make_item(level=2, number=f"附表 {cls['letter']}", title=cls.get("title", ""), annotation=TAG_KEEP, source="attach"))
            for sub in cls.get("subs", []):
                items.append(make_item(level=3, number=sub["num"], title=sub.get("title", ""), annotation=TAG_KEEP, source="attach"))

    return {"document_title": title, "items": items}


def apply_directory_templates(tpl: dict, directory_templates: list[dict]) -> dict:
    """Merge stored directory-template profiles into extracted template skeleton.

    The uploaded project template remains primary. Stored profiles only add
    missing chapters/H2s and mark those additions so S3 can review their source.
    """
    if not directory_templates:
        return tpl

    merged = copy.deepcopy(tpl or {})
    chapters = merged.setdefault("chapters", [])
    if not isinstance(chapters, list):
        merged["chapters"] = chapters = []

    profile_queue = sorted(
        [profile for profile in directory_templates if isinstance(profile, dict)],
        key=lambda profile: 1 if str(profile.get("id") or "") == "tech-general" else 0,
    )

    for profile in profile_queue:
        profile_id = str(profile.get("id") or "")
        profile_name = str(profile.get("name") or "")
        for profile_chapter in profile.get("chapters") or []:
            if not isinstance(profile_chapter, dict):
                continue
            target = _find_template_chapter(chapters, profile_chapter)
            if target is None:
                target = _directory_template_chapter(profile_chapter, profile_id, profile_name)
                chapters.append(target)
            elif not str(target.get("source_kind") or ""):
                _add_missing_directory_template_h2s(target, profile_chapter, profile_id, profile_name)
            else:
                _add_missing_directory_template_h2s(target, profile_chapter, profile_id, profile_name)

    chapters.sort(key=lambda item: _section_sort_key(str(item.get("num") or "")))
    for chapter in chapters:
        if isinstance(chapter.get("h2s"), list):
            chapter["h2s"].sort(key=lambda item: _section_sort_key(str(item.get("num") or "")))
    return merged


def _find_template_chapter(chapters: list[dict], profile_chapter: dict) -> dict | None:
    p_num = str(profile_chapter.get("num") or "").strip()
    p_title_key = title_key(str(profile_chapter.get("title") or ""))
    for chapter in chapters:
        c_num = str(chapter.get("num") or "").strip()
        c_title_key = title_key(str(chapter.get("title") or ""))
        if p_num and c_num == p_num:
            return chapter
        if p_title_key and c_title_key == p_title_key:
            return chapter
    return None


def _directory_template_chapter(chapter: dict, profile_id: str, profile_name: str) -> dict:
    num = str(chapter.get("num") or "").strip()
    title = str(chapter.get("title") or "").strip()
    result = {
        "num": num,
        "title": title,
        "raw_text": f"{num} {title}".strip(),
        "source_kind": "directory_template",
        "template_id": profile_id,
        "template_name": profile_name,
        "h2s": [],
    }
    _add_missing_directory_template_h2s(result, chapter, profile_id, profile_name)
    return result


def _add_missing_directory_template_h2s(
    target_chapter: dict,
    profile_chapter: dict,
    profile_id: str,
    profile_name: str,
) -> None:
    h2s = target_chapter.setdefault("h2s", [])
    existing_titles = {title_key(str(item.get("title") or "")) for item in h2s if isinstance(item, dict)}
    chapter_num = str(target_chapter.get("num") or profile_chapter.get("num") or "").strip()
    for index, profile_h2 in enumerate(profile_chapter.get("h2s") or [], start=1):
        if not isinstance(profile_h2, dict):
            continue
        title = str(profile_h2.get("title") or "").strip()
        key = title_key(title)
        if not title or key in existing_titles:
            continue
        num = str(profile_h2.get("num") or "").strip()
        if not num and chapter_num:
            num = f"{chapter_num}.{len(h2s) + index}"
        if num and _section_number_exists(h2s, num):
            num = _next_available_child_number(chapter_num, h2s)
        h2s.append(
            {
                "num": num,
                "title": title,
                "raw_text": f"{num} {title}".strip(),
                "source_kind": "directory_template",
                "template_id": profile_id,
                "template_name": profile_name,
            }
        )
        existing_titles.add(key)


def _section_number_exists(items: list[dict], number: str) -> bool:
    return any(str(item.get("num") or "").strip() == number for item in items if isinstance(item, dict))


def _next_available_child_number(chapter_num: str, h2s: list[dict]) -> str:
    if not chapter_num:
        return ""
    used = {str(item.get("num") or "").strip() for item in h2s if isinstance(item, dict)}
    index = 1
    while True:
        candidate = f"{chapter_num}.{index}"
        if candidate not in used:
            return candidate
        index += 1


def _section_sort_key(value: str) -> tuple:
    parts = []
    for part in str(value or "").split("."):
        if part.isdigit():
            parts.append((0, int(part)))
        else:
            parts.append((1, part))
    return tuple(parts or [(1, value)])


def title_key(value: str) -> str:
    import re as _re
    return _re.sub(r"[\s　,，、.。:：()（）\[\]【】\-—_]+", "", str(value or "")).lower()


def template_section_map(tpl: dict) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for chap in tpl.get("chapters", []):
        ctitle = str(chap.get("title") or "")
        cnum = str(chap.get("num") or "")
        if ctitle and cnum:
            mapping[title_key(ctitle)] = cnum
        for h2 in chap.get("h2s", []):
            htitle = str(h2.get("title") or "")
            hnum = str(h2.get("num") or "")
            if htitle and hnum:
                mapping[title_key(htitle)] = hnum
    return mapping


def add_order(items: list) -> list:
    """补充稳定顺序号。"""
    for idx, item in enumerate(items, start=1):
        item["order"] = idx
    return items


def build_output(
    tpl: dict,
    tender: dict,
    attach: dict,
    wiki_root: Path,
    title: str,
    items: list,
    project_identity: dict | None = None,
    directory_templates: list[dict] | None = None,
) -> dict:
    """组装最终 JSON 输出。"""
    ordered_items = add_order(items)
    counts = Counter(item.get("annotation", "") for item in ordered_items)
    annotation_counts = {tag: counts.get(tag, 0) for tag in ALL_TAGS}
    return {
        "schema_version": "bid-toc-json-v1",
        "document_title": title,
        "project": {
            "owner": tender.get("owner", ""),
            "name": tender.get("project", ""),
            "code": tender.get("code", ""),
            "identity": project_identity or {},
            "site_flags": tender.get("site_flags", {}),
            "model_flags": tender.get("model_flags", {}),
            "plot_flags": tender.get("plot_flags", {}),
            "specials": tender.get("specials", []),
        },
        "source_files": {
            "template": tpl.get("source", ""),
            "tender": tender.get("source", ""),
            "attach": attach.get("source", "") if attach else "",
            "wiki": str(wiki_root),
            "directory_templates": [str(item.get("id") or "") for item in (directory_templates or [])],
        },
        "summary": {
            "total_items": len(ordered_items),
            "annotation_counts": annotation_counts,
        },
        "items": ordered_items,
    }


def _title_match(a: str, b: str) -> bool:
    import re as _re
    na = _re.sub(r"[\s　,，、.。()（）\[\]-]", "", a)
    nb = _re.sub(r"[\s　,，、.。()（）\[\]-]", "", b)
    if not na or not nb:
        return False
    return na in nb or nb in na


def emit_with_wiki(items: list, chapter_num: str, wiki_under: dict, chapter_title: str = ""):
    """按 wiki 素材 section 在章节下排布，删除建议不物理删除。"""
    emitted_containers = set()

    def sort_sec(s):
        parts = s.split(".")
        return tuple(int(p) if p.isdigit() else 99 for p in parts)

    if chapter_num in wiki_under:
        mains, checks = merge_group(wiki_under[chapter_num])
        mains_filtered = [m for m in mains if not (chapter_title and _title_match(m["display_name"], chapter_title))]
        for i, m in enumerate(mains_filtered, start=1):
            number = f"{chapter_num}.{i}"
            level = 2
            items.append(
                make_item(
                    level=level,
                    number=number,
                    title=m["display_name"],
                    annotation=tag_for(m),
                    source="wiki",
                    reason=m.get("_delete_reason", ""),
                    source_refs=[wiki_ref(m)],
                    material_refs=[material_ref(m)],
                )
            )
            if tag_for(m) != TAG_DELETE:
                add_internal_heading_items(items, m, number, level)
        for c in checks:
            items.append(
                make_item(
                    level=3,
                    number="附",
                    title=c["display_name"],
                    annotation=tag_for(c),
                    source="wiki",
                    reason=c.get("_delete_reason", ""),
                    source_refs=[wiki_ref(c)],
                    material_refs=[material_ref(c)],
                )
            )

    sub_sections = sorted([s for s in wiki_under if s != chapter_num], key=sort_sec)
    for sec in sub_sections:
        group = wiki_under[sec]
        mains, checks = merge_group(group)
        if not mains and not checks:
            continue

        parent = ".".join(sec.split(".")[:-1])
        if parent and parent != chapter_num and parent not in emitted_containers:
            container_title = guess_container_title(parent)
            items.append(make_item(level=2, number=parent, title=container_title, annotation=TAG_KEEP, source="wiki"))
            emitted_containers.add(parent)

        level = sec.count(".") + 1
        if mains:
            main = mains[0]
            items.append(
                make_item(
                    level=level,
                    number=sec,
                    title=main["display_name"],
                    annotation=tag_for(main),
                    source="wiki",
                    reason=main.get("_delete_reason", ""),
                    source_refs=[wiki_ref(main)],
                    material_refs=[material_ref(main)],
                )
            )
            if tag_for(main) != TAG_DELETE:
                add_internal_heading_items(items, main, sec, level)
            for i, m in enumerate(mains[1:], start=1):
                number = f"{sec}.{i}"
                items.append(
                    make_item(
                        level=level + 1,
                        number=number,
                        title=m["display_name"],
                        annotation=tag_for(m),
                        source="wiki",
                        reason=m.get("_delete_reason", ""),
                        source_refs=[wiki_ref(m)],
                        material_refs=[material_ref(m)],
                    )
                )
                if tag_for(m) != TAG_DELETE:
                    add_internal_heading_items(items, m, number, level + 1)
        for c in checks:
            items.append(
                make_item(
                    level=level + 1,
                    number="附",
                    title=c["display_name"],
                    annotation=tag_for(c),
                    source="wiki",
                    reason=c.get("_delete_reason", ""),
                    source_refs=[wiki_ref(c)],
                    material_refs=[material_ref(c)],
                )
            )


def guess_container_title(parent_section: str) -> str:
    container_titles = {
        "5.8": "项目风机各子系统专题",
        "5.9": "项目风机环境适应性专题",
    }
    return container_titles.get(parent_section, "")


def emit_from_template_h2(items: list, chap: dict, wiki_under: dict = None):
    """模板 H2 是主骨架；Wiki 素材作为该 H2 下的小标题/素材线索补充。"""
    wiki_names = set()
    if wiki_under:
        for group in wiki_under.values():
            for g in group:
                wiki_names.add(g["display_name"])
    emitted_wiki_sections: set[str] = set()
    for h2 in chap.get("h2s", []):
        h2_num = str(h2["num"])
        direct_wiki = list((wiki_under or {}).get(h2_num, []))
        matched_materials = [g for g in direct_wiki if _title_match(g["display_name"], h2["title"])]
        reason = ""
        if matched_materials:
            names = "、".join(g["display_name"] for g in matched_materials[:3])
            reason = f"匹配素材库：{names}"
        items.append(
            make_item(
                level=2,
                number=h2_num,
                title=h2["title"],
                annotation=template_tag(h2["title"], wiki_names),
                source=template_source(h2),
                reason=reason,
                source_refs=[template_ref(h2)],
                material_refs=[material_ref(g) for g in matched_materials],
            )
        )

        child_index = 1
        for g in direct_wiki:
            if _title_match(g["display_name"], h2["title"]):
                continue
            number = f"{h2_num}.{child_index}"
            child_index += 1
            items.append(
                make_item(
                    level=3,
                    number=number,
                    title=g["display_name"],
                    annotation=tag_for(g),
                    source="wiki",
                    reason=g.get("_delete_reason", "") or f"素材库挂载到模板章节 {h2_num}",
                    source_refs=[wiki_ref(g)],
                    material_refs=[material_ref(g)],
                )
            )
            if tag_for(g) != TAG_DELETE:
                add_internal_heading_items(items, g, number, 3)
        if direct_wiki:
            emitted_wiki_sections.add(h2_num)

        nested_sections = sorted(
            [
                sec
                for sec in (wiki_under or {})
                if sec.startswith(h2_num + ".") and sec not in emitted_wiki_sections
            ],
            key=lambda value: tuple(int(part) if part.isdigit() else 99 for part in value.split(".")),
        )
        for sec in nested_sections:
            group = (wiki_under or {}).get(sec) or []
            mains, checks = merge_group(group)
            for i, g in enumerate(mains + checks, start=1):
                number = sec if i == 1 else f"{sec}.{i - 1}"
                level = min(max(sec.count(".") + 1, 3), 6)
                items.append(
                    make_item(
                        level=level,
                        number=number,
                        title=g["display_name"],
                        annotation=tag_for(g),
                        source="wiki",
                        reason=g.get("_delete_reason", "") or f"素材库补充到模板章节 {h2_num}",
                        source_refs=[wiki_ref(g)],
                        material_refs=[material_ref(g)],
                    )
                )
                if tag_for(g) != TAG_DELETE:
                    add_internal_heading_items(items, g, number, level)
            emitted_wiki_sections.add(sec)


def mark_wiki_suggestions_not_in_template(chap: dict, active_wiki_under: dict):
    """wiki/rules 触发、但模板 H2 没覆盖的素材标为素材库建议新增。"""
    template_titles = [h2["title"] for h2 in chap.get("h2s", [])]
    for sec, group in active_wiki_under.items():
        if sec == chap["num"]:
            continue
        for g in group:
            if not any(_title_match(g["display_name"], title) for title in template_titles):
                g["_tag_override"] = TAG_WIKI_ADD


def emit_chapter_level_deletions(items: list, chapter_num: str, wiki_under: dict):
    """模板 H2 展开时，章级 wiki 中被规则剔除的项仍作为删除建议展示。"""
    for sec, group in wiki_under.items():
        if sec != chapter_num:
            continue
        for g in group:
            if g.get("_delete_reason"):
                items.append(
                    make_item(
                        level=2,
                        number=f"{chapter_num}.删",
                        title=g["display_name"],
                        annotation=TAG_DELETE,
                        source="wiki",
                        reason=g.get("_delete_reason", ""),
                        source_refs=[wiki_ref(g)],
                        material_refs=[material_ref(g)],
                    )
                )


def emit_template_gaps_as_wiki_suggestions(items: list, chap: dict, active_wiki_under: dict):
    """兼容旧调用：素材库建议已在 emit_with_wiki 前通过 tag override 标注。"""
    return


def inject_specials(items: list, tender: dict, wiki_under: dict, chapter_num: str):
    """招标 specials：若对应 wiki 素材未激活，作为 [新增-招标要求] 子节插入。"""
    specials = tender.get("specials", [])
    if not specials:
        return

    existing_names = set()
    for group in wiki_under.values():
        for g in group:
            existing_names.add(g["display_name"])

    hint_to_parent = {
        "叶片": ("5.8.1", 4),
        "净空": ("5.8.13", 4),
        "塔筒": ("5.10", 3),
        "数字化": ("5.18", 3),
        "碳排放": ("5.17", 3),
        "自主可控": ("1", 2),
        "状态监测": ("5.18", 3),
    }
    for sp in specials:
        hint = sp.get("hint_section", "")
        kw = sp.get("keyword", "")
        if hint not in hint_to_parent:
            continue
        parent_sec, new_level = hint_to_parent[hint]
        if not (parent_sec == chapter_num or parent_sec.startswith(chapter_num + ".")):
            continue
        if any(kw in n or n in kw for n in existing_names):
            continue
        existing_children = [x for x in items if x["number"].startswith(parent_sec + ".") and x["number"].count(".") == parent_sec.count(".") + 1]
        new_num = f"{parent_sec}.{len(existing_children) + 1}"
        inserted = False
        for i in range(len(items) - 1, -1, -1):
            if items[i]["number"] == parent_sec or items[i]["number"].startswith(parent_sec + "."):
                items.insert(
                    i + 1,
                    make_item(
                        level=new_level,
                        number=new_num,
                        title=f"{kw}相关方案",
                        annotation=TAG_TENDER_ADD,
                        source="tender_special",
                        reason=f"招标 specials 命中：{kw}",
                        source_refs=tender_special_ref(tender, kw),
                    ),
                )
                inserted = True
                break
        if inserted:
            continue


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", required=True, help="extract_template.py 输出的 JSON")
    ap.add_argument("--tender", required=True, help="extract_tender.py 输出的 JSON")
    ap.add_argument("--attach", help="extract_attach.py 输出的 JSON（可选）")
    ap.add_argument("--wiki", required=True, help="wiki 根目录")
    ap.add_argument("--project-identity", help="项目身份 JSON，用于过滤客户/项目素材")
    ap.add_argument("--directory-templates", help="目录模板沉淀 JSON，用于补齐通用/客户专属结构")
    ap.add_argument("--title", help="文档标题（缺省组装）")
    ap.add_argument("--output", required=True, help="输出 JSON 路径")
    args = ap.parse_args()

    tpl = load_json(args.template)
    tender = load_json(args.tender)
    attach = load_json(args.attach) if args.attach else None
    wiki_root = Path(args.wiki)
    wiki_items = load_wiki(wiki_root)
    project_identity = load_json(args.project_identity) if args.project_identity else {}
    directory_templates = load_json(args.directory_templates) if args.directory_templates else []
    if not isinstance(directory_templates, list):
        directory_templates = []
    wiki_items = filter_wiki_by_project_identity(wiki_items, project_identity, tender)

    title = args.title
    if not title:
        o = tender.get("owner", "").strip()
        p = tender.get("project", "").strip()
        c = tender.get("code", "").strip()
        if o and p.startswith(o):
            base = p
        elif o and p:
            base = f"{o} - {p}"
        else:
            base = o or p or "新项目"
        if c:
            base = f"{base}（{c}）"
        title = f"{base}投标文件总目录"

    plan = build_plan(tpl, tender, attach, wiki_items, title, directory_templates=directory_templates)
    output = build_output(
        tpl,
        tender,
        attach,
        wiki_root,
        title,
        plan["items"],
        project_identity,
        directory_templates,
    )
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": args.output, "items": len(output["items"]), "schema_version": output["schema_version"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
