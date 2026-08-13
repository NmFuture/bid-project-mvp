from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.services.bid_generation_flow import BidGenerationService
from app.services.bid_project_service import technical_project_service
from app.services.job_queue import is_generation_locked
from app.services.technical_score_index_state import score_index_state

SCORE_INDEX_JOB_TYPE = "score_index_xref"


class TechnicalGenerationService(BidGenerationService):
    async def run(
        self,
        project_id: str,
        request: Request,
        data: dict[str, Any] | None = None,
        user: dict[str, Any] | None = None,
    ) -> JSONResponse:
        # 正文拼装和重新生成索引都以 document_path 为最终产物，同时跑会互相顶掉成稿。
        # 反向的拦截在 technical_score_index_flow.run 里。
        index_state = score_index_state(self.ensure_project(project_id))
        if index_state.get("status") == "running" or is_generation_locked(SCORE_INDEX_JOB_TYPE, project_id):
            raise HTTPException(status_code=409, detail="章节索引正在重新生成，请等待完成后再重新生成正文。")
        return await super().run(project_id, request, data, user)


technical_generation_service = TechnicalGenerationService(technical_project_service, "/api/technical/projects")
