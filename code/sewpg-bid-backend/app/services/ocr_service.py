from __future__ import annotations

import base64
import mimetypes
import re
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy import desc, select

from app.models import async_session
from app.models.materials import OcrCandidate, OcrTask
from app.services.audit_service import audit_service
from app.services.material_store import material_store
from app.services.peripheral import PeripheralError
from app.services.store import store
from app.services.system_settings import system_settings_service


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def _candidate_field_name(text: str, index: int) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if "：" in clean:
        return clean.split("：", 1)[0][:40] or f"识别字段 {index}"
    if ":" in clean:
        return clean.split(":", 1)[0][:40] or f"识别字段 {index}"
    return f"识别字段 {index}"


def _candidate_value(text: str) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if "：" in clean:
        return clean.split("：", 1)[1].strip()
    if ":" in clean:
        return clean.split(":", 1)[1].strip()
    return clean


def _extract_candidates_from_text(text: str) -> list[dict[str, Any]]:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if not lines and str(text or "").strip():
        lines = [str(text).strip()]
    candidates: list[dict[str, Any]] = []
    for index, line in enumerate(lines[:30], start=1):
        candidates.append(
            {
                "fieldName": _candidate_field_name(line, index),
                "fieldValue": _candidate_value(line),
                "fieldType": "text",
                "confidence": 80,
                "sourceText": line,
                "pageNumber": 1,
            }
        )
    return candidates


class OcrService:
    async def _ensure_tables(self) -> None:
        async with async_session() as session:
            await material_store._ensure_runtime_tables(session)
            await session.commit()

    async def list_tasks(self, project_id: str) -> dict[str, Any]:
        await self._ensure_tables()
        async with async_session() as session:
            tasks = (
                await session.execute(
                    select(OcrTask).where(OcrTask.project_id == project_id).order_by(desc(OcrTask.created_at))
                )
            ).scalars().all()
            candidate_rows = (
                await session.execute(
                    select(OcrCandidate).where(OcrCandidate.project_id == project_id).order_by(OcrCandidate.created_at)
                )
            ).scalars().all()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in candidate_rows:
            grouped.setdefault(row.task_id, []).append(row.to_dict())
        return {"items": [task.to_dict(candidates=grouped.get(task.id, [])) for task in tasks], "total": len(tasks)}

    async def run_ocr(
        self,
        *,
        project_id: str,
        file_name: str,
        content: bytes,
        mime_type: str = "",
        user: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        await self._ensure_tables()
        config = await system_settings_service.get_model_secret_config("ocr")
        if not bool(config.get("enabled")) or not str(config.get("baseUrl") or "").strip():
            raise PeripheralError(400, "请先在系统设置中启用并配置 OCR 模型。", "OCR_CONFIG_REQUIRED")

        task_id = f"OCR-{uuid4().hex[:12]}"
        suffix = Path(file_name).suffix.lower()
        extracted_text = ""
        raw_response: dict[str, Any] = {}
        status = "completed"
        error_message = ""
        page_count = 1
        try:
            if suffix == ".pdf":
                extracted_text, raw_response, page_count = await self._ocr_pdf(content, config)
            elif suffix in IMAGE_SUFFIXES:
                extracted_text, raw_response = await self._ocr_image(content, mime_type or mimetypes.guess_type(file_name)[0] or "image/png", config)
            else:
                raise PeripheralError(400, "OCR 仅支持图片或图片型 PDF。", "OCR_FILE_TYPE_INVALID")
            candidates = _extract_candidates_from_text(extracted_text)
        except Exception as exc:
            status = "failed"
            error_message = str(exc)
            candidates = []

        async with async_session() as session:
            task = OcrTask(
                id=task_id,
                project_id=project_id,
                source_file_name=file_name,
                source_path="",
                mime_type=mime_type,
                status=status,
                error_message=error_message,
                page_count=page_count,
                raw_response=raw_response,
                created_by=str((user or {}).get("name") or "当前用户"),
            )
            session.add(task)
            await session.flush()
            for index, item in enumerate(candidates, start=1):
                session.add(
                    OcrCandidate(
                        id=f"OC-{uuid4().hex[:12]}",
                        task_id=task_id,
                        project_id=project_id,
                        page_number=int(item.get("pageNumber") or 1),
                        field_name=str(item.get("fieldName") or f"识别字段 {index}"),
                        field_value=str(item.get("fieldValue") or ""),
                        field_type=str(item.get("fieldType") or "text"),
                        confidence=int(item.get("confidence") or 80),
                        source_text=str(item.get("sourceText") or ""),
                        status="pending",
                    )
                )
            await session.commit()

        await audit_service.record(
            action="执行 OCR 识别",
            action_type="ocr",
            module_id="ocr",
            module_label="OCR 识别",
            target=f"{project_id} / {file_name}",
            status="成功" if status == "completed" else "失败",
            user=user,
            diff={"before": {}, "after": {"taskId": task_id, "candidateCount": len(candidates), "status": status}},
        )
        return await self.detail(project_id, task_id)

    async def _ocr_image(self, content: bytes, mime_type: str, config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        base_url = str(config.get("baseUrl") or "").strip()
        model = str(config.get("model") or "").strip()
        api_key = str(config.get("apiKey") or "").strip()
        timeout_ms = int(config.get("timeoutMs") or 60000)
        max_tokens = int(config.get("maxTokens") or 2048)
        url = f"{base_url.rstrip('/')}/chat/completions" if base_url.rstrip("/").endswith("/v1") else base_url.rstrip("/")
        data_url = f"data:{mime_type or 'image/png'};base64,{base64.b64encode(content).decode('ascii')}"
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": "Free OCR."},
                    ],
                }
            ],
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": 0,
        }
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=timeout_ms / 1000, trust_env=False) as client:
            response = await client.post(url, headers=headers, json=payload)
        if response.status_code >= 400:
            raise PeripheralError(response.status_code, f"OCR 调用失败：HTTP {response.status_code}", "OCR_REQUEST_FAILED")
        raw = response.json()
        content_text = str(((raw.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
        raw["_latencyMs"] = int((time.perf_counter() - start) * 1000)
        return content_text, raw

    async def _ocr_pdf(self, content: bytes, config: dict[str, Any]) -> tuple[str, dict[str, Any], int]:
        import fitz

        document = fitz.open(stream=content, filetype="pdf")
        texts = []
        raw_pages = []
        for page_index in range(min(len(document), 10)):
            page = document.load_page(page_index)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            text, raw = await self._ocr_image(pix.tobytes("png"), "image/png", config)
            texts.append(text)
            raw_pages.append({"pageNumber": page_index + 1, "response": raw})
        return "\n".join(texts), {"pages": raw_pages}, len(document)

    async def detail(self, project_id: str, task_id: str) -> dict[str, Any]:
        await self._ensure_tables()
        async with async_session() as session:
            task = (
                await session.execute(select(OcrTask).where(OcrTask.project_id == project_id, OcrTask.id == task_id))
            ).scalar_one_or_none()
            if task is None:
                raise PeripheralError(404, "OCR 任务不存在。", "OCR_TASK_NOT_FOUND")
            candidates = (
                await session.execute(select(OcrCandidate).where(OcrCandidate.task_id == task_id).order_by(OcrCandidate.created_at))
            ).scalars().all()
        return task.to_dict(candidates=[item.to_dict() for item in candidates])

    async def confirm_candidate(
        self,
        project_id: str,
        candidate_id: str,
        data: dict[str, Any],
        *,
        user: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        await self._ensure_tables()
        action = str(data.get("action") or "confirm")
        async with async_session() as session:
            candidate = (
                await session.execute(
                    select(OcrCandidate).where(OcrCandidate.project_id == project_id, OcrCandidate.id == candidate_id)
                )
            ).scalar_one_or_none()
            if candidate is None:
                raise PeripheralError(404, "OCR 候选字段不存在。", "OCR_CANDIDATE_NOT_FOUND")
            before = candidate.to_dict()
            if action == "ignore":
                candidate.status = "ignored"
                candidate.ignored_reason = str(data.get("reason") or "人工忽略")
            else:
                candidate.status = "confirmed"
                candidate.confirmed_value = str(data.get("value") or candidate.field_value or "")
                candidate.confirmed_by = str((user or {}).get("name") or "当前用户")
                from datetime import datetime

                candidate.confirmed_at = datetime.now()
                self._write_candidate_to_project(project_id, candidate)
            await session.commit()
            await session.refresh(candidate)
            after = candidate.to_dict()

        await audit_service.record(
            action="确认 OCR 候选字段" if action != "ignore" else "忽略 OCR 候选字段",
            action_type="ocr",
            module_id="ocr",
            module_label="OCR 识别",
            target=f"{project_id} / {candidate_id}",
            user=user,
            diff={"before": before, "after": after},
        )
        return {"message": "OCR 候选字段已处理", "item": after}

    def _write_candidate_to_project(self, project_id: str, candidate: OcrCandidate) -> None:
        project = store._require(project_id)
        parse_result = project.get("parse_result") if isinstance(project.get("parse_result"), dict) else {}
        structured = parse_result.get("structured") if isinstance(parse_result.get("structured"), dict) else {}
        fields = structured.get("ocrConfirmedFields")
        if not isinstance(fields, list):
            fields = []
        fields.append(
            {
                "candidateId": candidate.id,
                "taskId": candidate.task_id,
                "fieldName": candidate.field_name,
                "value": candidate.confirmed_value or candidate.field_value or "",
                "sourceText": candidate.source_text or "",
                "pageNumber": int(candidate.page_number or 1),
                "confirmedAt": candidate.confirmed_at.isoformat() if candidate.confirmed_at else "",
            }
        )
        structured["ocrConfirmedFields"] = fields
        parse_result["structured"] = structured
        project["parse_result"] = parse_result
        from app.services.store import now_iso

        project["updatedAt"] = now_iso()
        store._persist_project(project)


ocr_service = OcrService()
