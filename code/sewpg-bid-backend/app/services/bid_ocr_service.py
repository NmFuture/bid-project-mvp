from __future__ import annotations

from typing import Any

from app.services.bid_project_service import BidProjectService, business_project_service, technical_project_service
from app.services.ocr_service import ocr_service


class BidOcrService:
    def __init__(self, project_service: BidProjectService) -> None:
        self.project_service = project_service

    def _audit_metadata(self, project: dict[str, Any]) -> dict[str, Any]:
        return {
            "projectId": str(project.get("id") or ""),
            "projectName": str(project.get("name") or ""),
            "projectCode": str(project.get("projectCode") or project.get("id") or ""),
            "customerName": str(project.get("customerName") or ""),
            "bidType": self.project_service.bid_type,
        }

    async def list_tasks(self, project_id: str) -> dict[str, Any]:
        self.project_service.ensure_project(project_id)
        return await ocr_service.list_tasks(project_id)

    async def run(
        self,
        *,
        project_id: str,
        file_name: str,
        content: bytes,
        mime_type: str = "",
        user: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project = self.project_service.ensure_project(project_id)
        return await ocr_service.run_ocr(
            project_id=project_id,
            file_name=file_name,
            content=content,
            mime_type=mime_type,
            user=user,
            audit_metadata=self._audit_metadata(project),
        )

    async def detail(self, project_id: str, task_id: str) -> dict[str, Any]:
        self.project_service.ensure_project(project_id)
        return await ocr_service.detail(project_id, task_id)

    async def confirm_candidate(
        self,
        project_id: str,
        candidate_id: str,
        data: dict[str, Any],
        *,
        user: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project = self.project_service.ensure_project(project_id)
        return await ocr_service.confirm_candidate(
            project_id,
            candidate_id,
            data,
            user=user,
            audit_metadata=self._audit_metadata(project),
        )


business_ocr_service = BidOcrService(business_project_service)
technical_ocr_service = BidOcrService(technical_project_service)
