"""技术标 Wiki 文件卡片 AI 预览的后台生成任务。

「重建 Wiki」只做秒级的结构镜像（注入已缓存预览），缺失预览的 docx 降级为纯目录
卡片。真正耗时的部分 —— 为每个 docx 调 LLM 生成内容预览（实测单文件 ~15s，全量
500+ 文件 ×15s 远超前端 10 分钟 HTTP 超时）—— 拆到本后台任务异步跑：

    重建 Wiki（秒级）         -> 触发本任务（enqueue）
    worker 增量调 LLM 生成预览 -> 进度落盘，前端轮询
    全部生成完               -> 重新镜像 Wiki，把带预览的卡片落到树上

进度真值落在一份全局 runtime JSON（不分项目），前端轮询 GET 端点读它。任务级互斥
复用 Redis job 锁（job_type=technical_wiki_preview，project_id 固定为本 bidType）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.services.bid_runtime_state import read_json_file, write_json_file_atomic
from app.services.bid_type import TECHNICAL_BID_TYPE
from app.services.technical_material_index import (
    TECHNICAL_MATERIAL_INDEX_PATH,
    rebuild_technical_material_index,
)

logger = logging.getLogger(__name__)

# 任务类型名（注册进 job_queue.KNOWN_JOB_TYPES）；project_id 固定用 bidType，全局单例。
PREVIEW_JOB_TYPE = "technical_wiki_preview"
PREVIEW_JOB_PROJECT_ID = TECHNICAL_BID_TYPE

# 进度真值文件，与索引同目录。
PREVIEW_PROGRESS_PATH = TECHNICAL_MATERIAL_INDEX_PATH.parent / "technical_wiki_preview_progress.json"


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_preview_progress() -> dict[str, Any]:
    """读取预览任务进度；不存在返回 idle 初值。"""
    data = read_json_file(PREVIEW_PROGRESS_PATH)
    if not isinstance(data, dict) or not data:
        return {"status": "idle", "done": 0, "total": 0, "updatedAt": "", "message": ""}
    return data


def _write_progress(
    status: str,
    *,
    done: int = 0,
    total: int = 0,
    message: str = "",
) -> None:
    write_json_file_atomic(
        PREVIEW_PROGRESS_PATH,
        {
            "status": status,
            "done": int(done),
            "total": int(total),
            "updatedAt": _now_iso(),
            "message": message,
        },
    )


def enqueue_preview_job() -> dict[str, Any]:
    """把预览生成任务丢进 Redis 队列；已在跑（锁存在）则返回 running，不重复入队。

    返回 {queued, jobId, locked, unavailable}，由 API 端点直接透传给前端。
    """
    from app.services.job_queue import enqueue_generation_job

    try:
        result = enqueue_generation_job(PREVIEW_JOB_TYPE, PREVIEW_JOB_PROJECT_ID, {})
    except Exception as exc:  # pragma: no cover - 队列不可用不应让前端报错崩
        logger.warning("Failed to enqueue technical wiki preview job: %s", exc)
        return {"queued": False, "unavailable": True, "locked": False, "jobId": "", "message": str(exc)}

    if result.queued:
        # 入队成功，预置 running 进度，避免前端首轮轮询看到上一轮的 completed。
        _write_progress("running", message="任务已排队，等待 worker 拉取…")
    return {
        "queued": result.queued,
        "jobId": result.job_id,
        "locked": result.locked,
        "unavailable": result.unavailable,
    }


def get_preview_status() -> dict[str, Any]:
    """返回预览任务状态：落盘进度 + 是否仍持锁（在跑）。"""
    from app.services.job_queue import is_generation_locked

    progress = read_preview_progress()
    running = is_generation_locked(PREVIEW_JOB_TYPE, PREVIEW_JOB_PROJECT_ID)
    return {**progress, "running": bool(running)}


async def generate_technical_wiki_previews(
    _project_id: str = PREVIEW_JOB_PROJECT_ID,
    _data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """后台任务主体：增量为 docx 生成 AI 预览，再重镜像 Wiki。

    签名与其它 job handler 对齐（project_id, data）。整段 best-effort，进度落盘供前端
    轮询。返回 {"status": "success"|"failed", "summary": ...} 供 worker 标记 job 状态。
    """
    # 进度回调按节流落盘：每完成一个文件都写盘成本高，故仅每 5 个或最后一个写一次。
    state = {"last_written": -1}

    def _on_progress(done: int, total: int) -> None:
        if done == total or done - state["last_written"] >= 5 or state["last_written"] < 0:
            state["last_written"] = done
            _write_progress("running", done=done, total=total, message=f"正在生成内容预览 {done}/{total}")

    _write_progress("running", message="正在准备生成内容预览…")
    try:
        # 增量调 LLM 补齐缺失预览（命中缓存的不重算），并把已生成预览注入索引、写盘。
        index_payload = await rebuild_technical_material_index(
            preview_mode="generate",
            progress_cb=_on_progress,
        )

        # 预览写进 DB + 索引后，重新镜像 Wiki，让带预览的文件卡片落到树上。
        # 延迟导入，避免与 wiki_generation 形成循环引用。
        from app.services.wiki_generation import (
            _mirror_technical_index_to_wiki,
            load_technical_material_index,
        )

        if not isinstance(index_payload, dict) or not index_payload.get("tiers"):
            index_payload = load_technical_material_index()
        await _mirror_technical_index_to_wiki(index_payload, mode="replace")

        stats = index_payload.get("stats") if isinstance(index_payload.get("stats"), dict) else {}
        total = int(stats.get("fileCount") or 0)
        _write_progress("completed", done=total, total=total, message="内容预览已全部生成")
        logger.info("technical wiki preview job completed")
        return {"status": "success", "summary": "内容预览已全部生成"}
    except Exception as exc:  # noqa: BLE001 - 失败也要把状态落盘给前端
        logger.exception("technical wiki preview job failed")
        _write_progress("failed", message=f"内容预览生成失败：{exc}"[:200])
        return {"status": "failed", "summary": str(exc)}


# worker 在同步上下文调用，复用一个长存事件循环（与 material_cleaning 同模式）。
_sync_loop: asyncio.AbstractEventLoop | None = None


def _get_sync_loop() -> asyncio.AbstractEventLoop:
    global _sync_loop
    if _sync_loop is None or _sync_loop.is_closed():
        _sync_loop = asyncio.new_event_loop()
    return _sync_loop


def generate_technical_wiki_previews_sync(
    project_id: str = PREVIEW_JOB_PROJECT_ID,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _get_sync_loop().run_until_complete(
        generate_technical_wiki_previews(project_id, data)
    )
