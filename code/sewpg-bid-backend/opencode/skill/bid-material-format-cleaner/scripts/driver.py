#!/usr/bin/env python3
"""
driver.py — bid-material-format-cleaner 的总控入口。

职责：
- 只依赖 venv 解释器运行，不依赖 activate
- 扫描素材目录并按类型路由到 PDF / Excel / Word 分支
- 统一维护输出目录镜像结构
- Word 分支采用“单临时副本事务 + 预检快路径”
- 输出统一报告，并可发送飞书通知
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path


if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/a343d185-ccd0-4ff4-8c63-50242908fe4a"
RUNTIME_DEPENDENCIES = {
    "fitz": "pymupdf",
    "docx": "python-docx",
    "pandas": "pandas",
    "openpyxl": "openpyxl",
    "lxml": "lxml",
}
SUPPORTED_SUFFIXES = {".pdf", ".xlsx", ".xls", ".xlsm", ".docx", ".doc"}
HEADING_STYLE_RE = re.compile(r"^(?:heading(?:\s*[1-9]\d*)?|标题(?:\s*[一二三四五六七八九十\d]+)?|[1-9]\d*)$", re.I)
BODY_HEADING_RE = re.compile(
    r"^(?:第[一二三四五六七八九十百零\d]+[章节部分编]|[一二三四五六七八九十百零]+、|\d+(?:\.\d+){0,4}[、.．)]?)"
)
SENTENCE_END_RE = re.compile(r"[。！？!?；;]$")
TOC_LINE_RE = re.compile(r"[\.．·•…]{2,}\s*\d+\s*$")
PAGE_NUMBER_TOC_RE = re.compile(r"^.{1,60}\s+\d+\s*$")
FRONT_MATTER_TITLES = {
    "目录",
    "前言",
    "说明",
    "声明",
    "编制说明",
    "修订记录",
    "修订历史",
    "版本记录",
    "审批",
    "审核",
    "批准",
    "投标文件",
    "技术标",
    "商务标",
}
FRONT_MATTER_KEYWORDS = (
    "编制日期",
    "修订记录",
    "修订历史",
    "版本记录",
    "审批意见",
    "审核意见",
    "批准意见",
    "声明",
    "前言",
    "目 录",
    "目录",
    "密级",
)
COVER_LINE_KEYWORDS = (
    "公司",
    "集团",
    "项目",
    "工程",
    "报告",
    "方案",
    "投标",
    "文件",
    "技术",
    "日期",
    "编制",
    "年",
    "月",
    "日",
)


@dataclass
class FileRecord:
    kind: str
    source: Path
    output: Path | None
    status: str
    detail: str


@dataclass
class WordPlan:
    action: str
    reason: str
    anchor_index: int | None = None
    anchor_para_id: str | None = None
    anchor_text: str | None = None
    probe_tool: str = "python"


def _ensure_venv() -> None:
    if os.getenv("FORMAT_CLEANER_ALLOW_SYSTEM_PY") == "1":
        return
    if sys.prefix == getattr(sys, "base_prefix", sys.prefix):
        raise RuntimeError("请使用 venv 解释器运行 driver.py，而不是系统 Python。")


def _ensure_runtime_dependencies() -> None:
    missing = [pkg for mod, pkg in RUNTIME_DEPENDENCIES.items() if importlib.util.find_spec(mod) is None]
    if not missing:
        return

    print(f"检测到缺少依赖，使用当前 venv 安装: {', '.join(missing)}")
    cmd = [sys.executable, "-m", "pip", "install", *missing]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_subprocess_env(),
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "pip install 失败")


def _subprocess_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("MSYS2_ARG_CONV_EXCL", "*")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    if extra:
        env.update(extra)
    return env


@contextlib.contextmanager
def _trusted_word_env():
    previous = os.environ.get("FORMAT_CLEANER_TRUST_PATH")
    os.environ["FORMAT_CLEANER_TRUST_PATH"] = "1"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("FORMAT_CLEANER_TRUST_PATH", None)
        else:
            os.environ["FORMAT_CLEANER_TRUST_PATH"] = previous


def _run_capture(args: list[str]) -> subprocess.CompletedProcess[str] | None:
    executable = shutil.which(args[0])
    if executable is None:
        return None
    return subprocess.run(
        [executable, *args[1:]],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_subprocess_env(),
    )


@contextlib.contextmanager
def _officecli_probe_copy(docx_path: Path):
    temp_dir = tempfile.mkdtemp(prefix="fcv3_probe_")
    probe_path = Path(temp_dir) / "probe.docx"
    shutil.copy2(str(docx_path), str(probe_path))
    try:
        yield probe_path
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _run_officecli_view(docx_path: Path, *view_args: str) -> subprocess.CompletedProcess[str] | None:
    executable = shutil.which("officecli")
    if executable is None:
        return None
    with _officecli_probe_copy(docx_path) as probe_path:
        return subprocess.run(
            [executable, "view", str(probe_path), *view_args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_subprocess_env(),
        )


def _normalize_space(text: str | None) -> str:
    return " ".join((text or "").split())


def _compact_text(text: str | None) -> str:
    return re.sub(r"\s+", "", text or "")


def _entry_text(entry: dict) -> str:
    return _normalize_space(entry.get("_full_text") or entry.get("text_preview") or "")


def _is_heading_style(style: str | None) -> bool:
    raw = (style or "").strip()
    if not raw:
        return False
    value = raw.lower()
    if "toc" in value or "目录" in raw:
        return False
    if raw.isdigit():
        return 1 <= int(raw) <= 9
    return bool(HEADING_STYLE_RE.match(raw))


def _looks_like_numeric_style_heading(entry: dict) -> bool:
    style = (entry.get("style") or "").strip()
    if not style or not style.isdigit():
        return False
    if not 1 <= int(style) <= 20:
        return False

    text = _entry_text(entry)
    compact = _compact_text(text)
    if not compact or len(compact) > 20:
        return False
    if _looks_like_toc(text) or _looks_like_front_matter(text):
        return False
    if re.search(r"[。！？!?；;]", text):
        return False
    return True


def _looks_like_toc(text: str) -> bool:
    compact = _compact_text(text)
    if compact.lower() == "contents" or compact in {"目录"}:
        return True
    if TOC_LINE_RE.search(text):
        return True
    if PAGE_NUMBER_TOC_RE.match(text) and not BODY_HEADING_RE.match(text):
        return True
    return False


def _looks_like_front_matter(text: str) -> bool:
    compact = _compact_text(text)
    if compact in FRONT_MATTER_TITLES:
        return True
    return any(keyword in compact for keyword in FRONT_MATTER_KEYWORDS)


def _looks_like_numbered_sentence(text: str) -> bool:
    if not BODY_HEADING_RE.match(text):
        return False
    compact = _compact_text(text)
    if len(compact) <= 20:
        return False
    return bool(SENTENCE_END_RE.search(text) or len(compact) >= 28)


def _looks_like_short_structural_title(text: str) -> bool:
    compact = _compact_text(text)
    if not compact:
        return False
    if len(compact) > 20:
        return False
    if BODY_HEADING_RE.match(text):
        return not _looks_like_numbered_sentence(text)
    if re.search(r"[。！？!?；;]", text):
        return False
    if any(ch.isdigit() for ch in compact):
        return False
    if any(keyword in compact for keyword in FRONT_MATTER_KEYWORDS):
        return False
    return compact.endswith(("概览", "概况", "分析", "说明", "综述", "结果", "评估", "背景", "方案", "条件", "特性", "总结", "附表"))


def _looks_like_explanatory_label(text: str) -> bool:
    compact = _compact_text(text).rstrip("：:")
    return compact in {"说明", "备注", "注", "附注", "注释"}


def _looks_like_body_supporting_text(entry: dict) -> bool:
    text = _entry_text(entry)
    if not text:
        return False
    if _looks_like_explanatory_label(text):
        return True
    if _looks_like_toc(text) or _looks_like_front_matter(text):
        return False
    if _looks_like_numbered_sentence(text):
        return True
    return len(_compact_text(text)) >= 24


def _looks_like_data_table(entry: dict) -> bool:
    if entry.get("tag") != "tbl":
        return False
    compact = _compact_text(_entry_text(entry))
    if len(compact) < 32:
        return False
    number_groups = len(re.findall(r"\d+(?:\.\d+)?", compact))
    return number_groups >= 4 or len(compact) >= 96


def _looks_like_short_title_meta(entry: dict) -> bool:
    if entry.get("tag") != "p":
        return False
    text = _entry_text(entry)
    compact = _compact_text(text)
    if not compact or len(compact) > 40:
        return False
    if _looks_like_toc(text) or _looks_like_front_matter(text):
        return False
    if _looks_like_numbered_sentence(text):
        return False
    return True


def _looks_like_leading_body_cluster(elements: list[dict]) -> bool:
    meaningful = [entry for entry in elements if _entry_text(entry)]
    if not meaningful:
        return False

    window = meaningful[:8]

    if _looks_like_body_heading(window[0]):
        suffix = window[1:4]
        if any(_looks_like_body_supporting_text(entry) or _looks_like_data_table(entry) for entry in suffix):
            return True

    carrier_idx = None
    for idx, entry in enumerate(window[:4]):
        text = _entry_text(entry)
        if _looks_like_toc(text):
            return False
        if _looks_like_front_matter(text) and not _looks_like_explanatory_label(text):
            return False
        if _looks_like_data_table(entry):
            carrier_idx = idx
            break

    if carrier_idx is None:
        return False

    prefix = window[:carrier_idx]
    if len(prefix) > 3:
        return False
    if prefix and not all(_looks_like_short_title_meta(entry) for entry in prefix):
        return False

    suffix = window[carrier_idx + 1:carrier_idx + 4]
    if any(_looks_like_toc(_entry_text(entry)) for entry in suffix):
        return False
    if any(_looks_like_body_supporting_text(entry) for entry in suffix):
        return True

    return carrier_idx == 0


def _looks_like_cover_line(entry: dict) -> bool:
    text = _entry_text(entry)
    if not text or len(text) > 32:
        return False
    if _looks_like_toc(text) or _looks_like_front_matter(text):
        return False
    if _looks_like_body_heading(entry):
        return False
    return any(keyword in text for keyword in COVER_LINE_KEYWORDS)


def _looks_like_body_heading(entry: dict) -> bool:
    text = _entry_text(entry)
    if not text:
        return False
    if _looks_like_toc(text) or _looks_like_front_matter(text):
        return False
    if _is_heading_style(entry.get("style")):
        return True
    if _looks_like_numeric_style_heading(entry):
        return True
    if _looks_like_short_structural_title(text):
        return True
    if BODY_HEADING_RE.match(text):
        return not _looks_like_numbered_sentence(text)
    return False


def _load_body_elements(docx_path: Path) -> list[dict]:
    from docx import Document
    import word_cleaner

    doc = Document(str(docx_path))
    return word_cleaner._collect_body_elements(doc.element.body, include_full_text=True)


def _probe_preview(docx_path: Path, max_lines: int = 120) -> tuple[str, str]:
    outline = _run_officecli_view(docx_path, "outline")
    text = _run_officecli_view(docx_path, "text", "--max-lines", str(max_lines))
    if outline is not None and text is not None and outline.returncode == 0 and text.returncode == 0:
        return "officecli", (outline.stdout + "\n" + text.stdout).strip()

    import word_cleaner

    buf = io.StringIO()
    with _trusted_word_env(), contextlib.redirect_stdout(buf):
        word_cleaner.cmd_peek(docx_path, max_paras=max_lines)
    return "word_cleaner", buf.getvalue().strip()


def _detect_anchor(elements: list[dict]) -> WordPlan:
    meaningful = [entry for entry in elements if _entry_text(entry)]
    if not meaningful:
        return WordPlan(action="review", reason="无有效正文")

    first = meaningful[0]
    first_window = meaningful[:6]

    if _looks_like_leading_body_cluster(meaningful):
        return WordPlan(action="skip", reason="首页已形成正文簇（标题块+表格/说明）")

    frontish_seen = False
    coverish_count = 0

    if _looks_like_toc(_entry_text(first)) or _looks_like_front_matter(_entry_text(first)):
        frontish_seen = True
    else:
        for entry in first_window:
            text = _entry_text(entry)
            if not text:
                continue
            if _looks_like_body_heading(entry) or _looks_like_data_table(entry):
                break
            if _looks_like_toc(text) or _looks_like_front_matter(text):
                frontish_seen = True
                break
            if _looks_like_cover_line(entry):
                coverish_count += 1
        if coverish_count >= 2:
            frontish_seen = True

    if not frontish_seen:
        if _looks_like_body_heading(first):
            return WordPlan(action="skip", reason="正文已从首个有效元素开始")
        if _looks_like_data_table(first):
            return WordPlan(action="skip", reason="正文已从首页表格内容开始")
        if any(_looks_like_body_heading(entry) or _looks_like_data_table(entry) for entry in first_window):
            return WordPlan(action="skip", reason="前部未发现明显封面/目录，直接走规范化")
        if len(_entry_text(first)) >= 24:
            return WordPlan(action="skip", reason="前部已是正文内容段落")
        return WordPlan(action="review", reason="无法稳定判断正文起点")

    fallback: dict | None = None
    for idx, entry in enumerate(meaningful):
        text = _entry_text(entry)
        if not text:
            continue

        frontish = _looks_like_toc(text) or _looks_like_front_matter(text)
        if idx < 6 and _looks_like_cover_line(entry):
            frontish = True

        if frontish:
            continue
        if _looks_like_body_heading(entry) or _looks_like_data_table(entry):
            return WordPlan(
                action="trim",
                reason="检测到封面/目录/前序内容，需一次切割",
                anchor_index=entry["index"],
                anchor_para_id=entry.get("paraId"),
                anchor_text=text,
            )
        if fallback is None:
            fallback = entry

    if fallback is not None:
        return WordPlan(
            action="trim",
            reason="未找到强标题锚点，退回到首个非前序正文元素",
            anchor_index=fallback["index"],
            anchor_para_id=fallback.get("paraId"),
            anchor_text=_entry_text(fallback),
        )

    return WordPlan(action="review", reason="文档仅检测到封面/目录，未找到可保留正文")


def _analyze_word_doc(docx_path: Path) -> WordPlan:
    probe_tool, _ = _probe_preview(docx_path)
    plan = _detect_anchor(_load_body_elements(docx_path))
    plan.probe_tool = probe_tool
    return plan


def _verify_word_doc(docx_path: Path) -> tuple[bool, str]:
    outline = _run_officecli_view(docx_path, "outline")
    stats = _run_officecli_view(docx_path, "stats")
    text = _run_officecli_view(docx_path, "text", "--max-lines", "10")

    elements = [entry for entry in _load_body_elements(docx_path) if _entry_text(entry)]
    if not elements:
        return False, "空文档"

    first = elements[0]
    first_text = _entry_text(first)
    if _looks_like_toc(first_text) or _looks_like_front_matter(first_text):
        return False, f"首个有效元素仍像前序内容: {first_text[:40]}"

    if _looks_like_leading_body_cluster(elements):
        return True, first_text[:40]

    if _looks_like_data_table(first):
        if any(
            _looks_like_body_supporting_text(entry) or _looks_like_data_table(entry)
            for entry in elements[1:4]
        ):
            return True, first_text[:40]

    if text is not None and text.returncode == 0:
        first_lines = [line.strip() for line in text.stdout.splitlines() if line.strip()]
        if any(_looks_like_toc(line) or _looks_like_front_matter(line) for line in first_lines[:3]):
            return False, "首页文本仍出现目录/前序特征"

    if stats is not None and stats.returncode == 0:
        stats_text = stats.stdout
        if "paragraphs: 0" in stats_text.lower() and not any(_looks_like_data_table(entry) for entry in elements):
            return False, "stats 显示段落数为 0"

    if outline is not None and outline.returncode == 0:
        outline_lines = [line.strip() for line in outline.stdout.splitlines() if line.strip()]
        if outline_lines and any(_looks_like_toc(line) or _looks_like_front_matter(line) for line in outline_lines[:1]):
            return False, "outline 首项仍像前序标题"

    return True, first_text[:40]


def _copy_to_output(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src), str(dst))


def _process_word_docx(source_path: Path, output_path: Path) -> FileRecord:
    import word_cleaner

    temp_dir = tempfile.mkdtemp(prefix="fcv3_word_")
    work_path = Path(temp_dir) / "work.docx"
    shutil.copy2(str(source_path), str(work_path))

    plan = None
    status = "REVIEW"
    detail = ""

    try:
        with _trusted_word_env():
            plan = _analyze_word_doc(work_path)
            if plan.action == "trim":
                word_cleaner.cmd_trim(
                    work_path,
                    anchor_index=plan.anchor_index,
                    anchor_para_id=plan.anchor_para_id,
                    anchor_text=plan.anchor_text,
                )

            word_cleaner.cmd_normalize(work_path)

            if plan.action == "review":
                _copy_to_output(work_path, output_path)
                detail = f"{plan.reason}；已规范化；需人工复核"
                return FileRecord(kind="word", source=source_path, output=output_path, status="REVIEW", detail=detail)

            verified, verify_detail = _verify_word_doc(work_path)
            corrected = False

            if not verified:
                correction = _analyze_word_doc(work_path)
                if correction.action == "trim":
                    corrected = True
                    word_cleaner.cmd_trim(
                        work_path,
                        anchor_index=correction.anchor_index,
                        anchor_para_id=correction.anchor_para_id,
                        anchor_text=correction.anchor_text,
                    )
                    word_cleaner.cmd_normalize(work_path)
                    verified, verify_detail = _verify_word_doc(work_path)
                    if correction.anchor_text:
                        plan = correction

            _copy_to_output(work_path, output_path)

            if verified:
                if plan.action == "skip" and not corrected:
                    status = "SKIP"
                    detail = f"无需切割；{plan.reason}；已规范化；probe={plan.probe_tool}"
                else:
                    status = "OK"
                    anchor = plan.anchor_text or "未显式锚点"
                    detail = f"锚点: {anchor}；已规范化；probe={plan.probe_tool}"
            else:
                status = "REVIEW"
                anchor = plan.anchor_text or "未定位锚点"
                detail = f"{anchor}；已规范化；需人工复核（{verify_detail}）"

    except Exception as exc:
        return FileRecord(kind="word", source=source_path, output=None, status="FAIL", detail=str(exc))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return FileRecord(kind="word", source=source_path, output=output_path, status=status, detail=detail)


def _find_soffice() -> str | None:
    for name in ("soffice", "libreoffice"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _convert_doc_to_temp_docx(source_path: Path) -> tuple[Path, str]:
    soffice = _find_soffice()
    if not soffice:
        raise RuntimeError("未找到 LibreOffice/soffice，无法转换 .doc 文件")

    temp_dir = tempfile.mkdtemp(prefix="fcv3_doc_")
    proc = subprocess.run(
        [soffice, "--headless", "--convert-to", "docx", "--outdir", temp_dir, str(source_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_subprocess_env(),
    )
    if proc.returncode != 0:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "LibreOffice 转换失败")

    candidates = sorted(Path(temp_dir).glob("*.docx"))
    if not candidates:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError(".doc 转 .docx 后未找到输出文件")

    return candidates[0], temp_dir


def _process_doc_word(source_path: Path, output_path: Path) -> FileRecord:
    temp_docx = None
    temp_dir = None
    try:
        temp_docx, temp_dir = _convert_doc_to_temp_docx(source_path)
        record = _process_word_docx(temp_docx, output_path)
        if record.status != "FAIL":
            record.source = source_path
            record.detail = f"源文件为 .doc；{record.detail}"
        return record
    except Exception as exc:
        return FileRecord(kind="word", source=source_path, output=None, status="FAIL", detail=str(exc))
    finally:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)


def _process_pdf(source_path: Path, output_path: Path) -> FileRecord:
    from pdf_to_word import process_pdf

    try:
        result = process_pdf(source_path, output_dir=output_path.parent)
        return FileRecord(kind="pdf", source=source_path, output=result, status="OK", detail="已转换为 Word")
    except Exception as exc:
        return FileRecord(kind="pdf", source=source_path, output=None, status="FAIL", detail=str(exc))


def _process_excel(source_path: Path, output_path: Path) -> FileRecord:
    from excel_to_word import convert_excel_to_word

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        convert_excel_to_word(source_path, output_path)
        return FileRecord(kind="excel", source=source_path, output=output_path, status="OK", detail="已转换为 Word")
    except Exception as exc:
        return FileRecord(kind="excel", source=source_path, output=None, status="FAIL", detail=str(exc))


def _relative_display(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except Exception:
        return str(path)


def _scan_sources(source_dir: Path, output_dir: Path) -> list[Path]:
    source_dir = source_dir.resolve()
    output_dir = output_dir.resolve()
    files: list[Path] = []

    for path in sorted(source_dir.rglob("*"), key=lambda p: str(p).casefold()):
        if not path.is_file():
            continue
        if path.name.startswith("~$"):
            continue
        if output_dir == path or output_dir in path.parents:
            continue
        if path.suffix.lower() in SUPPORTED_SUFFIXES:
            files.append(path)
    return files


def _output_path_for(source_path: Path, source_dir: Path, output_dir: Path) -> Path:
    relative_parent = source_path.relative_to(source_dir).parent
    if source_path.suffix.lower() in {".pdf", ".xlsx", ".xls", ".xlsm", ".doc"}:
        return output_dir / relative_parent / f"{source_path.stem}.docx"
    return output_dir / relative_parent / source_path.name


def _render_report(source_dir: Path, output_dir: Path, records: list[FileRecord]) -> str:
    pdf_records = [r for r in records if r.kind == "pdf"]
    excel_records = [r for r in records if r.kind == "excel"]
    word_records = [r for r in records if r.kind == "word"]

    pdf_ok = sum(r.status == "OK" for r in pdf_records)
    excel_ok = sum(r.status == "OK" for r in excel_records)
    word_ok = sum(r.status == "OK" for r in word_records)
    word_skip = sum(r.status == "SKIP" for r in word_records)
    word_review = sum(r.status == "REVIEW" for r in word_records)
    word_fail = sum(r.status == "FAIL" for r in word_records)
    total_ok = sum(r.status in {"OK", "SKIP"} for r in records)

    lines = [
        "═══════════════════════════════════════",
        "        素材清洗报告（V4）",
        "═══════════════════════════════════════",
        f"源目录: {source_dir}",
        f"输出目录: {output_dir}",
        "───────────────────────────────────────",
        "文件统计:",
        f"  PDF  文件: {len(pdf_records)} 个（成功 {pdf_ok} / 失败 {len(pdf_records) - pdf_ok}）",
        f"  Excel文件: {len(excel_records)} 个（成功 {excel_ok} / 失败 {len(excel_records) - excel_ok}）",
        f"  Word 文件: {len(word_records)} 个（清洗 {word_ok} / 无需切割 {word_skip} / 人工复核 {word_review} / 失败 {word_fail}）",
        f"  总计: {len(records)} 个文件（成功 {total_ok} / 异常 {len(records) - total_ok}）",
        "───────────────────────────────────────",
        "详细清单:",
    ]

    for record in records:
        src = _relative_display(record.source, source_dir)
        dst = _relative_display(record.output, output_dir) if record.output else "-"
        lines.append(f"  [{record.status}] {src} → {dst} ({record.detail})")

    lines.append("═══════════════════════════════════════")
    return "\n".join(lines)


def _send_feishu_summary(source_dir: Path, output_dir: Path, records: list[FileRecord]) -> None:
    pdf_records = [r for r in records if r.kind == "pdf"]
    excel_records = [r for r in records if r.kind == "excel"]
    word_records = [r for r in records if r.kind == "word"]

    payload = {
        "msg_type": "text",
        "content": {
            "text": (
                "【bid-material-format-cleaner 清洗完成】\n"
                f"源目录: {source_dir}\n"
                f"输出目录: {output_dir}\n"
                f"PDF: {sum(r.status == 'OK' for r in pdf_records)}/{len(pdf_records)} | "
                f"Excel: {sum(r.status == 'OK' for r in excel_records)}/{len(excel_records)} | "
                f"Word: {sum(r.status in {'OK', 'SKIP'} for r in word_records)}/{len(word_records)}\n"
                f"总计: {sum(r.status in {'OK', 'SKIP'} for r in records)}/{len(records)} 个文件处理成功"
            )
        },
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        WEBHOOK,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req) as resp:
        print(f"飞书通知: {resp.read().decode('utf-8')}")


def run(source_dir: Path, output_dir: Path, *, notify: bool) -> int:
    _ensure_venv()
    _ensure_runtime_dependencies()

    output_dir.mkdir(parents=True, exist_ok=True)
    files = _scan_sources(source_dir, output_dir)
    if not files:
        sys.stderr.write("未找到支持的素材文件\n")
        return 1

    print(f"共发现 {len(files)} 个文件")
    records: list[FileRecord] = []

    for path in files:
        output_path = _output_path_for(path, source_dir, output_dir)
        print(f"\n[{path.name}]")
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            record = _process_pdf(path, output_path)
        elif suffix in {".xlsx", ".xls", ".xlsm"}:
            record = _process_excel(path, output_path)
        elif suffix == ".docx":
            record = _process_word_docx(path, output_path)
        else:
            record = _process_doc_word(path, output_path)

        records.append(record)
        print(f"  -> {record.status}: {record.detail}")

    report = _render_report(source_dir, output_dir, records)
    print("\n" + report)

    if notify:
        try:
            _send_feishu_summary(source_dir, output_dir, records)
        except Exception as exc:
            sys.stderr.write(f"飞书通知失败: {exc}\n")

    return 0 if all(record.status in {"OK", "SKIP"} for record in records) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="bid-material-format-cleaner 总控驱动")
    parser.add_argument("source_dir", help="素材根目录")
    parser.add_argument(
        "--output-dir",
        default="Cleaned_Materials",
        help="输出目录（默认: Cleaned_Materials）",
    )
    parser.add_argument(
        "--no-feishu",
        action="store_true",
        help="处理完成后不发送飞书通知（适合本地验证）",
    )
    args = parser.parse_args(argv)

    source_dir = Path(args.source_dir).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not source_dir.exists() or not source_dir.is_dir():
        sys.stderr.write(f"源目录不存在或不是目录: {source_dir}\n")
        return 1

    try:
        return run(source_dir, output_dir, notify=not args.no_feishu)
    except Exception as exc:
        sys.stderr.write(f"driver 执行失败: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
