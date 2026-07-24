#!/usr/bin/env python3
"""
初始化 project_params.json：从目录 docx 首行自动抽业主/项目名/招标编号，
**其余字段不询问用户，默认填占位符 `[待填写：<字段说明>]`**（一把出模式）。
需要保留 null 让外部交互补齐时加 --keep-null。

字段：
    project_name        项目全名（首行抽取）
    project_short       项目简称（用户填或从名字推）
    client_name         业主（正则"XX公司"）
    tender_no           招标编号（正则）
    turbine_model       风机机型号
    turbine_platform    风机平台
    rated_power_kw      额定功率（kW）
    rated_speed         额定转速（rpm）
    rotor_diameter_m    风轮直径（m）
    turbine_layout      风机布局
    hub_height          轮毂高度（m）
    wind_class          风区等级（IEC IIA 等）
    site_location       场址位置
    site_altitude       场址海拔（m）
    delivery_date       交货期
    warranty_years      质保年限
    cooling_type        冷却方式
    bid_date            投标日期
    land_area           地块（北区/南区/全场）

用法：
    # 从目录 docx 预填并写 project_params.json
    python3 init_params.py --toc /tmp/toc.json --out project_params.json

    # 打印缺失字段（agent 据此调 AskUserQuestion）
    python3 init_params.py --missing --params project_params.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional


SCHEMA = {
    "project_name": {"desc": "项目全名（招标文件封面）", "auto": True},
    "project_short": {"desc": "项目简称（用于文件名后缀，如 华能蒙东）", "auto": False},
    "client_name": {"desc": "业主单位（如 华能蒙东新能源公司）", "auto": True},
    "tender_no": {"desc": "招标编号（如 HNZB2025-12-1-382-01）", "auto": True},
    # 风机参数：与 backend _build_project_params 字段名保持一致
    "turbine_model": {"desc": "风机机型号（如 EW8.5-220）", "auto": False},
    "model_no": {"desc": "风机机型号（如 EW8.5-220）", "auto": False},
    "turbine_platform": {"desc": "风机平台（如 陆上 / 海上）", "auto": False},
    "rated_power_kw": {"desc": "额定功率（单位 kW，如 8500）", "auto": False},
    "rated_power": {"desc": "额定功率（单位 MW，如 8.5）", "auto": False},
    "rated_speed": {"desc": "额定转速（单位 rpm，如 9.8）", "auto": False},
    "rotor_diameter_m": {"desc": "风轮直径（单位 m，如 220）", "auto": False},
    "rotor_diameter": {"desc": "风轮直径（单位 m，如 220）", "auto": False},
    "turbine_layout": {"desc": "机组布置方式", "auto": False},
    "hub_height": {"desc": "轮毂高度（单位 m，如 145）", "auto": False},
    "wind_class": {"desc": "IEC 风区等级（如 IEC IIIA）", "auto": False},
    "site_location": {"desc": "场址位置（如 内蒙古赤峰市翁牛特旗）", "auto": False},
    "site_altitude": {"desc": "场址海拔（单位 m）", "auto": False},
    "delivery_date": {"desc": "计划交货期（如 2026 年 12 月）", "auto": False},
    "warranty_years": {"desc": "质保年限（单位 年）", "auto": False},
    "cooling_type": {"desc": "发电机冷却方式（水冷 / 风冷）", "auto": False},
    "bid_date": {"desc": "投标日期（如 2026 年 4 月 20 日）", "auto": False},
    "land_area": {"desc": "地块（北区 / 南区 / 全场）", "auto": False},
    "purchase_object": {"desc": "采购对象（如 风力发电机组（不含塔架）及附属设备采购）", "auto": False},
    "bid_date_cn": {"desc": "投标年月中文大写（如 二〇二六年四月；由 bid_date 自动推）", "auto": True},
}


_CN_DIGITS = "〇一二三四五六七八九"


def _num_to_cn(n: int) -> str:
    """整数转中文大写（简单版：支持年份 4 位 + 月份 1-12）。"""
    if n < 0:
        return str(n)
    if n == 0:
        return "〇"
    # 年份（4 位）：逐位数字
    s = str(n)
    if len(s) == 4:
        return "".join(_CN_DIGITS[int(c)] for c in s)
    # 月份（1-12）
    if 1 <= n <= 10:
        return _CN_DIGITS[n] if n < 10 else "十"
    if 11 <= n <= 19:
        return "十" + _CN_DIGITS[n - 10]
    if n == 20:
        return "二十"
    return str(n)


def _derive_bid_date_cn(bid_date: str) -> Optional[str]:
    """从 bid_date 抽年月并转中文大写。

    输入形式：'2026 年 4 月 20 日' / '2026-04-20' / '2026/4/20' / '2026年4月'
    输出：'二〇二六年四月'
    """
    if not bid_date:
        return None
    import re as _re
    m = _re.search(r"(\d{4})\D+(\d{1,2})", bid_date)
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    return f"{_num_to_cn(year)}年{_num_to_cn(month)}月"


# ---------- 自动抽取 ----------

_CLIENT_PATTERN = re.compile(r"([\u4e00-\u9fff]{2,20}(?:能源公司|电力公司|电站公司|发电公司|新能源公司|集团|公司))")
_TENDER_PATTERN = re.compile(r"([A-Z]{2,6}\d{4}[-\d]{4,20}(?:[-A-Za-z\d]+)?)")


def auto_extract_from_title(title: str) -> dict:
    """从目录 docx 首行 Heading 1 标题抽取。首行格式（样例）：
    '华能蒙东新能源公司赤峰市200万千瓦自建调峰能力...基地项目（HNZB2025-12-1-382-01）投标文件总目录'
    """
    out: dict = {k: None for k in SCHEMA}

    # 去掉尾部"投标文件总目录"
    cleaned = re.sub(r"投标文件[^\s]*目录\s*$", "", title).strip()

    # 招标编号（括号内）
    m = _TENDER_PATTERN.search(cleaned)
    if m:
        out["tender_no"] = m.group(1)
        # 去掉编号括号部分
        cleaned = re.sub(r"（[^）]*" + re.escape(m.group(1)) + r"[^）]*）", "", cleaned)
        cleaned = re.sub(r"\([^)]*" + re.escape(m.group(1)) + r"[^)]*\)", "", cleaned)
        cleaned = cleaned.strip()

    # 业主
    m = _CLIENT_PATTERN.search(cleaned)
    if m:
        out["client_name"] = m.group(1)

    # 项目名（整个 cleaned 作为 project_name）
    out["project_name"] = cleaned or title

    return out


def load_toc_first_title(toc_path: Path) -> str:
    """从当前 S2 目录 JSON 或 parse_toc 输出中提取项目/标题线索。"""
    if not toc_path.exists():
        return ""
    try:
        data = json.loads(toc_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if isinstance(data, dict):
        title = str(data.get("document_title") or data.get("documentTitle") or "").strip()
        if title:
            return title
        project = data.get("project")
        if isinstance(project, dict):
            parts = [
                str(project.get("owner") or "").strip(),
                str(project.get("name") or "").strip(),
                str(project.get("code") or "").strip(),
            ]
            text = "".join(part for part in parts if part)
            if text:
                return f"{text}投标文件总目录"
        nodes = data.get("items") or data.get("nodes") or []
    elif isinstance(data, list):
        nodes = data
    else:
        nodes = []
    if isinstance(nodes, list) and nodes:
        first = nodes[0]
        if isinstance(first, dict):
            number = str(first.get("number") or first.get("chapter_no") or "").strip()
            title = str(first.get("title") or "").strip()
            return f"{number} {title}".strip()
    return ""


# ---------- 主 ----------

def cmd_init(args):
    out: dict

    # 初始化：若已有 json，读入；否则全 null
    if args.out.exists() and not args.overwrite:
        out = json.loads(args.out.read_text(encoding="utf-8"))
    else:
        out = {k: None for k in SCHEMA}

    # 自动抽取
    if args.docx:
        from docx import Document
        doc = Document(str(args.docx))
        # 首行 Heading 1（文档标题）
        first_title = ""
        for para in doc.paragraphs:
            st = para.style.name if para.style else ""
            if (st == "Heading 1" or st == "标题 1") and (para.text or "").strip():
                first_title = para.text.strip()
                break
        if first_title:
            auto = auto_extract_from_title(first_title)
            for k, v in auto.items():
                if v and not out.get(k):
                    out[k] = v
    elif args.toc:
        first_title = load_toc_first_title(args.toc)
        if first_title:
            auto = auto_extract_from_title(first_title)
            for k, v in auto.items():
                if v and not out.get(k):
                    out[k] = v

    # 如果 project_short 为空，从 client_name 推（取业主关键词）
    if out.get("client_name") and not out.get("project_short"):
        m = re.match(r"(华能[\u4e00-\u9fff]{2,4})", out["client_name"])
        if m:
            out["project_short"] = m.group(1)

    # 从 bid_date 自动推 bid_date_cn
    if out.get("bid_date") and not out.get("bid_date_cn"):
        cn = _derive_bid_date_cn(out["bid_date"])
        if cn:
            out["bid_date_cn"] = cn

    # 缺失字段处理：默认填占位符 [待填写：<desc>]；--keep-null 保留 null
    missing_before = [k for k in SCHEMA if out.get(k) is None or out.get(k) == ""]
    if not args.keep_null:
        for k in missing_before:
            schema_entry = SCHEMA.get(k)
            if schema_entry is None:
                # 保留未知字段原值，避免外部新增字段导致崩溃
                continue
            out[k] = f"[待填写：{schema_entry['desc']}]"

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    filled = len(SCHEMA) - len(missing_before)
    print(f"[OK] {args.out} ({filled}/{len(SCHEMA)} 自动填充，{len(missing_before)} 占位符)", file=sys.stderr)
    if missing_before:
        mode = "保留 null" if args.keep_null else "已写 [待填写：xx]"
        print(f"[MISSING/{mode}] {', '.join(missing_before)}", file=sys.stderr)


def cmd_missing(args):
    if not args.params.exists():
        print(f"[ERR] params not found: {args.params}", file=sys.stderr)
        sys.exit(1)
    params = json.loads(args.params.read_text(encoding="utf-8"))
    missing = []
    for k in SCHEMA:
        v = params.get(k)
        if v is None or v == "":
            missing.append({"key": k, "desc": SCHEMA[k]["desc"]})
    print(json.dumps(missing, ensure_ascii=False, indent=2))


def cmd_schema(args):
    print(json.dumps(
        {k: {"desc": v["desc"], "auto": v["auto"]} for k, v in SCHEMA.items()},
        ensure_ascii=False, indent=2,
    ))


def main():
    # 探测是否带子命令：第一个非选项 token ∈ {init, missing, schema} 才走子命令分发
    SUB_CMDS = {"init", "missing", "schema"}
    has_sub = len(sys.argv) > 1 and sys.argv[1] in SUB_CMDS

    if has_sub:
        ap = argparse.ArgumentParser()
        sub = ap.add_subparsers(dest="cmd", required=True)

        p_init = sub.add_parser("init", help="从目录 docx 预填 project_params.json")
        p_init.add_argument("--docx", type=Path, help="目录 docx 路径（抽首行）")
        p_init.add_argument("--toc", type=Path, help="toc.json（可选，未使用）")
        p_init.add_argument("--out", type=Path, required=True)
        p_init.add_argument("--overwrite", action="store_true", help="覆盖已有 json")
        p_init.add_argument("--keep-null", action="store_true", help="缺失字段保留 null 而非写占位符（兼容旧交互流程）")
        p_init.set_defaults(func=cmd_init)

        p_missing = sub.add_parser("missing", help="列出缺失字段（兼容旧交互流程）")
        p_missing.add_argument("--params", type=Path, required=True)
        p_missing.set_defaults(func=cmd_missing)

        p_schema = sub.add_parser("schema", help="打印字段 schema")
        p_schema.set_defaults(func=cmd_schema)

        args = ap.parse_args()
        args.func(args)
        return

    # 默认：无子命令，等价于 init
    ap = argparse.ArgumentParser(description="初始化 project_params.json（默认非交互，缺失字段写占位符）")
    ap.add_argument("--docx", type=Path)
    ap.add_argument("--toc", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--keep-null", action="store_true", help="缺失字段保留 null 而非写占位符")
    args = ap.parse_args()
    cmd_init(args)


if __name__ == "__main__":
    main()
