"""素材流水线自动衔接（产品裁决 2026-08-04）：上传 → 清洗 → Wiki 增量自动化。

上传后清洗本来就自动入队；这里补上「清洗批次收尾 → 自动触发技术标 Wiki
增量构建（refresh 模式，等价于手动点 Wiki 页刷新）」的衔接：

- 合批天然成立：批量上传逐个清洗，只有「最后一个清洗任务完成、队列排空」
  的时刻触发一次 Wiki refresh，不会每个文件抖一次。
- 纯非 Word 批次（PDF/Excel 不产生清洗任务）由上传入口直接触发。
- Wiki 任务正在运行时来了新批次：落 pending 标记，Wiki 任务结束后补跑一轮，
  保证最后一批必被收录。
- 超大 docx / PDF / XLSX 的预览依赖后台深度解析，而解析几乎必然晚于本轮 Wiki 的
  预览阶段完成：解析批次收尾后再补跑一轮，把兜底卡片升级为正式预览。
- 总开关 MATERIAL_WIKI_AUTO_REFRESH（默认开）。

商务标上传共用清洗队列：其批次收尾也会触发一次技术标 Wiki refresh——
refresh 只补缺失预览，技术标文件没变化时近似空转、不产生模型调用。
"""
from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.core.redis import RedisError, get_redis_client
from app.services.bid_type import TECHNICAL_BID_TYPE

logger = logging.getLogger(__name__)

MATERIAL_CLEANING_JOB_TYPE = "material_cleaning"
MATERIAL_DEEP_PARSE_JOB_TYPE = "material_deep_parse"
_AUTO_REFRESH_PENDING_KEY = "bid:wiki:auto-refresh-pending:technical"
_PENDING_TTL_SEC = 24 * 3600
_DEEP_PARSE_CLAIM_PREFIX = "bid:wiki:auto-refresh-deep-parse:"
_DEEP_PARSE_CLAIM_TTL_SEC = 6 * 3600
_CLEANING_BATCH_TOTAL_KEY = "bid:pipeline:cleaning-batch-total"
_CLEANING_BATCH_TTL_SEC = 24 * 3600


def auto_refresh_enabled() -> bool:
    return bool(settings.material_wiki_auto_refresh)


def _set_pending() -> None:
    client = get_redis_client()
    if client is None:
        return
    try:
        client.set(_AUTO_REFRESH_PENDING_KEY, "1", ex=_PENDING_TTL_SEC)
    except RedisError as exc:
        logger.warning("素材流水线：写入 Wiki 补跑标记失败：%s", exc)


def _consume_pending() -> bool:
    client = get_redis_client()
    if client is None:
        return False
    try:
        return bool(client.delete(_AUTO_REFRESH_PENDING_KEY))
    except RedisError as exc:
        logger.warning("素材流水线：读取 Wiki 补跑标记失败：%s", exc)
        return False


def _claim_deep_parse_refresh(file_id: str, source_version: Any = None) -> bool:
    """深度解析补跑的循环刹车：同一素材同一版本 6 小时内只因深度解析补跑一次 Wiki。

    正常路径补跑一次即可把兜底卡片升级为正式预览；若某素材的解析产物始终满足不了
    预览条件，refresh 会再次排队深度解析，没有这道闸就是 refresh↔解析 无限转圈。
    键里带上入队时快照的素材版本：覆盖上传换版后，旧版本的 claim 不再拦截新版本
    解析完成后的补跑；版本未知（历史任务）时退化为仅按 file_id 去重。
    """
    value = str(file_id or "").strip()
    if not value:
        return False
    version = str(source_version or "").strip()
    key = f"{_DEEP_PARSE_CLAIM_PREFIX}{value}:v{version}" if version else f"{_DEEP_PARSE_CLAIM_PREFIX}{value}"
    client = get_redis_client()
    if client is None:
        return True
    try:
        return bool(
            client.set(
                key,
                "1",
                ex=_DEEP_PARSE_CLAIM_TTL_SEC,
                nx=True,
            )
        )
    except RedisError as exc:
        logger.warning("素材流水线：写入深度解析补跑标记失败：%s", exc)
        return True


def add_cleaning_batch_total(count: int) -> None:
    """累加本轮清洗批次的总量，供进度条算 m/n；队列排空时归零。

    队列查询只能给出「还剩几个」，分母必须在入队时记下来。跨批次累加是对的：
    前一批没跑完又传一批时，用户看到的就是合并后的一条进度。
    """
    if int(count or 0) <= 0:
        return
    client = get_redis_client()
    if client is None:
        return
    try:
        client.incrby(_CLEANING_BATCH_TOTAL_KEY, int(count))
        client.expire(_CLEANING_BATCH_TOTAL_KEY, _CLEANING_BATCH_TTL_SEC)
    except RedisError as exc:
        logger.warning("素材流水线：记录清洗批次总量失败：%s", exc)


def _reset_cleaning_batch_total() -> None:
    client = get_redis_client()
    if client is None:
        return
    try:
        client.delete(_CLEANING_BATCH_TOTAL_KEY)
    except RedisError as exc:
        logger.warning("素材流水线：清空清洗批次总量失败：%s", exc)


def _cleaning_batch_total() -> int:
    client = get_redis_client()
    if client is None:
        return 0
    try:
        return int(client.get(_CLEANING_BATCH_TOTAL_KEY) or 0)
    except (RedisError, TypeError, ValueError) as exc:
        logger.warning("素材流水线：读取清洗批次总量失败：%s", exc)
        return 0


def _has_other_active_jobs(job_type: str, exclude_job_id: str = "") -> bool:
    from app.services.job_queue import find_active_jobs_of_type

    try:
        jobs = find_active_jobs_of_type(job_type)
    except Exception as exc:  # Redis 抖动时按「仍有任务」处理，避免误触发
        logger.warning("素材流水线：查询 %s 队列失败：%s", job_type, exc)
        return True
    excluded = str(exclude_job_id or "")
    return any(str(job.get("id") or "") != excluded for job in jobs)


def _has_other_active_cleaning_jobs(exclude_job_id: str = "") -> bool:
    return _has_other_active_jobs(MATERIAL_CLEANING_JOB_TYPE, exclude_job_id)


def request_technical_wiki_auto_refresh(reason: str = "") -> dict[str, Any] | None:
    """触发一次技术标 Wiki 增量构建；Wiki 正在运行时落补跑标记。"""
    if not auto_refresh_enabled():
        return None
    from app.services.material_wiki_jobs import enqueue_material_wiki_generation
    from app.services.peripheral import PeripheralError

    try:
        result = enqueue_material_wiki_generation(TECHNICAL_BID_TYPE, mode="refresh")
    except PeripheralError as exc:
        if int(getattr(exc, "status_code", 0) or 0) == 409:
            _set_pending()
            logger.info("素材流水线：Wiki 任务运行中，已登记补跑（%s）", reason)
        else:
            logger.warning("素材流水线：自动触发 Wiki 失败（%s）：%s", reason, exc)
        return None
    if result.get("reused"):
        # 复用的是已在运行/排队的任务，可能已错过本批新文件：登记补跑。
        _set_pending()
        logger.info("素材流水线：复用运行中的 Wiki 任务并登记补跑（%s）", reason)
    else:
        logger.info("素材流水线：已自动触发技术标 Wiki 增量构建（%s）→ %s", reason, result.get("jobId"))
    return result


def on_material_cleaning_job_finished(current_job_id: str = "") -> None:
    """清洗任务完成钩子：本任务是队列里最后一个时，触发 Wiki 增量。"""
    if _has_other_active_cleaning_jobs(exclude_job_id=current_job_id):
        return
    # 队列已排空：本轮清洗批次结束，分母归零，进度条不再显示清洗段计数。
    _reset_cleaning_batch_total()
    if not auto_refresh_enabled():
        return
    request_technical_wiki_auto_refresh("清洗批次收尾")


def on_material_wiki_job_finished() -> None:
    """Wiki 任务结束钩子：消费补跑标记，把运行期间到达的新批次补进 Wiki。"""
    if not auto_refresh_enabled():
        return
    if not _consume_pending():
        return
    if _has_other_active_cleaning_jobs():
        # 新批次还在清洗，收尾钩子稍后会触发；标记已消费无需恢复。
        return
    request_technical_wiki_auto_refresh("补跑：Wiki 运行期间到达的新批次")


def on_material_deep_parse_job_finished(
    file_id: str, current_job_id: str = "", source_version: Any = None
) -> None:
    """深度解析完成钩子：产物就绪后补跑一轮 Wiki，把兜底卡片升级为正式预览。

    超大 docx / PDF / XLSX 的预览依赖后台深度解析，而深度解析几乎必然晚于本轮
    Wiki 的预览阶段完成——卡片只能先落「已排队后台深度解析」的本地 TLDR 并标
    retryable，等下一轮刷新升级。手动流程靠人再点一次刷新兜住，自动链路必须自己
    补这一跳，否则卡片永远停在兜底文案（2026-08-05 实测 RAW-2297）。
    source_version 是入队时快照的素材版本，claim 按 文件+版本 去重：
    覆盖上传换版后新版本的解析完成必须能触发新一轮补跑。
    """
    if not auto_refresh_enabled():
        return
    if _has_other_active_jobs(MATERIAL_DEEP_PARSE_JOB_TYPE, exclude_job_id=current_job_id):
        return
    if _has_other_active_cleaning_jobs():
        # 新批次还在清洗，清洗收尾钩子稍后会触发，无需重复。
        return
    if not _claim_deep_parse_refresh(file_id, source_version):
        return
    request_technical_wiki_auto_refresh("深度解析产物就绪")


def on_material_tree_changed(reason: str) -> None:
    """素材树结构变更钩子（删除 / 移动 / 改名）：补一轮 Wiki，让树跟着素材库走。

    Wiki 是素材库三级目录的镜像：删除后 refresh 会清掉「不在本次蓝图内的自动生成
    节点」（手工节点保留），移动/改名则把节点挪到新位置。但这些链路自身都不触发
    刷新——不补这一跳，Wiki 树会一直停在旧结构，直到有人手动刷新为止。
    批量操作是单次调用天然合批；连续操作撞上运行中的任务由 pending 标记补跑。
    """
    if not auto_refresh_enabled():
        return
    request_technical_wiki_auto_refresh(reason)


async def _pending_preview_count() -> int:
    """待补全预览数：预览停在 retryable 兜底、等下一轮刷新升级的素材条数。

    进度条据此如实收尾——队列已空但仍有待补全时不能装作全部完成。
    """
    from app.services.technical_wiki_preview_generation import count_retryable_previews

    try:
        return await count_retryable_previews()
    except Exception as exc:  # 计数失败不应阻断进度查询
        logger.warning("素材流水线：查询待补全预览数失败：%s", exc)
        return 0


async def technical_pipeline_progress() -> dict[str, Any]:
    """素材流水线进度聚合：清洗队列剩余 + 最新 Wiki 任务阶段进度，供前端进度条轮询。"""
    from app.services.job_queue import find_active_jobs_of_type
    from app.services.material_wiki_jobs import latest_material_wiki_job_status
    from app.services.peripheral import PeripheralError

    def _queue_snapshot(job_type: str) -> dict[str, int]:
        try:
            jobs = find_active_jobs_of_type(job_type)
        except Exception as exc:
            logger.warning("素材流水线：查询 %s 进度失败：%s", job_type, exc)
            jobs = []
        return {
            "active": len(jobs),
            "processing": sum(1 for job in jobs if str(job.get("status") or "") == "processing"),
        }

    cleaning = _queue_snapshot(MATERIAL_CLEANING_JOB_TYPE)
    # 清洗 m/n：分母是入队时记下的批次总量，done = 总量 - 队列剩余。
    cleaning_total = _cleaning_batch_total()
    if cleaning_total > 0:
        cleaning["total"] = cleaning_total
        cleaning["done"] = max(0, cleaning_total - cleaning["active"])
    deep_parse = _queue_snapshot(MATERIAL_DEEP_PARSE_JOB_TYPE)
    wiki: dict[str, Any] = {"status": "idle"}
    try:
        wiki = latest_material_wiki_job_status(TECHNICAL_BID_TYPE)
    except PeripheralError as exc:
        logger.warning("素材流水线：查询 Wiki 进度失败：%s", exc)
    return {
        "cleaning": cleaning,
        "deepParse": deep_parse,
        "wiki": wiki,
        "pendingPreview": await _pending_preview_count(),
        "autoRefresh": auto_refresh_enabled(),
    }


def on_material_upload_completed(clean_job_count: int) -> None:
    """上传入口钩子：记清洗批次分母；本批未产生清洗任务（纯 PDF/Excel）时直接触发 Wiki 增量。"""
    add_cleaning_batch_total(int(clean_job_count or 0))
    if not auto_refresh_enabled():
        return
    if int(clean_job_count or 0) > 0:
        return
    if _has_other_active_cleaning_jobs():
        return
    request_technical_wiki_auto_refresh("纯非清洗批次上传")
