from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy import and_, desc, func, or_, select, update

from app.core.config import settings
from app.models import async_session
from app.models.materials import OcrCandidate, OcrTask
from app.services.audit_service import audit_service
from app.services.material_runtime_tables import ensure_material_runtime_tables
from app.services.peripheral import PeripheralError
from app.services.system_settings import system_settings_service
from app.services.workspace_project_access import (
    persist_workspace_project_state,
    require_any_workspace_project_for_update,
)


logger = logging.getLogger(__name__)


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
UNLIMITED_OCR_MODEL_MARKER = "unlimited-ocr"

_OCR_MAX_CONCURRENT = 8
_OCR_MAX_RETRIES = 2
_OCR_WORKER_IDLE_SLEEP = 1.0
_OCR_WAIT_POLL_INTERVAL = 0.5
_OCR_INTERNAL_PROJECT_ID = "_internal_ocr_"
# processing 任务锁超时（秒）：超时视为进程崩溃遗留，允许回收重领
_OCR_LOCK_TIMEOUT_SECONDS = 600
# 持有者心跳续租间隔（秒）：远小于锁超时，避免长任务被误判崩溃而重领
_OCR_HEARTBEAT_INTERVAL_SECONDS = 60


def _ocr_project_not_found(project_id: str) -> PeripheralError:
    return PeripheralError(404, "OCR 项目不存在。", "OCR_PROJECT_NOT_FOUND")


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


def _is_unlimited_ocr_config(config: dict[str, Any]) -> bool:
    return UNLIMITED_OCR_MODEL_MARKER in str(config.get("model") or "").lower()


def _chat_completions_url(base_url: str) -> str:
    url = str(base_url or "").strip().rstrip("/")
    if not url:
        return ""
    if url.endswith("/chat/completions"):
        return url
    if url.endswith("/v1"):
        return f"{url}/chat/completions"
    return f"{url}/chat/completions"


def _clean_unlimited_ocr_text(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"<\|det\|>.*?<\|/det\|>", "", value, flags=re.DOTALL)
    value = value.replace("<|ref|>", "").replace("<|/ref|>", "")
    return value.strip()


def _extract_chat_content(raw: dict[str, Any]) -> str:
    return str(((raw.get("choices") or [{}])[0].get("message") or {}).get("content") or "")


class OcrService:
    def __init__(self) -> None:
        self._ocr_semaphore = asyncio.Semaphore(_OCR_MAX_CONCURRENT)
        self._worker_tasks: list[asyncio.Task[Any]] = []
        self._shutdown_event = asyncio.Event()

    async def start_worker(self) -> None:
        """启动后台 OCR worker（幂等），并发数 = _OCR_MAX_CONCURRENT。"""
        completed_tasks = [task for task in self._worker_tasks if task.done()]
        for task in completed_tasks:
            if not task.cancelled():
                task.exception()

        active_tasks = [task for task in self._worker_tasks if not task.done()]
        if active_tasks:
            self._worker_tasks = active_tasks
            return

        # asyncio 同步原语会绑定首次使用它们的 event loop；每代 worker 必须独立创建。
        self._shutdown_event = asyncio.Event()
        self._ocr_semaphore = asyncio.Semaphore(_OCR_MAX_CONCURRENT)
        self._worker_tasks = [
            asyncio.create_task(self._ocr_worker_loop())
            for _ in range(_OCR_MAX_CONCURRENT)
        ]

    async def stop_worker(self) -> None:
        """优雅停止后台 OCR worker。"""
        self._shutdown_event.set()
        tasks = list(self._worker_tasks)
        try:
            if tasks:
                _done, pending = await asyncio.wait(tasks, timeout=10.0)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            self._worker_tasks = []

    async def _ocr_worker_loop(self) -> None:
        while not self._shutdown_event.is_set():
            try:
                processed = await self._process_one_pending_task()
            except Exception:
                # Worker 不应因单条任务异常而退出
                processed = False
            if not processed:
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(), timeout=_OCR_WORKER_IDLE_SLEEP
                    )
                except asyncio.TimeoutError:
                    pass

    async def _process_one_pending_task(self) -> bool:
        now = datetime.now(timezone.utc)
        lock_timeout_at = now - timedelta(seconds=_OCR_LOCK_TIMEOUT_SECONDS)
        # 可领取条件：未锁定的 pending，或锁超时（进程崩溃遗留）的 processing
        claimable = or_(
            and_(OcrTask.status == "pending", OcrTask.locked_at.is_(None)),
            and_(OcrTask.status == "processing", OcrTask.locked_at < lock_timeout_at),
        )
        async with async_session() as session:
            candidate_id = (
                await session.execute(
                    select(OcrTask.id)
                    .where(claimable)
                    .order_by(OcrTask.created_at)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if candidate_id is None:
                return False
            # 单条原子条件更新完成 claim，避免多 worker/副本重复领取同一任务；
            # 同时写入持有者标识并递增 fencing token，供续租与结果写入校验
            owner = f"ocr-worker-{uuid4().hex[:12]}"
            claimed = (
                await session.execute(
                    update(OcrTask)
                    .where(OcrTask.id == candidate_id, claimable)
                    .values(
                        status="processing",
                        locked_at=now,
                        locked_by=owner,
                        fence_token=func.coalesce(OcrTask.fence_token, 0) + 1,
                    )
                    .returning(OcrTask.id, OcrTask.fence_token)
                )
            ).first()
            await session.commit()
            if claimed is None:
                # 被其他 worker 抢走，返回 True 继续抢下一条而不空转 sleep
                return True
            claimed_id, fence_token = claimed

        async with self._ocr_semaphore:
            await self._process_task(claimed_id, owner, int(fence_token or 0))
        return True

    async def _process_task(self, task_id: str, owner: str, fence_token: int) -> None:
        lost_lease = asyncio.Event()
        heartbeat = asyncio.create_task(
            self._heartbeat_loop(task_id, owner, fence_token, lost_lease, asyncio.current_task())
        )
        try:
            await self._run_claimed_task(task_id, owner, fence_token, lost_lease)
        except asyncio.CancelledError:
            # 续租失败导致的取消静默放弃（任务已被新持有者接管）；worker 关停仍向上抛
            if lost_lease.is_set():
                logger.info("OCR 任务 %s 租约已易主，放弃本地处理", task_id)
                return
            raise
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

    async def _heartbeat_loop(
        self,
        task_id: str,
        owner: str,
        fence_token: int,
        lost_lease: asyncio.Event,
        parent_task: "asyncio.Task[Any] | None",
    ) -> None:
        try:
            while True:
                await asyncio.sleep(_OCR_HEARTBEAT_INTERVAL_SECONDS)
                if not await self._renew_lease(task_id, owner, fence_token):
                    lost_lease.set()
                    logger.warning("OCR 任务 %s 续租失败，租约已易主", task_id)
                    if parent_task is not None:
                        parent_task.cancel()
                    return
        except asyncio.CancelledError:
            return

    async def _renew_lease(self, task_id: str, owner: str, fence_token: int) -> bool:
        """以 (task_id, owner, fence_token) 条件刷新 locked_at；返回 False 表示租约已失。"""
        async with async_session() as session:
            renewed_id = (
                await session.execute(
                    update(OcrTask)
                    .where(self._fencing_guard(task_id, owner, fence_token))
                    .values(locked_at=datetime.now(timezone.utc))
                    .returning(OcrTask.id)
                )
            ).scalar_one_or_none()
            await session.commit()
        return renewed_id is not None

    async def _run_claimed_task(
        self,
        task_id: str,
        owner: str,
        fence_token: int,
        lost_lease: asyncio.Event,
    ) -> None:
        async with async_session() as session:
            task = (
                await session.execute(select(OcrTask).where(OcrTask.id == task_id))
            ).scalar_one_or_none()
            if task is None:
                return
            # 快照任务字段后即释放会话，避免长 OCR 期间持有数据库连接
            project_id = task.project_id
            file_name = task.source_file_name
            mime_type = task.mime_type
            input_path_str = task.input_path
            retry_count = int(task.retry_count or 0)
            max_retries = int(task.max_retries or _OCR_MAX_RETRIES)
            audit_meta = task.audit_meta or {}
            config = await system_settings_service.get_model_secret_config("ocr")

        def _task_snapshot(status: str) -> OcrTask:
            return OcrTask(
                id=task_id,
                project_id=project_id,
                source_file_name=file_name,
                audit_meta=audit_meta,
                status=status,
            )

        if not bool(config.get("enabled")) or not str(config.get("baseUrl") or "").strip():
            finalized, _ = await self._finalize_task_failure(
                task_id,
                owner,
                fence_token,
                error_message="OCR 模型未启用或未配置",
                retry_count=retry_count,
                max_retries=max_retries,
                allow_retry=False,
            )
            if finalized:
                await self._record_task_audit(_task_snapshot("failed"), [], succeeded=False)
            return

        input_path = Path(input_path_str) if input_path_str else None
        if input_path is None or not input_path.exists():
            finalized, _ = await self._finalize_task_failure(
                task_id,
                owner,
                fence_token,
                error_message="OCR 任务输入文件丢失",
                retry_count=retry_count,
                max_retries=max_retries,
                allow_retry=False,
            )
            if finalized:
                await self._record_task_audit(_task_snapshot("failed"), [], succeeded=False)
            return

        try:
            content = input_path.read_bytes()
            suffix = Path(file_name).suffix.lower()
            extracted_text = ""
            raw_response: dict[str, Any] = {}
            page_count = 1
            if suffix == ".pdf":
                extracted_text, raw_response, page_count = await self._ocr_pdf(content, config)
            elif suffix in IMAGE_SUFFIXES:
                extracted_text, raw_response = await self._ocr_image(
                    content,
                    mime_type or mimetypes.guess_type(file_name)[0] or "image/png",
                    config,
                )
                page_count = 1
            else:
                raise PeripheralError(400, "OCR 仅支持图片或图片型 PDF。", "OCR_FILE_TYPE_INVALID")

            candidates = _extract_candidates_from_text(extracted_text)
        except Exception as exc:
            if lost_lease.is_set():
                return
            finalized, is_final_failure = await self._finalize_task_failure(
                task_id,
                owner,
                fence_token,
                error_message=str(exc),
                retry_count=retry_count,
                max_retries=max_retries,
                allow_retry=True,
            )
            if finalized and is_final_failure:
                await self._record_task_audit(_task_snapshot("failed"), [], succeeded=False)
            return

        if lost_lease.is_set():
            return
        finalized = await self._finalize_task_success(
            task_id,
            owner,
            fence_token,
            project_id=project_id,
            page_count=page_count,
            raw_response=raw_response,
            extracted_text=extracted_text,
            candidates=candidates,
        )
        if not finalized:
            # fencing 校验失败：任务已被接管或重复提交，丢弃迟到/重复结果
            logger.warning("OCR 任务 %s 结果写入被 fencing 拒绝，丢弃迟到/重复结果", task_id)
            return
        self._delete_task_input(input_path)
        await self._record_task_audit(_task_snapshot("completed"), candidates, succeeded=True)

    def _fencing_guard(self, task_id: str, owner: str, fence_token: int) -> Any:
        """结果写入/续租的持有者校验：仅当前 fencing token 持有者可写。"""
        return and_(
            OcrTask.id == task_id,
            OcrTask.status == "processing",
            OcrTask.locked_by == owner,
            OcrTask.fence_token == fence_token,
        )

    async def _finalize_task_success(
        self,
        task_id: str,
        owner: str,
        fence_token: int,
        *,
        project_id: str,
        page_count: int,
        raw_response: dict[str, Any],
        extracted_text: str,
        candidates: list[dict[str, Any]],
    ) -> bool:
        """按 fencing 条件写入成功结果并落候选；返回 False 表示结果被丢弃。

        幂等：guard 要求任务仍处于 processing 且持有者/token 匹配，
        已 completed 或被接管的任务重复提交不会再次写候选。
        """
        async with async_session() as session:
            finalized_id = (
                await session.execute(
                    update(OcrTask)
                    .where(self._fencing_guard(task_id, owner, fence_token))
                    .values(
                        status="completed",
                        page_count=page_count,
                        raw_response={**raw_response, "extractedText": extracted_text},
                        error_message="",
                        locked_at=datetime.now(timezone.utc),
                    )
                    .returning(OcrTask.id)
                )
            ).scalar_one_or_none()
            if finalized_id is None:
                await session.rollback()
                return False
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
        return True

    async def _finalize_task_failure(
        self,
        task_id: str,
        owner: str,
        fence_token: int,
        *,
        error_message: str,
        retry_count: int,
        max_retries: int,
        allow_retry: bool,
    ) -> tuple[bool, bool]:
        """按 fencing 条件写入失败/重试状态。返回 (是否写入成功, 是否最终失败)。"""
        can_retry = allow_retry and retry_count < max_retries
        values: dict[str, Any] = {
            "status": "pending" if can_retry else "failed",
            "error_message": error_message,
            "locked_at": None,
            "locked_by": None,
        }
        if can_retry:
            values["retry_count"] = retry_count + 1
        async with async_session() as session:
            finalized_id = (
                await session.execute(
                    update(OcrTask)
                    .where(self._fencing_guard(task_id, owner, fence_token))
                    .values(**values)
                    .returning(OcrTask.id)
                )
            ).scalar_one_or_none()
            await session.commit()
        return finalized_id is not None, not can_retry

    def _persist_task_input(self, task_id: str, file_name: str, content: bytes) -> Path:
        directory = settings.documents_dir / "_runtime" / "ocr_inputs" / task_id
        directory.mkdir(parents=True, exist_ok=True)
        safe_name = Path(file_name).name
        path = directory / safe_name
        path.write_bytes(content)
        return path

    def _delete_task_input(self, input_path: Path | None) -> None:
        if input_path is None:
            return
        try:
            if input_path.exists():
                input_path.unlink()
            parent = input_path.parent
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
        except Exception:
            pass

    async def _record_task_audit(
        self,
        task: OcrTask,
        candidates: list[OcrCandidate],
        *,
        succeeded: bool,
    ) -> None:
        audit_meta = task.audit_meta or {}
        user = audit_meta.get("user")
        audit_metadata = audit_meta.get("audit_metadata") or {}
        await self._record_audit_best_effort(
            failure_context=f"执行任务 {task.id}",
            action="执行 OCR 识别",
            action_type="ocr",
            module_id="ocr",
            module_label="OCR 识别",
            target=f"{task.project_id} / {task.source_file_name}",
            status="成功" if succeeded else "失败",
            user=user,
            diff={
                "before": {},
                "after": {
                    "taskId": task.id,
                    "candidateCount": len(candidates),
                    "status": task.status,
                },
            },
            metadata={
                **audit_metadata,
                "taskId": task.id,
                "fileName": task.source_file_name,
                "candidateCount": len(candidates),
                "ocrStatus": task.status,
            },
        )

    async def _record_audit_best_effort(
        self,
        *,
        failure_context: str,
        **audit_payload: Any,
    ) -> None:
        try:
            await audit_service.record(**audit_payload)
        except Exception:
            logger.exception("OCR 审计记录失败：%s", failure_context)

    async def _wait_for_task(
        self,
        task_id: str,
        *,
        timeout: float = 300.0,
    ) -> tuple[OcrTask, list[OcrCandidate]]:
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            async with async_session() as session:
                task = (
                    await session.execute(select(OcrTask).where(OcrTask.id == task_id))
                ).scalar_one_or_none()
                if task is None:
                    raise PeripheralError(404, "OCR 任务不存在。", "OCR_TASK_NOT_FOUND")
                if task.status == "completed":
                    candidates = (
                        await session.execute(
                            select(OcrCandidate).where(OcrCandidate.task_id == task_id).order_by(OcrCandidate.created_at)
                        )
                    ).scalars().all()
                    return task, list(candidates)
                if task.status == "failed":
                    raise PeripheralError(
                        500,
                        f"OCR 识别失败：{task.error_message or '未知错误'}",
                        "OCR_TASK_FAILED",
                    )
            await asyncio.sleep(_OCR_WAIT_POLL_INTERVAL)
        raise PeripheralError(408, "OCR 识别超时。", "OCR_TASK_TIMEOUT")

    async def _ensure_tables(self) -> None:
        async with async_session() as session:
            await ensure_material_runtime_tables(session)
            await session.commit()

    async def recognize_text_for_parse(
        self,
        *,
        file_name: str,
        content: bytes,
        mime_type: str = "",
    ) -> tuple[str, dict[str, Any]]:
        await self._ensure_tables()
        config = await system_settings_service.get_model_secret_config("ocr")
        if not bool(config.get("enabled")) or not str(config.get("baseUrl") or "").strip():
            raise PeripheralError(400, "请先在系统设置中启用并配置 OCR 模型。", "OCR_CONFIG_REQUIRED")

        suffix = Path(file_name).suffix.lower()
        if suffix not in ({".pdf"} | IMAGE_SUFFIXES):
            raise PeripheralError(400, "OCR 仅支持图片或图片型 PDF。", "OCR_FILE_TYPE_INVALID")

        task_id = f"OCR-{uuid4().hex[:12]}"
        input_path = self._persist_task_input(task_id, file_name, content)

        async with async_session() as session:
            task = OcrTask(
                id=task_id,
                project_id=_OCR_INTERNAL_PROJECT_ID,
                source_file_name=file_name,
                source_path="",
                mime_type=mime_type,
                status="pending",
                page_count=0,
                retry_count=0,
                max_retries=_OCR_MAX_RETRIES,
                input_path=str(input_path),
                created_by="system",
            )
            session.add(task)
            await session.commit()

        await self.start_worker()
        completed_task, _candidates = await self._wait_for_task(task_id)
        return completed_task.raw_response.get("extractedText") or "", {
            "status": completed_task.status,
            "pageCount": completed_task.page_count,
            "rawResponse": completed_task.raw_response,
        }

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
        audit_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        await self._ensure_tables()
        config = await system_settings_service.get_model_secret_config("ocr")
        if not bool(config.get("enabled")) or not str(config.get("baseUrl") or "").strip():
            raise PeripheralError(400, "请先在系统设置中启用并配置 OCR 模型。", "OCR_CONFIG_REQUIRED")

        suffix = Path(file_name).suffix.lower()
        if suffix not in ({".pdf"} | IMAGE_SUFFIXES):
            raise PeripheralError(400, "OCR 仅支持图片或图片型 PDF。", "OCR_FILE_TYPE_INVALID")

        task_id = f"OCR-{uuid4().hex[:12]}"
        input_path = self._persist_task_input(task_id, file_name, content)

        async with async_session() as session:
            task = OcrTask(
                id=task_id,
                project_id=project_id,
                source_file_name=file_name,
                source_path="",
                mime_type=mime_type,
                status="pending",
                page_count=0,
                retry_count=0,
                max_retries=_OCR_MAX_RETRIES,
                input_path=str(input_path),
                audit_meta={
                    "user": user,
                    "audit_metadata": audit_metadata,
                },
                created_by=str((user or {}).get("name") or "当前用户"),
            )
            session.add(task)
            await session.commit()
            pending_payload = task.to_dict(candidates=[])

        await self.start_worker()

        await self._record_audit_best_effort(
            failure_context=f"提交任务 {task_id}",
            action="提交 OCR 识别任务",
            action_type="ocr",
            module_id="ocr",
            module_label="OCR 识别",
            target=f"{project_id} / {file_name}",
            status="成功",
            user=user,
            diff={"before": {}, "after": {"taskId": task_id, "status": "pending"}},
            metadata={
                **(audit_metadata or {}),
                "taskId": task_id,
                "fileName": file_name,
                "ocrStatus": "pending",
            },
        )
        return pending_payload

    async def _ocr_image(self, content: bytes, mime_type: str, config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        data_url = f"data:{mime_type or 'image/png'};base64,{base64.b64encode(content).decode('ascii')}"
        raw = await self._ocr_chat_completion(
            [
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
            config,
            multi_page=False,
        )
        content_text = _extract_chat_content(raw)
        if _is_unlimited_ocr_config(config):
            content_text = _clean_unlimited_ocr_text(content_text)
        return content_text, raw

    async def _ocr_chat_completion(
        self,
        images: list[dict[str, Any]],
        config: dict[str, Any],
        *,
        multi_page: bool,
    ) -> dict[str, Any]:
        base_url = str(config.get("baseUrl") or "").strip()
        model = str(config.get("model") or "").strip()
        api_key = str(config.get("apiKey") or "").strip()
        timeout_ms = int(config.get("timeoutMs") or 60000)
        max_tokens = int(config.get("maxTokens") or 2048)
        url = _chat_completions_url(base_url)
        is_unlimited_ocr = _is_unlimited_ocr_config(config)
        text_prompt = "<image>Multi page parsing." if is_unlimited_ocr and multi_page else (
            "<image>document parsing." if is_unlimited_ocr else "Free OCR."
        )
        content = [{"type": "text", "text": text_prompt}] + images if is_unlimited_ocr else images + [{"type": "text", "text": text_prompt}]
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": content,
                }
            ],
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": 0,
        }
        if is_unlimited_ocr:
            payload["skip_special_tokens"] = False
            payload["vllm_xargs"] = {
                "ngram_size": 35,
                "window_size": 1024 if multi_page else 128,
            }
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=timeout_ms / 1000, trust_env=False) as client:
            response = await client.post(url, headers=headers, json=payload)
        if response.status_code >= 400:
            detail = re.sub(r"\s+", " ", response.text or "").strip()[:200]
            raise PeripheralError(
                response.status_code,
                f"OCR 调用失败：HTTP {response.status_code}" + (f"（{detail}）" if detail else ""),
                "OCR_REQUEST_FAILED",
            )
        raw = response.json()
        raw["_latencyMs"] = int((time.perf_counter() - start) * 1000)
        return raw

    async def _ocr_pdf(self, content: bytes, config: dict[str, Any]) -> tuple[str, dict[str, Any], int]:
        import fitz

        document = fitz.open(stream=content, filetype="pdf")
        total_pages = len(document)
        if _is_unlimited_ocr_config(config):
            # 长 PDF 按批处理，避免单请求塞入过多图片导致 token/超时问题
            batch_size = 10
            texts: list[str] = []
            raw_pages: list[dict[str, Any]] = []
            for batch_start in range(0, total_pages, batch_size):
                images: list[dict[str, Any]] = []
                for page_index in range(batch_start, min(total_pages, batch_start + batch_size)):
                    page = document.load_page(page_index)
                    pix = page.get_pixmap(matrix=fitz.Matrix(300 / 72, 300 / 72), alpha=False)
                    data_url = f"data:image/png;base64,{base64.b64encode(pix.tobytes('png')).decode('ascii')}"
                    images.append({"type": "image_url", "image_url": {"url": data_url}})
                raw = await self._ocr_chat_completion(images, config, multi_page=len(images) > 1)
                batch_text = _clean_unlimited_ocr_text(_extract_chat_content(raw))
                texts.append(batch_text)
                raw_pages.append({
                    "startPage": batch_start + 1,
                    "endPage": min(total_pages, batch_start + batch_size),
                    "response": raw,
                })
            return "\n".join(texts), {"pages": raw_pages}, total_pages

        texts = []
        raw_pages = []
        for page_index in range(total_pages):
            page = document.load_page(page_index)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            text, raw = await self._ocr_image(pix.tobytes("png"), "image/png", config)
            texts.append(text)
            raw_pages.append({"pageNumber": page_index + 1, "response": raw})
        return "\n".join(texts), {"pages": raw_pages}, total_pages

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
        audit_metadata: dict[str, Any] | None = None,
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
            metadata={
                **(audit_metadata or {}),
                "candidateId": candidate_id,
                "taskId": str(after.get("taskId") or before.get("taskId") or ""),
                "fieldName": str(after.get("fieldName") or before.get("fieldName") or ""),
                "ocrAction": action,
            },
        )
        return {"message": "OCR 候选字段已处理", "item": after}

    def _write_candidate_to_project(self, project_id: str, candidate: OcrCandidate) -> None:
        project = require_any_workspace_project_for_update(project_id, not_found_error=_ocr_project_not_found)
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
        from app.services.bid_runtime_state import now_iso

        project["updatedAt"] = now_iso()
        persist_workspace_project_state(project)


ocr_service = OcrService()
