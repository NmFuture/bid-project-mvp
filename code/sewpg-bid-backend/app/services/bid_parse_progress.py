"""S1 解析进度计算族：阶段百分比映射与 ``_progress_callback`` 事件翻译。

从 bid_parse_service.py 拆分搬迁（原 :387-1028），纯搬迁不改实现与签名；
bid_parse_service 门面 re-export 本模块全部符号，外部调用方与 patch 目标
保持 ``app.services.bid_parse_service.<符号>`` 可解析。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

def _progress_ratio(current: Any, total: Any) -> int:
    try:
        current_value = max(0, int(current))
        total_value = max(0, int(total))
    except (TypeError, ValueError):
        return 0
    if total_value <= 0:
        return 0
    return max(0, min(100, round(current_value * 100 / total_value)))


def _progress_between(start: int, end: int, phase_percent: int) -> int:
    bounded = max(0, min(100, int(phase_percent)))
    return max(0, min(100, start + round((end - start) * bounded / 100)))


TECHNICAL_PROGRESS_PHASES: dict[str, dict[str, tuple[int, int]]] = {
    "word": {
        "extract": (8, 24),
        "local_structure": (24, 34),
        "appendix_scan": (34, 40),
        "appendix": (40, 62),
        "prepare": (62, 68),
        "structured": (68, 96),
    },
    "pdf": {
        "extract": (8, 42),
        "local_structure": (42, 50),
        "appendix_scan": (50, 52),
        "appendix": (52, 62),
        "prepare": (62, 68),
        "structured": (68, 96),
    },
}


def _progress_document_kind_from_extension(value: Any) -> str:
    extension = str(value or "").strip().lower()
    return "pdf" if extension == ".pdf" else "word"


def _progress_document_kind_from_payload(payload: dict[str, Any], fallback: str = "word") -> str:
    extension = str(payload.get("fileExtension") or "").strip().lower()
    if not extension:
        file_name = str(payload.get("fileName") or "").strip().lower()
        extension = Path(file_name).suffix.lower() if file_name else ""
    if extension:
        return _progress_document_kind_from_extension(extension)
    return fallback if fallback in TECHNICAL_PROGRESS_PHASES else "word"


def _technical_phase_range(document_kind: str, phase: str) -> tuple[int, int]:
    profile = TECHNICAL_PROGRESS_PHASES.get(document_kind) or TECHNICAL_PROGRESS_PHASES["word"]
    return profile[phase]


def _technical_phase_progress(document_kind: str, phase: str, phase_percent: int) -> int:
    start, end = _technical_phase_range(document_kind, phase)
    return _progress_between(start, end, phase_percent)


def _pdf_extract_phase_percent(payload: dict[str, Any]) -> int:
    page_percent = _progress_ratio(payload.get("currentPage"), payload.get("totalPages"))
    try:
        elapsed_seconds = max(0, int(payload.get("elapsedSeconds") or 0))
    except (TypeError, ValueError):
        elapsed_seconds = 0
    elapsed_percent = min(95, 5 + elapsed_seconds // 4) if elapsed_seconds else 5
    return max(page_percent, elapsed_percent)


def _format_elapsed_duration(seconds: Any) -> str:
    try:
        elapsed_seconds = max(0, int(seconds))
    except (TypeError, ValueError):
        elapsed_seconds = 0
    if elapsed_seconds <= 0:
        return ""
    minutes, remaining_seconds = divmod(elapsed_seconds, 60)
    if minutes:
        return f"{minutes} 分 {remaining_seconds} 秒"
    return f"{remaining_seconds} 秒"


def _opencode_elapsed_seconds(payload: dict[str, Any]) -> int:
    values: list[int] = []
    for key in ("elapsedSeconds", "idleSeconds"):
        try:
            values.append(max(0, int(payload.get(key) or 0)))
        except (TypeError, ValueError):
            values.append(0)
    return max(values or [0])


def _file_extract_phase_percent(current: Any, total: Any, in_file_percent: Any = 25) -> int:
    try:
        current_index = max(1, int(current))
        total_count = max(0, int(total))
        in_file = max(0, min(99, int(in_file_percent)))
    except (TypeError, ValueError):
        return 0
    if total_count <= 0:
        return 0
    completed_before_current = max(0, min(total_count, current_index - 1))
    weighted_current = min(total_count, completed_before_current + in_file / 100)
    return max(0, min(99, round(weighted_current * 100 / total_count)))


def _opencode_progress_from_payload(payload: dict[str, Any]) -> tuple[int, int, int]:
    parts = payload.get("parts") if isinstance(payload.get("parts"), list) else []
    part_count = len(parts)
    trace_status = str(payload.get("status") or "").lower()
    # 分片并发时单个会话的进度不代表整体：任一分片完成都会把 status 置为 completed，
    # 直接采用会让进度条在其余分片仍在跑时跳到 100%。编排层给出聚合百分比时以它为准。
    if payload.get("shardProgress") is not None:
        try:
            shard_percent = max(0, min(99, int(payload.get("shardProgress") or 0)))
        except (TypeError, ValueError):
            shard_percent = 0
        return (
            _technical_phase_progress("word", "structured", shard_percent),
            shard_percent,
            int(payload.get("completedShards") or 0),
        )
    try:
        heartbeat_index = max(0, int(payload.get("heartbeatIndex") or 0))
    except (TypeError, ValueError):
        heartbeat_index = 0
    try:
        idle_seconds = max(0, int(payload.get("idleSeconds") or payload.get("elapsedSeconds") or 0))
    except (TypeError, ValueError):
        idle_seconds = 0
    try:
        elapsed_seconds = max(0, int(payload.get("elapsedSeconds") or 0))
    except (TypeError, ValueError):
        elapsed_seconds = 0
    progress_seconds = max(idle_seconds, elapsed_seconds)
    if trace_status in {"received", "completed"}:
        phase_percent = 100
    elif trace_status in {"waiting", "idle"}:
        phase_percent = 5
    else:
        phase_percent = min(95, 12 + part_count * 6)
    if payload.get("heartbeat") or elapsed_seconds:
        heartbeat_credit = max(heartbeat_index * 3, progress_seconds // 2)
        phase_percent = min(99, max(phase_percent, 12 + part_count * 6 + heartbeat_credit))
    return _technical_phase_progress("word", "structured", phase_percent), phase_percent, part_count


def _progress_callback(service: "BidParseService", project_id: str):
    document_kind = "word"
    # 结构化解析每隔两三秒回一次心跳；events 是 80 条环形缓冲，条条都写会把上传、提取、
    # 附表的阶段记录全挤掉（实测一次 8 分钟的解析，80 条全是「仍在执行」）。
    # 只有真正推进（完成的分片数/已返回片段数变了）才记一条，心跳本身照常刷新
    # 百分比、摘要和 heartbeatAt——卡死检测看的是 heartbeatAt，不看 events。
    last_opencode_advance: int | None = None

    def update(event: str, details: dict[str, Any] | None = None) -> None:
        nonlocal document_kind, last_opencode_advance
        service.raise_if_parse_cancel_requested(project_id)
        payload = details or {}
        document_kind = _progress_document_kind_from_payload(payload, document_kind)
        if event == "upload_ready":
            file_count = int(payload.get("fileCount") or 0)
            service.update_parse_progress(
                project_id,
                percentage=8,
                summary=f"正在保存招标文件，已保存 {payload.get('fileCount', 0)} / {payload.get('fileCount', 0)}。",
                event_step="upload",
                event_message=f"已保存 {payload.get('fileCount', 0)} 个招标文件。",
                phase_key="upload",
                phase_label="上传文件中",
                phase_percent=100,
                current=file_count,
                total=file_count,
                stale_after_seconds=180,
            )
        elif event == "extract_started":
            total = int(payload.get("fileCount") or 0)
            phase_label = "PDF 处理中" if document_kind == "pdf" else "Word 处理中"
            service.update_parse_progress(
                project_id,
                percentage=_technical_phase_progress(document_kind, "extract", 0),
                summary="正在准备读取招标文件。",
                event_step="extract",
                event_message=f"开始提取 {payload.get('fileCount', 0)} 个招标文件。",
                phase_key="extract",
                phase_label=phase_label,
                phase_percent=0,
                current=0,
                total=total,
                stale_after_seconds=300,
            )
        elif event == "extracting_file":
            total = int(payload.get("total") or payload.get("fileCount") or 0)
            current = max(1, int(payload.get("current") or 1))
            is_pdf = document_kind == "pdf"
            phase_percent = _file_extract_phase_percent(current, total, 0 if is_pdf else 5)
            stale_after_seconds = 1800 if is_pdf else 300
            file_name = payload.get("fileName", "招标文件")
            phase_label = "PDF 处理中" if is_pdf else "Word 处理中"
            summary = f"正在解析 {file_name} 的页面与表格。" if is_pdf else f"正在读取 {file_name}，提取可解析文本。"
            event_message = f"开始解析 {file_name} 的页面与表格。" if is_pdf else f"开始读取 {file_name}。"
            service.update_parse_progress(
                project_id,
                percentage=_technical_phase_progress(document_kind, "extract", phase_percent),
                summary=summary,
                event_step="extract",
                event_message=event_message,
                phase_key="extract",
                phase_label=phase_label,
                phase_percent=phase_percent,
                current=current,
                total=total,
                stale_after_seconds=stale_after_seconds,
            )
        elif event == "pdf_extracting_progress":
            file_name = payload.get("fileName", "PDF 招标文件")
            phase_percent = _pdf_extract_phase_percent(payload)
            elapsed_text = _format_elapsed_duration(payload.get("elapsedSeconds"))
            page_text = ""
            try:
                current_page = int(payload.get("currentPage") or 0)
                total_pages = int(payload.get("totalPages") or 0)
            except (TypeError, ValueError):
                current_page = 0
                total_pages = 0
            if current_page > 0 and total_pages > 0:
                page_text = f"，已处理 {current_page} / {total_pages} 页"
            elapsed_suffix = f"，已执行 {elapsed_text}" if elapsed_text else ""
            table_count = int(payload.get("tableCount") or 0)
            table_suffix = f"，已识别 {table_count} 个表格" if table_count > 0 else ""
            service.update_parse_progress(
                project_id,
                percentage=_technical_phase_progress("pdf", "extract", phase_percent),
                summary=f"正在解析页面与表格{page_text}{table_suffix}{elapsed_suffix}。",
                event_step="extract",
                event_message=f"正在解析 {file_name} 的页面与表格{page_text}{elapsed_suffix}。",
                phase_key="extract",
                phase_label="PDF 处理中",
                phase_percent=phase_percent,
                current=current_page,
                total=total_pages,
                stale_after_seconds=1800,
            )
        elif event == "extracting_file_progress":
            total = int(payload.get("total") or payload.get("fileCount") or 0)
            current = max(1, int(payload.get("current") or 1))
            in_file_percent = int(payload.get("progress") or 25)
            phase_percent = _file_extract_phase_percent(current, total, in_file_percent)
            file_name = payload.get("fileName", "招标文件")
            is_pdf = document_kind == "pdf"
            phase_label = "PDF 处理中" if is_pdf else "Word 处理中"
            summary = (
                f"正在解析 {file_name} 的页面与表格，已执行 {_format_elapsed_duration(payload.get('elapsedSeconds'))}。"
                if is_pdf and payload.get("elapsedSeconds")
                else f"正在读取 {file_name}，已提取约 {payload.get('textLength', 0)} 字。"
            )
            service.update_parse_progress(
                project_id,
                percentage=_technical_phase_progress(document_kind, "extract", phase_percent),
                summary=summary,
                event_step="extract",
                event_message=f"{file_name} 文本读取进度 {max(0, min(99, in_file_percent))}%。",
                phase_key="extract",
                phase_label=phase_label,
                phase_percent=phase_percent,
                current=current,
                total=total,
                stale_after_seconds=1800 if is_pdf else 300,
            )
        elif event == "file_extracted":
            total = int(payload.get("total") or payload.get("fileCount") or 0)
            current = int(payload.get("current") or total or 1)
            phase_percent = _progress_ratio(current, total)
            is_pdf = document_kind == "pdf"
            phase_label = "PDF 处理中" if is_pdf else "Word 处理中"
            file_failed = bool(payload.get("failed"))
            if file_failed:
                # 单文件失败隔离：失败在进度里显式可见，整批解析继续。
                summary = f"{payload.get('fileName', '招标文件')} 解析失败：{payload.get('error') or '未知错误'}，已跳过并继续解析其余文件。"
            else:
                summary = (
                    f"PDF 页面与表格解析完成，已提取约 {payload.get('textLength', 0)} 字。"
                    if is_pdf
                    else f"Word 正文读取完成，已提取约 {payload.get('textLength', 0)} 字。"
                )
            service.update_parse_progress(
                project_id,
                percentage=_technical_phase_progress(document_kind, "extract", phase_percent),
                summary=summary,
                event_step="extract",
                event_level="warning" if file_failed else "info",
                event_message=summary,
                phase_key="extract",
                phase_label=phase_label,
                phase_percent=phase_percent,
                current=current,
                total=total or current,
                stale_after_seconds=300,
            )
        elif event == "local_structure_started":
            start, _ = _technical_phase_range(document_kind, "local_structure")
            service.update_parse_progress(
                project_id,
                percentage=start,
                summary="正在整理正文、表格和原文位置。",
                event_step="local_structure",
                event_message="开始整理文档线索。",
                phase_key="local_structure",
                phase_label="整理文档线索中",
                phase_percent=0,
                current=0,
                total=0,
                stale_after_seconds=300,
            )
        elif event == "local_structure_finished":
            _, end = _technical_phase_range(document_kind, "local_structure")
            service.update_parse_progress(
                project_id,
                percentage=end,
                summary=f"文档线索整理完成，已发现 {payload.get('itemCount', 0)} 条候选要求。",
                event_step="local_structure",
                event_message=f"文档线索整理完成，已发现 {payload.get('itemCount', 0)} 条候选要求。",
                phase_key="local_structure",
                phase_label="整理文档线索中",
                phase_percent=100,
                current=int(payload.get("itemCount") or 0),
                total=int(payload.get("itemCount") or 0),
                stale_after_seconds=300,
            )
        elif event == "appendices_started":
            document_count = int(payload.get("documentCount") or 0)
            start, _ = _technical_phase_range(document_kind, "appendix_scan")
            service.update_parse_progress(
                project_id,
                percentage=start,
                summary="正在提取附表。",
                event_step="appendix",
                event_message=f"开始从 {document_count} 个招标文件识别附表。",
                phase_key="appendix",
                phase_label="提取附表中",
                phase_percent=0,
                current=0,
                total=0,
                stale_after_seconds=300,
            )
        elif event == "docx_appendix_scanning":
            file_name = payload.get("fileName", "DOCX 招标文件")
            is_heartbeat = bool(payload.get("heartbeat"))
            heartbeat_index = int(payload.get("heartbeatIndex") or 0)
            elapsed_seconds = int(payload.get("elapsedSeconds") or 0)
            phase_percent = min(30, 5 + heartbeat_index * 5) if is_heartbeat else 3
            summary = (
                f"正在扫描 {file_name} 的附表候选，已等待约 {elapsed_seconds} 秒。"
                if is_heartbeat and elapsed_seconds > 0
                else f"正在扫描 {file_name} 的附表候选。"
            )
            event_message = (
                f"扫描 {file_name} 的附表候选中，已等待约 {elapsed_seconds} 秒。"
                if is_heartbeat and elapsed_seconds > 0
                else f"开始扫描 {file_name} 的附表候选。"
            )
            service.update_parse_progress(
                project_id,
                percentage=_technical_phase_progress(document_kind, "appendix_scan", phase_percent),
                summary=summary,
                event_step="appendix",
                event_message=event_message,
                phase_key="appendix",
                phase_label="提取附表中",
                phase_percent=phase_percent,
                current=0,
                total=0,
                stale_after_seconds=300,
            )
        elif event == "docx_appendix_started":
            total = int(payload.get("total") or 0)
            start, _ = _technical_phase_range(document_kind, "appendix")
            service.update_parse_progress(
                project_id,
                percentage=start,
                summary=f"正在扫描 {payload.get('fileName', 'DOCX 招标文件')} 的附表。",
                event_step="appendix",
                event_message=f"开始生成 {payload.get('fileName', 'DOCX 招标文件')} 的附表 Word。",
                phase_key="appendix",
                phase_label="提取附表中",
                phase_percent=0,
                current=0,
                total=total,
                stale_after_seconds=300,
            )
        elif event == "docx_appendix_materializing":
            current = int(payload.get("current") or 0)
            total = int(payload.get("total") or current or 0)
            is_heartbeat = bool(payload.get("heartbeat"))
            heartbeat_index = int(payload.get("heartbeatIndex") or 0)
            elapsed_seconds = int(payload.get("elapsedSeconds") or 0)
            completed_before_current = max(0, current - 1)
            in_current_credit = min(0.9, heartbeat_index * 0.05) if is_heartbeat else 0
            phase_percent = max(
                0,
                min(
                    99,
                    round((completed_before_current + in_current_credit) * 100 / total) if total > 0 else 0,
                ),
            )
            wait_suffix = f"，已等待约 {elapsed_seconds} 秒" if is_heartbeat and elapsed_seconds > 0 else ""
            service.update_parse_progress(
                project_id,
                percentage=_technical_phase_progress(document_kind, "appendix", phase_percent),
                summary=f"正在提取附表，已生成 {current} / {total or current}{wait_suffix}。",
                event_step="appendix",
                event_message=(
                    f"正在提取附表 {current} / {total or current}："
                    f"{payload.get('title', '附表')}{wait_suffix}"
                ),
                phase_key="appendix",
                phase_label="提取附表中",
                phase_percent=phase_percent,
                current=current,
                total=total or current,
                stale_after_seconds=300,
            )
        elif event == "docx_appendix_progress":
            current = int(payload.get("current") or 0)
            total = int(payload.get("total") or current or 0)
            phase_percent = _progress_ratio(current, total)
            service.update_parse_progress(
                project_id,
                percentage=_technical_phase_progress(document_kind, "appendix", phase_percent),
                summary=f"正在提取附表，已生成 {current} / {total or current}。",
                event_step="appendix",
                event_message=f"附表已生成 {current} / {total or current}：{payload.get('title', '附表')}",
                phase_key="appendix",
                phase_label="提取附表中",
                phase_percent=phase_percent,
                current=current,
                total=total or current,
                stale_after_seconds=300,
            )
        elif event == "docx_appendix_finished":
            total = int(payload.get("total") or payload.get("current") or 0)
            _, end = _technical_phase_range(document_kind, "appendix")
            service.update_parse_progress(
                project_id,
                percentage=end,
                summary=f"附表提取完成，已生成 {total} 个附表。",
                event_step="appendix",
                event_message=f"{payload.get('fileName', 'DOCX 招标文件')} 附表提取完成，共 {total} 个。",
                phase_key="appendix",
                phase_label="提取附表中",
                phase_percent=100,
                current=total,
                total=total,
                stale_after_seconds=300,
            )
        elif event == "business_template_extraction_started":
            service.update_parse_progress(
                project_id,
                percentage=45,
                summary="正在识别商务附件模板。",
                event_step="template",
                event_message=f"开始对 {payload.get('documentCount', 0)} 个招标文件进行商务模板抽取。",
                phase_key="business_template",
                phase_label="识别商务模板",
                phase_percent=0,
                current=0,
                total=int(payload.get("documentCount") or 0),
                stale_after_seconds=600,
            )
        elif event == "business_template_extraction_agent":
            service.update_parse_progress(
                project_id,
                percentage=50,
                summary="opencode 正在识别商务模板。",
                event_step="template",
                event_message="收到商务模板提取进度。",
                opencode_output=payload,
                phase_key="business_template",
                phase_label="识别商务模板",
                phase_percent=50,
                stale_after_seconds=900,
            )
        elif event == "business_template_extraction_finished":
            service.update_parse_progress(
                project_id,
                percentage=55,
                summary="商务附件模板识别已完成。",
                event_step="template",
                event_message=(
                    f"商务模板识别 {payload.get('appendixCount', 0)} 个，"
                    f"警告 {payload.get('warningCount', 0)} 条。"
                ),
                phase_key="business_template",
                phase_label="识别商务模板",
                phase_percent=100,
                current=int(payload.get("appendixCount") or 0),
                total=int(payload.get("appendixCount") or 0),
                stale_after_seconds=300,
            )
        elif event == "appendices_extracted":
            appendix_count = int(payload.get("appendixCount") or 0)
            generated_count = int(payload.get("generatedCount") or 0)
            _, end = _technical_phase_range(document_kind, "appendix")
            service.update_parse_progress(
                project_id,
                percentage=end,
                summary=f"附表提取完成，已生成 {generated_count} / {appendix_count or generated_count}。",
                event_step="appendix",
                event_message=(
                    f"识别附表 {appendix_count} 个，已生成 {generated_count} 个。"
                ),
                phase_key="appendix",
                phase_label="提取附表中",
                phase_percent=100,
                current=generated_count,
                total=appendix_count or generated_count,
                stale_after_seconds=300,
            )
        elif event == "skill_manifest_ready":
            _, end = _technical_phase_range(document_kind, "prepare")
            service.update_parse_progress(
                project_id,
                percentage=end,
                summary="正在整理结构化解析输入。",
                event_step="skill",
                event_message="结构化解析输入已准备。",
                phase_key="skill",
                phase_label="准备结构化解析中",
                phase_percent=100,
                current=1,
                total=1,
                stale_after_seconds=300,
            )
        elif event == "opencode_delta":
            percentage, phase_percent, part_count = _opencode_progress_from_payload(payload)
            elapsed_text = _format_elapsed_duration(_opencode_elapsed_seconds(payload))
            shard_total = int(payload.get("totalShards") or 0)
            if shard_total > 0:
                # 卡片第一行给可核对的计数；耗时另有一行，摘要里再写一遍「已执行 X」是重复。
                summary = (
                    f"正在识别招标文件中的技术要求和原文依据，已完成 "
                    f"{int(payload.get('completedShards') or 0)}/{shard_total} 个分片。"
                )
            elif elapsed_text:
                summary = f"正在识别招标文件中的技术要求和原文依据，已执行 {elapsed_text}。"
            else:
                summary = "正在识别招标文件中的技术要求和原文依据，请稍候。"
            advanced = last_opencode_advance is None or part_count != last_opencode_advance
            last_opencode_advance = part_count
            total_shards = int(payload.get("totalShards") or 0)
            event_message = ""
            if advanced:
                progress_text = (
                    f"已完成 {part_count}/{total_shards} 个分片"
                    if total_shards > 0
                    else f"已返回 {part_count} 段输出"
                )
                event_message = (
                    f"结构化解析{progress_text}，已执行 {elapsed_text}。"
                    if elapsed_text
                    else f"结构化解析{progress_text}。"
                )
            service.update_parse_progress(
                project_id,
                percentage=percentage,
                summary=summary,
                event_step="opencode",
                event_message=event_message,
                opencode_output=payload,
                phase_key="opencode",
                phase_label="结构化解析中",
                phase_percent=phase_percent,
                current=part_count,
                total=0,
                stale_after_seconds=900,
            )
        elif event == "opencode_finished":
            service.update_parse_progress(
                project_id,
                percentage=96,
                summary="结构化解析已完成，正在整理结构化结果。",
                event_step="opencode",
                event_message="结构化解析已完成。",
                phase_key="opencode",
                phase_label="结构化解析中",
                phase_percent=100,
                current=1,
                total=1,
                stale_after_seconds=300,
            )
        elif event == "complete":
            service.update_parse_progress(
                project_id,
                percentage=97,
                summary=f"解析输出已生成，正在写入 {payload.get('extractedCount', 0)} 条结构化要求。",
                event_step="complete",
                event_level="success",
                event_message=(
                    f"解析输出已生成，提取 {payload.get('extractedCount', 0)} 条结构化要求，"
                    f"附表 {payload.get('appendixCount', 0)} 个。"
                ),
                phase_key="finalize",
                phase_label="写入解析结果中",
                phase_percent=50,
                current=int(payload.get("extractedCount") or 0),
                total=int(payload.get("extractedCount") or 0),
                stale_after_seconds=300,
            )
        elif event == "result_persisting":
            extracted_count = int(payload.get("extractedCount") or 0)
            service.update_parse_progress(
                project_id,
                percentage=98,
                summary=f"正在同步 {extracted_count} 条解析结果到项目状态。",
                event_step="finalize",
                event_message=f"正在同步 {extracted_count} 条解析结果到项目状态。",
                phase_key="finalize",
                phase_label="写入解析结果中",
                phase_percent=70,
                current=extracted_count,
                total=extracted_count,
                stale_after_seconds=300,
            )
        elif event == "result_assets_materializing":
            appendix_count = int(payload.get("appendixCount") or 0)
            service.update_parse_progress(
                project_id,
                percentage=99,
                summary=f"正在生成解析结果资产，附表 {appendix_count} 个。",
                event_step="finalize",
                event_message=f"正在生成解析结果资产，附表 {appendix_count} 个。",
                phase_key="finalize",
                phase_label="生成结果资产中",
                phase_percent=90,
                current=appendix_count,
                total=appendix_count,
                stale_after_seconds=300,
            )

    return update
