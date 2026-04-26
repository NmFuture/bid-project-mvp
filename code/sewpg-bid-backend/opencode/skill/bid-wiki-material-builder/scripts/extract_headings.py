#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_headings.py — Word Heading 层级抽取工具

用途：
  1. 给任意 .docx 导出结构化 heading 树（可独立使用）
  2. 维护 skeleton.md：全量重抽素材库所有 docx 并原地 regen heading 树块（幂等）
  3. 审计：对照 docx 实际 heading 与 skeleton.md 声明的层级/条数，报不一致

用法：
  python3 extract_headings.py <docx>                # 打印单个 docx 的 heading 树
  python3 extract_headings.py --scan                # 扫素材库，列全部 docx heading 统计
  python3 extract_headings.py --audit               # 对照 skeleton.md 中的 Lx-Ly/条数声明
  python3 extract_headings.py --regen-skeleton      # 原地 regen skeleton.md 所有 heading 树
  python3 extract_headings.py --regen-skeleton --dry-run   # 只报告，不写文件

新素材/更新素材后的常见流程：
  1) 放入素材库（确保 .docx）
  2) python3 extract_headings.py --audit             # 看差异
  3) 手工在 skeleton.md 加/改 merge 素材条目（path / shift / 备注 等）
  4) python3 extract_headings.py --regen-skeleton    # 全量对齐 heading 树
  5) python3 parse_skeleton.py                       # 回填卡片的 Merge 信息节
  6) python3 check.py                                # 一致性检查
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    from docx import Document
except ImportError:
    sys.stderr.write("需要 python-docx：pip install python-docx\n")
    sys.exit(2)

WIKI = Path(__file__).resolve().parent.parent  # wiki/scripts/ → wiki/
ROOT = WIKI.parent  # 素材库/
SKELETON = WIKI / "skeleton.md"

# ===== 核心：Heading 抽取 =====

def extract_headings(docx_path: Path) -> list[tuple[int, str]]:
    """抽取 [(level, text), ...]，按 docx 自然顺序。只收 Heading 1–9 样式。"""
    doc = Document(str(docx_path))
    out: list[tuple[int, str]] = []
    for p in doc.paragraphs:
        style = p.style.name if p.style else ""
        if not style.startswith("Heading"):
            continue
        suffix = style[len("Heading"):].strip()
        if not suffix.isdigit():
            continue
        text = p.text.strip()
        if not text:
            continue
        out.append((int(suffix), text))
    return out


def format_tree(headings: list[tuple[int, str]], base_indent: int = 4, step: int = 2) -> str:
    """
    按 skeleton.md 现有格式输出：
        L2  顶层
          L3  二层
            L4  三层
    顶层缩进 = base_indent 个空格；每深 1 层 +step 个空格。
    """
    if not headings:
        return ""
    min_lv = min(lv for lv, _ in headings)
    lines = []
    for lv, text in headings:
        indent = base_indent + (lv - min_lv) * step
        lines.append(" " * indent + f"L{lv}  {text}")
    return "\n".join(lines)


def expand_path(short: str) -> Path:
    """把 skeleton.md 里的 `通/...` / `定/...` 短路径还原为绝对/相对素材库根的完整路径。"""
    if short.startswith("通/"):
        return ROOT / "投标资料库-通用" / short[2:]
    if short.startswith("定/"):
        return ROOT / "投标资料库-定制" / short[2:]
    return ROOT / short


# ===== 扫描 & 审计 =====

def iter_library_docx() -> list[Path]:
    paths: list[Path] = []
    for sub in ("投标资料库-通用", "投标资料库-定制"):
        base = ROOT / sub
        if not base.exists():
            continue
        for p in base.rglob("*.docx"):
            name = p.name
            if name.startswith("~$") or name.startswith(".~") or "archive" in p.parts:
                continue
            paths.append(p)
    return sorted(paths)


def cmd_scan() -> int:
    print(f"{'Count':>5}  {'Range':<8}  Distribution                         File")
    print("-" * 100)
    for p in iter_library_docx():
        try:
            heads = extract_headings(p)
        except Exception as e:
            print(f"  FAIL  {p.name}: {e}")
            continue
        if not heads:
            print(f"  {'0':>4}  {'none':<8}  {'(无 Heading)':<38} {p.relative_to(ROOT)}")
            continue
        levels = sorted({lv for lv, _ in heads})
        rng = f"L{levels[0]}-L{levels[-1]}"
        dist = {lv: sum(1 for v, _ in heads if v == lv) for lv in levels}
        dist_s = " ".join(f"L{lv}:{dist[lv]}" for lv in levels)
        print(f"  {len(heads):>4}  {rng:<8}  {dist_s:<38} {p.relative_to(ROOT)}")
    return 0


# ===== skeleton.md 解析 + regen =====

MERGE_LINE_RE = re.compile(r"^(\s*-\s*\*\*merge 素材\*\*[:：]\s*`)([^`]+)(`\s*)$")
LEVEL_LINE_RE = re.compile(
    r"^(\s*-\s*素材层级[:：]\s*)L\d+[–\-\u2013]+L\d+"
    r"([,，]?\s*共\s*)\d+(\s*条\s*Heading)(.*)$"
)
EXPAND_MARKER = "贴入后自动展开成以下子节"
TREE_LINE_RE = re.compile(r"^\s+L\d+\s+\S")
SECTION_RE = re.compile(r"^#{2,4}\s")
BULLET_RE = re.compile(r"^\s*-\s")


def _regen_core(audit_only: bool = False) -> tuple[int, int, list[tuple[str, str]]]:
    """返回 (更新素材数, 跳过无Heading素材数, 缺失docx列表)。audit_only=True 时不写盘只收集差异。"""
    if not SKELETON.exists():
        print(f"未找到 {SKELETON}", file=sys.stderr)
        return (0, 0, [])
    lines = SKELETON.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    i, n = 0, len(lines)
    updated = 0
    skipped_none = 0
    missing: list[tuple[str, str]] = []
    audit_diffs: list[str] = []

    while i < n:
        line = lines[i]
        m = MERGE_LINE_RE.match(line)
        if not m:
            out.append(line)
            i += 1
            continue

        # 进入一份 merge 素材条目
        out.append(line)
        short = m.group(2).strip()
        docx_path = expand_path(short)

        if not docx_path.exists():
            missing.append((short, "docx 文件不存在"))
            i += 1
            continue

        try:
            heads = extract_headings(docx_path)
        except Exception as e:
            missing.append((short, f"读取失败: {e}"))
            i += 1
            continue

        j = i + 1
        replaced_tree = False
        while j < n:
            l2 = lines[j]
            if MERGE_LINE_RE.match(l2) or SECTION_RE.match(l2) or l2.strip() == "---":
                break

            # 更新 "素材层级：Lx–Ly，共 N 条 Heading ..." 行
            lm = LEVEL_LINE_RE.match(l2)
            if lm and heads:
                levels = sorted({lv for lv, _ in heads})
                new_count = len(heads)
                new_line = (
                    f"{lm.group(1)}L{levels[0]}–L{levels[-1]}"
                    f"{lm.group(2)}{new_count}{lm.group(3)}{lm.group(4)}"
                )
                if audit_only and new_line.rstrip() != l2.rstrip():
                    audit_diffs.append(
                        f"  [层级/条数] {short}\n"
                        f"    旧: {l2.rstrip()}\n"
                        f"    新: {new_line.rstrip()}"
                    )
                out.append(new_line)
                j += 1
                continue

            # 命中展开标记 → 替换 tree
            if EXPAND_MARKER in l2:
                out.append(l2)
                j += 1
                # 扫描旧 tree span：包括前置空行 + 缩进的 L? 行 + 可能的 `... (共 N 条...)` 截断标记
                k = j
                while k < n:
                    lt = lines[k]
                    if MERGE_LINE_RE.match(lt) or SECTION_RE.match(lt) or lt.strip() == "---":
                        break
                    # 非 tree 型 bullet（如下一段 - ** 字段）也视为 tree 结束
                    if BULLET_RE.match(lt):
                        break
                    k += 1

                if heads:
                    new_tree_block = ["", format_tree(heads), ""]
                    if audit_only:
                        old_span = "\n".join(lines[j:k]).rstrip()
                        new_span = "\n".join(new_tree_block).rstrip()
                        if old_span != new_span:
                            audit_diffs.append(
                                f"  [Heading 树] {short}\n"
                                f"    旧 {k - j} 行 → 新 {len(format_tree(heads).splitlines())} 行"
                            )
                    out.extend(new_tree_block)
                    updated += 1
                else:
                    # 无 Heading：保留原样（不该出现 expand marker，但防御保留）
                    out.extend(lines[j:k])
                    skipped_none += 1
                j = k
                replaced_tree = True
                continue

            # 无 Heading 素材的"整段附"说明行 → 原样输出
            out.append(l2)
            j += 1

        if not replaced_tree and heads:
            # 该条目有 heads 但 skeleton 里没写 expand marker（异常情况，报 audit）
            missing.append((short, "skeleton.md 里缺 '贴入后自动展开' 节，未替换"))

        i = j

    if not audit_only:
        content = "\n".join(out)
        if SKELETON.read_text(encoding="utf-8").endswith("\n"):
            content += "\n"
        SKELETON.write_text(content, encoding="utf-8")

    if audit_only and audit_diffs:
        for d in audit_diffs:
            print(d)

    return updated, skipped_none, missing


def cmd_regen(dry_run: bool) -> int:
    updated, skipped, missing = _regen_core(audit_only=dry_run)
    prefix = "[dry-run] " if dry_run else ""
    print(f"{prefix}regen 完成：更新 {updated} 份素材 heading 树；{skipped} 份无 Heading 素材保持原样。")
    if missing:
        print(f"\n问题 {len(missing)} 条：")
        for s, reason in missing:
            print(f"  ! {s}  — {reason}")
    return 0


def cmd_audit() -> int:
    print("审计 skeleton.md vs 实际 docx：\n")
    _regen_core(audit_only=True)
    return 0


def cmd_tree(path: str) -> int:
    p = Path(path)
    if not p.is_absolute():
        p = Path.cwd() / p
    if not p.exists():
        print(f"文件不存在: {p}", file=sys.stderr)
        return 1
    heads = extract_headings(p)
    if not heads:
        print("(无 Heading)")
        return 0
    print(format_tree(heads))
    print(f"\n— 共 {len(heads)} 条，层级 L{min(lv for lv,_ in heads)}–L{max(lv for lv,_ in heads)}")
    return 0


# ===== CLI =====

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Word Heading 抽取工具（辅助投标素材库 wiki）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    g = ap.add_mutually_exclusive_group()
    g.add_argument("docx", nargs="?", help="单个 .docx 路径，打印其 heading 树")
    g.add_argument("--scan", action="store_true", help="扫素材库列全部 docx heading 统计")
    g.add_argument("--audit", action="store_true", help="对照 skeleton.md 报不一致（只读）")
    g.add_argument("--regen-skeleton", action="store_true", help="原地 regen skeleton.md heading 树")
    ap.add_argument("--dry-run", action="store_true", help="配合 --regen-skeleton：不写文件")

    args = ap.parse_args()
    if args.scan:
        return cmd_scan()
    if args.audit:
        return cmd_audit()
    if args.regen_skeleton:
        return cmd_regen(dry_run=args.dry_run)
    if args.docx:
        return cmd_tree(args.docx)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
