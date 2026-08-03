from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.services.auth_service import current_user
from app.services.job_timing import get_job_timing, list_job_timings, summarize_job_timings

router = APIRouter()


@router.get("/api/monitoring/job-timings")
async def monitoring_job_timings(
    jobType: str = Query(default=""),
    bidType: str = Query(default=""),
    projectId: str = Query(default=""),
    status: str = Query(default=""),
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=50, ge=1, le=500),
    _: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return await list_job_timings(
        job_type=jobType.strip(),
        bid_type=bidType.strip(),
        project_id=projectId.strip(),
        status=status.strip(),
        days=days,
        limit=limit,
    )


# 注意：summary 必须声明在 {timing_id} 之前，否则会被路径参数抢占。
@router.get("/api/monitoring/job-timings/summary")
async def monitoring_job_timings_summary(
    days: int = Query(default=7, ge=1, le=90),
    _: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    return await summarize_job_timings(days=days)


@router.get("/api/monitoring/job-timings/{timing_id}")
async def monitoring_job_timing_detail(
    timing_id: int,
    _: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    item = await get_job_timing(timing_id)
    if item is None:
        raise HTTPException(status_code=404, detail="任务耗时记录不存在。")
    return item
