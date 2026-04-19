#!/usr/bin/env python3
"""build_plan.py — 组合 template/tender/attach/wiki 输入，生成 gen_toc.py 的 plan.json

输入：
- --template  extract_template.py 输出的 JSON（模板 H1/H2 骨架）
- --tender    extract_tender.py 输出的 JSON（项目参数）
- --attach    extract_attach.py 输出的 JSON（附表 outline，可选）
- --wiki      wiki 根目录（用 wiki_lookup.py 取素材清单）
- --title     文档标题（可选，缺省从 tender 组装）
- --output    输出 plan.json 路径

输出：plan.json（title + items），items[i] = {level, number, text, tag}

核心逻辑：
1. 从 template 取章节框架（章号、章标题、章内 H2）
2. 从 wiki 取 71 条素材清单（按 skeleton_section 排好）
3. 按 tender 参数应用 rules.md 激活/剔除（基于场址/机型/地块 flags + specials）
4. 对每个模板章节：
   - 有 wiki 素材 section 匹配 → 按 wiki 排布内容
   - 无 wiki 素材 → 直接用模板 H2（如第 4 章承诺函）
5. wiki 特殊 section（"前言" / "附表"）独立处理
6. 模板 H2 但无对应 wiki 素材 → [新增]
7. 招标 specials 且无对应 wiki 素材 → 按 hint_section 匹配最近父节 [新增]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR = Path(__file__).parent


def load_json(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def load_wiki(wiki_root: Path):
    """调 wiki_lookup.py --list-by-section"""
    r = subprocess.run(
        ["python3", str(SCRIPT_DIR / "wiki_lookup.py"), "--wiki", str(wiki_root), "--list-by-section"],
        capture_output=True, text=True, check=True,
    )
    return json.loads(r.stdout)


def is_activated(item: dict, tender: dict) -> bool:
    """根据 tender 参数决定 wiki 素材是否激活。
    默认激活；按 rules.md 规则做剔除/条件触发。
    """
    name = item["display_name"]
    cat = item.get("category", "")
    scope = item.get("scope", "")
    section = str(item.get("section", ""))
    owner = tender.get("owner", "")
    site = tender.get("site_flags", {})
    model = tender.get("model_flags", {})
    plot = tender.get("plot_flags", {})

    # 业主专属素材泛化识别：素材名含"与 X 集团/公司/新能源"的，
    # 仅在当前业主 name 包含 X 时激活；否则剔除
    import re as _re
    m = _re.search(r"与([\u4e00-\u9fa5]{1,8}?)(?:集团|公司|新能源)", name)
    if m:
        expected = m.group(1)
        if expected and expected not in owner:
            return False

    # 机型剔除
    if "齿轮箱" in name and model.get("强制直驱"):
        return False
    if "液压" in name and not model.get("强制含液压"):
        # wiki 标"（如有）"本身说明按需，招标强制才激活
        pass  # 非强制时也保留，作为"如有"候选
    if name == "升降机" and not model.get("强制含升降机"):
        pass  # 同上

    # 环境适应性按场址 flag
    env_map = {
        "抗低温设计": "低温",
        "抗高温设计": "高温",
        "抗覆冰防凝露设计": "覆冰",
        "抗潮湿防腐蚀设计": "潮湿",
        "防风沙设计": "风沙",
        "防雷保护设计": "雷暴",
        "电气绝缘方案": "高海拔",
        "防紫外线、抗老化、电离辐射设计": "紫外",
    }
    if name in env_map:
        key = env_map[name]
        if not site.get(key, False):
            return False

    # 混塔/数字化/碳排放/净空监测等按 specials 激活
    if "混塔" in name and not any(s["keyword"] == "混塔" for s in tender.get("specials", [])):
        return False

    # 地块激活
    if "北区" in name and not plot.get("北区"):
        return False
    if "南区" in name and not plot.get("南区"):
        return False
    # 两区都未命中时：两份都作为占位（让人工决策），返回 True

    return True


def tag_for(item: dict) -> str:
    name = item["display_name"]
    if item.get("scope") == "定制":
        return "适配"
    if any(k in name for k in ("业绩", "担保", "关键数据", "技术参数", "承诺", "性能指标", "交货进度")):
        return "适配"
    return ""


def is_attach_type(item: dict) -> bool:
    return item.get("scope") == "定制" and any(k in item["display_name"] for k in ("基础工程量", "基础弯矩"))


def is_check_report(item: dict) -> bool:
    return item.get("scope") == "定制" and any(k in item["display_name"] for k in ("校核", "复核"))


def merge_group(group: list):
    """同 section 分组：通用主 + 通用次 + 校核类作"附"。"""
    generals = [g for g in group if g.get("scope") == "通用"]
    checks = [g for g in group if is_check_report(g)]
    custom_mains = [g for g in group if g.get("scope") == "定制" and not is_check_report(g) and not is_attach_type(g)]
    mains = generals + custom_mains
    # 同名通用+定制合并：定制直接丢（正文 docx 内部处理叠加/覆盖）
    seen_names = set()
    dedup_mains = []
    for m in mains:
        if m["display_name"] in seen_names:
            continue
        seen_names.add(m["display_name"])
        dedup_mains.append(m)
    return dedup_mains, checks


def build_plan(tpl: dict, tender: dict, attach: dict, wiki_items: list, title: str) -> dict:
    # 按 section 分组
    by_section = defaultdict(list)
    for it in wiki_items:
        by_section[str(it["section"])].append(it)

    items = []

    # 0) 前言段
    prologue = [it for it in by_section.get("前言", []) if is_activated(it, tender)]
    for it in prologue:
        items.append({"level": 1, "number": "前言", "text": it["display_name"], "tag": ""})

    # 1) 按模板章节遍历
    chapter_cn = {"1": "第一章", "2": "第二章", "3": "第三章", "4": "第四章",
                  "5": "第五章", "6": "第六章", "7": "第七章", "8": "第八章", "9": "第九章"}

    for chap in tpl.get("chapters", []):
        cnum = chap["num"]
        ctitle = chap["title"]
        items.append({"level": 1, "number": chapter_cn.get(cnum, cnum), "text": ctitle, "tag": ""})

        wiki_under_chapter = {
            sec: [it for it in by_section[sec] if is_activated(it, tender) and not is_attach_type(it)]
            for sec in by_section
            if sec == cnum or sec.startswith(cnum + ".")
        }
        wiki_under_chapter = {k: v for k, v in wiki_under_chapter.items() if v}

        # 策略：
        # - 若 wiki 有子 section（cnum.x）→ 按 wiki 排（子系统专题这种）
        # - 若 wiki 只有章级 section（cnum 本身是 L1 素材，无子节）且模板有 H2
        #   → 模板 H2 优先（承诺函这种 wiki 没覆盖细节）
        # - 两者都无 → 模板 H2 兜底
        has_sub_wiki = any(s != cnum for s in wiki_under_chapter)
        template_has_h2 = bool(chap.get("h2s"))

        if has_sub_wiki:
            emit_with_wiki(items, cnum, wiki_under_chapter, ctitle)
        elif template_has_h2:
            emit_from_template_h2(items, chap, wiki_under_chapter)
        elif wiki_under_chapter:
            emit_with_wiki(items, cnum, wiki_under_chapter, ctitle)

        # 在章末插入招标特殊要求
        inject_specials(items, tender, wiki_under_chapter, cnum)

    # 附表区
    if attach and attach.get("classes"):
        items.append({"level": 1, "number": "附表", "text": "", "tag": ""})
        for cls in attach["classes"]:
            items.append({"level": 2, "number": f"附表 {cls['letter']}", "text": cls.get("title", ""), "tag": ""})
            for sub in cls.get("subs", []):
                items.append({"level": 3, "number": sub["num"], "text": sub.get("title", ""), "tag": ""})

    return {"title": title, "items": items}


def _title_match(a: str, b: str) -> bool:
    """两个标题语义相近（去除标点空格后有一方是另一方的子串或完全相等）。"""
    import re as _re
    na = _re.sub(r"[\s　,，、.。()（）]", "", a)
    nb = _re.sub(r"[\s　,，、.。()（）]", "", b)
    if not na or not nb:
        return False
    return na in nb or nb in na


def emit_with_wiki(items: list, chapter_num: str, wiki_under: dict, chapter_title: str = ""):
    """按 wiki 素材 section 在章节下排布。"""
    emitted_containers = set()

    def sort_sec(s):
        parts = s.split(".")
        return tuple(int(p) if p.isdigit() else 99 for p in parts)

    # 章直属 section（sec == chapter_num）作为章内子节
    if chapter_num in wiki_under:
        mains, checks = merge_group(wiki_under[chapter_num])
        # 与章标题同名的 main 不重复展开（已作章标题）
        mains_filtered = [m for m in mains if not (chapter_title and _title_match(m["display_name"], chapter_title))]
        for i, m in enumerate(mains_filtered, start=1):
            items.append({
                "level": 2, "number": f"{chapter_num}.{i}",
                "text": m["display_name"], "tag": tag_for(m),
            })
        for c in checks:
            items.append({"level": 3, "number": "附", "text": c["display_name"], "tag": "适配"})

    # 子 section（如 5.1 / 5.8.1）
    sub_sections = sorted([s for s in wiki_under if s != chapter_num], key=sort_sec)
    for sec in sub_sections:
        group = wiki_under[sec]
        mains, checks = merge_group(group)
        if not mains and not checks:
            continue

        # H2 容器（如 5.8 / 5.9）：若 sec 是 5.8.x 且 5.8 容器未发出
        parent = ".".join(sec.split(".")[:-1])
        if parent and parent != chapter_num and parent not in emitted_containers:
            # 找容器标题：看看 by_section 里 parent 是否有素材作标题
            container_title = guess_container_title(parent)
            items.append({"level": 2, "number": parent, "text": container_title, "tag": ""})
            emitted_containers.add(parent)

        level = sec.count(".") + 1
        if mains:
            main = mains[0]
            items.append({
                "level": level, "number": sec,
                "text": main["display_name"], "tag": tag_for(main),
            })
            for i, m in enumerate(mains[1:], start=1):
                items.append({
                    "level": level + 1, "number": f"{sec}.{i}",
                    "text": m["display_name"], "tag": tag_for(m),
                })
        for c in checks:
            items.append({"level": level + 1, "number": "附",
                          "text": c["display_name"], "tag": "适配"})


def guess_container_title(parent_section: str) -> str:
    """对 5.8 / 5.9 等 H2 容器，返回 wiki 习惯标题。
    极少数情况，硬编码几个已知容器，不命中则返回空。
    这是"通用词典"不是写死项目参数。"""
    container_titles = {
        "5.8": "项目风机各子系统专题",
        "5.9": "项目风机环境适应性专题",
    }
    return container_titles.get(parent_section, "")


def emit_from_template_h2(items: list, chap: dict, wiki_under: dict = None):
    """模板该章无 wiki 子节覆盖 → 按模板 H2 展开。
    wiki 章级素材存在但无对应 wiki 子节时，标 [新增] 表示 wiki 无 docx；
    若恰好 wiki 有对应该 H2 的素材则标 [适配]。"""
    wiki_names = set()
    if wiki_under:
        for sec, group in wiki_under.items():
            for g in group:
                wiki_names.add(g["display_name"])
    for h2 in chap.get("h2s", []):
        tag = "新增"
        for wn in wiki_names:
            if _title_match(wn, h2["title"]):
                tag = "适配"
                break
        items.append({
            "level": 2, "number": h2["num"],
            "text": h2["title"], "tag": tag,
        })


def inject_specials(items: list, tender: dict, wiki_under: dict, chapter_num: str):
    """招标 specials：若对应 wiki 素材未激活，作为 [新增] 子节插入。"""
    specials = tender.get("specials", [])
    if not specials:
        return
    # 本章已有的 wiki 名字集合
    existing_names = set()
    for sec, group in wiki_under.items():
        for g in group:
            existing_names.add(g["display_name"])

    # special 挂到 hint_section 匹配的最近父节
    hint_to_parent = {
        "叶片": ("5.8.1", 4),           # 挂到 5.8.1.1
        "净空": ("5.8.13", 4),          # 挂到 5.8.13.1
        "塔筒": ("5.10", 3),            # 挂到 5.10.1
        "数字化": ("5.18", 3),          # 挂到 5.18.1
        "碳排放": ("5.17", 3),          # 挂到 5.17.1
        "自主可控": ("1", 2),           # 挂到 1 章新条
        "状态监测": ("5.18", 3),        # 挂到 5.18.1
    }
    for sp in specials:
        hint = sp.get("hint_section", "")
        kw = sp.get("keyword", "")
        if hint not in hint_to_parent:
            continue
        parent_sec, new_level = hint_to_parent[hint]
        # 只处理本章下的
        if not (parent_sec == chapter_num or parent_sec.startswith(chapter_num + ".")):
            continue
        # 若 wiki 已有同名或相近名素材 → 跳过
        if any(kw in n or n in kw for n in existing_names):
            continue
        # 找 parent 下已有子节数，新增 .X+1
        existing_children = [x for x in items if x["number"].startswith(parent_sec + ".") and x["number"].count(".") == parent_sec.count(".") + 1]
        new_num = f"{parent_sec}.{len(existing_children) + 1}"
        # 插入到 parent 节之后最近位置
        for i in range(len(items) - 1, -1, -1):
            if items[i]["number"] == parent_sec or items[i]["number"].startswith(parent_sec + "."):
                items.insert(i + 1, {
                    "level": new_level, "number": new_num,
                    "text": f"{kw}相关方案", "tag": "新增",
                })
                return


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", required=True, help="extract_template.py 输出的 JSON")
    ap.add_argument("--tender", required=True, help="extract_tender.py 输出的 JSON")
    ap.add_argument("--attach", help="extract_attach.py 输出的 JSON（可选）")
    ap.add_argument("--wiki", required=True, help="wiki 根目录")
    ap.add_argument("--title", help="文档标题（缺省组装）")
    ap.add_argument("--output", required=True, help="输出 plan.json 路径")
    args = ap.parse_args()

    tpl = load_json(args.template)
    tender = load_json(args.tender)
    attach = load_json(args.attach) if args.attach else None
    wiki_items = load_wiki(Path(args.wiki))

    title = args.title
    if not title:
        o = tender.get("owner", "").strip()
        p = tender.get("project", "").strip()
        c = tender.get("code", "").strip()
        # 若 project 已含 owner 前缀，去掉 owner 避免重复
        if o and p.startswith(o):
            base = p
        elif o and p:
            base = f"{o} - {p}"
        else:
            base = o or p or "新项目"
        if c:
            base = f"{base}（{c}）"
        title = f"{base}投标文件总目录"

    plan = build_plan(tpl, tender, attach, wiki_items, title)
    Path(args.output).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": args.output, "items": len(plan["items"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
