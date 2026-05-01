from __future__ import annotations

import copy
import itertools
import json
import re
from contextlib import closing
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.core.config import settings
from app.services.identity import build_project_identity


STAGE_NAMES = {
    1: "S1 模板上传",
    2: "S2 目录生成",
    3: "S3 目录审核",
    4: "S4 缺口识别",
    5: "S5 备料",
    6: "S6 审核备料",
    7: "S7 填充",
    8: "S8 校验",
    9: "S9 共创",
    10: "S10 导出",
}

STAGE_PROGRESS_NAMES = {
    1: "模板上传",
    2: "目录",
    3: "审核目录",
    4: "缺口识别",
    5: "备料",
    6: "审核备料",
    7: "填充",
    8: "校验",
    9: "共创",
    10: "导出",
}

REVIEW_DECISION_LABELS = {
    "pending": "待审核",
    "participate": "参与投标",
    "abandon": "不参与",
}


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_outline_nodes(project_name: str) -> list[dict[str, Any]]:
    return [
        {
            "id": "OL-1",
            "title": "项目概况",
            "children": [
                {"id": "OL-1-1", "title": "项目背景", "children": []},
                {"id": "OL-1-2", "title": "建设目标", "children": []},
            ],
        },
        {
            "id": "OL-2",
            "title": "技术方案",
            "children": [
                {"id": "OL-2-1", "title": f"{project_name}总体方案", "children": []},
            ],
        },
        {
            "id": "OL-3",
            "title": "实施与保障",
            "children": [],
        },
    ]


def build_directory_event(
    message: str,
    *,
    level: str = "info",
    step: str = "general",
    at: str | None = None,
) -> dict[str, Any]:
    return {
        "at": at or now_iso(),
        "level": level,
        "step": step,
        "message": message,
    }


def build_directory_opencode_output(
    *,
    status: str = "idle",
    session_id: str = "",
    provider_id: str = "",
    model_id: str = "",
    received_at: str = "",
    parts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "sessionId": session_id,
        "providerId": provider_id,
        "modelId": model_id,
        "receivedAt": received_at,
        "parts": copy.deepcopy(parts or []),
    }


def default_fill_tasks() -> list[dict[str, Any]]:
    return [
        {"id": "task-1", "label": "准备 S2 目录、Wiki 与素材库", "status": "pending"},
        {"id": "task-2", "label": "调用技术标正文拼装 skill", "status": "pending"},
        {"id": "task-3", "label": "写入 Word 正文", "status": "pending"},
    ]


class AppStore:
    def __init__(self, storage_backend: str | None = None) -> None:
        settings.ensure_dirs()
        self._storage_backend = (storage_backend or settings.project_store_backend or "postgres").strip().lower()
        self._projects: dict[str, dict[str, Any]] = {}
        self._ensure_db()
        self._load_projects()
        self._counter = itertools.count(self._next_project_number())

    @staticmethod
    def _parse_project_number(project_id: str) -> int:
        match = re.fullmatch(r"PRJ-(\d{4,})", project_id)
        if not match:
            return 0
        return int(match.group(1))

    def _next_project_number(self) -> int:
        max_id = max((self._parse_project_number(project_id) for project_id in self._projects), default=0)
        return max_id + 1

    @staticmethod
    def _postgres_dsn() -> str:
        return settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1).replace(
            "postgresql+psycopg://",
            "postgresql://",
            1,
        )

    @property
    def _uses_postgres(self) -> bool:
        return self._storage_backend == "postgres"

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self._postgres_dsn(), row_factory=dict_row)

    def _ensure_db(self) -> None:
        if not self._uses_postgres:
            return
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id VARCHAR(50) PRIMARY KEY,
                    payload JSONB NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.commit()

    def _load_projects(self) -> None:
        if not self._uses_postgres:
            return
        self._ensure_db()
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT id, payload FROM projects").fetchall()
        self._projects = {
            str(row["id"]): self._normalize_project_identity(
                row["payload"] if isinstance(row["payload"], dict) else json.loads(str(row["payload"]))
            )
            for row in rows
        }

    def _load_project(self, project_id: str) -> dict[str, Any] | None:
        if not self._uses_postgres:
            return self._projects.get(project_id)
        self._ensure_db()
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT id, payload FROM projects WHERE id = %s", (project_id,)).fetchone()
        if row is None:
            self._projects.pop(project_id, None)
            return None
        payload = row["payload"] if isinstance(row["payload"], dict) else json.loads(str(row["payload"]))
        project = self._normalize_project_identity(payload)
        self._projects[project_id] = project
        return project

    def _persist_project(self, project: dict[str, Any]) -> None:
        if not self._uses_postgres:
            return
        self._ensure_db()
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO projects (id, payload, updated_at)
                VALUES (%s, %s, %s)
                ON CONFLICT(id) DO UPDATE SET
                    payload=excluded.payload,
                    updated_at=excluded.updated_at
                """,
                (project["id"], Jsonb(project), project["updatedAt"]),
            )
            connection.commit()

    def _delete_project_record(self, project_id: str) -> None:
        if not self._uses_postgres:
            return
        self._ensure_db()
        with closing(self._connect()) as connection:
            connection.execute("DELETE FROM projects WHERE id = %s", (project_id,))
            connection.commit()

    def reset_for_tests(self, *, clear_persistent: bool = False) -> None:
        self._projects = {}
        if clear_persistent and self._uses_postgres:
            self._ensure_db()
            with closing(self._connect()) as connection:
                connection.execute("DELETE FROM projects")
                connection.commit()
        self._counter = itertools.count(1)

    @staticmethod
    def _normalize_project_identity(project: dict[str, Any]) -> dict[str, Any]:
        project_id = str(project.get("id") or "")
        project["projectCode"] = str(project.get("projectCode") or project_id)
        identity = build_project_identity(project)
        project["identity"] = identity
        project["customerId"] = identity.get("customerId") or ""
        project["customerCanonicalName"] = identity.get("customerCanonicalName") or ""
        project["materialCustomerId"] = identity.get("customerId") or ""
        project["materialCustomerName"] = identity.get("customerCanonicalName") or ""
        project["materialProjectId"] = identity.get("projectId") or ""
        project["materialProjectCode"] = identity.get("projectCode") or ""
        project["materialProjectName"] = identity.get("projectName") or ""
        project["materialProjectMode"] = identity.get("materialProjectMode") or project.get("materialProjectMode") or ""
        return project

    @staticmethod
    def format_size(size_bytes: int) -> str:
        if size_bytes <= 0:
            return "0 MB"
        return f"{size_bytes / 1024 / 1024:.1f} MB"

    @staticmethod
    def _source_file_type(file_name: str) -> str:
        lowered = str(file_name or "").lower()
        if lowered.endswith(".pdf"):
            return "PDF"
        if lowered.endswith(".md"):
            return "MD"
        if lowered.endswith((".doc", ".docx")):
            return "DOCX"
        return "文件"

    def _require(self, project_id: str) -> dict[str, Any]:
        project = self._load_project(project_id) or self._projects.get(project_id)
        if not project:
            raise KeyError(project_id)
        return project

    def _summary(self, project: dict[str, Any]) -> dict[str, Any]:
        project = self._normalize_project_identity(project)
        identity = project.get("identity") or {}
        review_decision = str(project.get("reviewDecision") or "participate")
        if review_decision not in REVIEW_DECISION_LABELS:
            review_decision = "pending"
        stage_label = "审核终止" if review_decision == "abandon" else STAGE_NAMES[project["currentStage"]]
        return {
            "id": project["id"],
            "projectCode": project.get("projectCode") or project["id"],
            "name": project["name"],
            "customerName": project["customerName"],
            "customerId": identity.get("customerId") or "",
            "customerCanonicalName": identity.get("customerCanonicalName") or "",
            "customerAliases": copy.deepcopy(identity.get("customerAliases") or []),
            "materialCustomerId": project.get("materialCustomerId") or identity.get("customerId") or "",
            "materialCustomerName": project.get("materialCustomerName") or identity.get("customerCanonicalName") or "",
            "materialProjectId": project.get("materialProjectId") or identity.get("projectId") or "",
            "materialProjectCode": project.get("materialProjectCode") or identity.get("projectCode") or "",
            "materialProjectName": project.get("materialProjectName") or identity.get("projectName") or "",
            "materialProjectMode": project.get("materialProjectMode") or identity.get("materialProjectMode") or "",
            "owner": project["owner"],
            "manager": project["manager"],
            "deadline": project["deadline"],
            "bidType": project["bidType"],
            "currentStage": project["currentStage"],
            "stageLabel": stage_label,
            "reviewDecision": review_decision,
            "reviewDecisionLabel": REVIEW_DECISION_LABELS[review_decision],
            "reviewDecidedAt": project.get("reviewDecidedAt") or "",
            "updatedAt": project["updatedAt"],
            "identity": copy.deepcopy(identity),
        }

    def _detail(self, project: dict[str, Any]) -> dict[str, Any]:
        return {
            **self._summary(project),
            "files": copy.deepcopy(project["files"]),
            "templateFiles": copy.deepcopy(project["templateFiles"]),
            "templateFallback": copy.deepcopy(self._normalize_template_fallback(project)),
            "isKeyAccount": project["isKeyAccount"],
            "keyAccountId": project["keyAccountId"],
            "reviewComment": str(project.get("reviewComment") or ""),
        }

    @staticmethod
    def _normalize_template_fallback(project: dict[str, Any]) -> dict[str, Any]:
        raw = project.get("templateFallback")
        fallback = raw if isinstance(raw, dict) else {}
        enabled = fallback.get("enabled")
        if enabled is None:
            enabled = True
        return {
            "enabled": bool(enabled),
            "sourceId": str(fallback.get("sourceId") or "system-default"),
        }

    def list_projects(
        self,
        status: str = "",
        bid_type: str = "",
        date_range: str = "",
        page: int = 1,
        page_size: int = 12,
    ) -> dict[str, Any]:
        self._load_projects()
        items = [self._summary(project) for project in self._projects.values()]
        normalized_bid_type = str(bid_type or "").strip()
        if normalized_bid_type:
            items = [item for item in items if str(item.get("bidType") or "").strip() == normalized_bid_type]
        items.sort(key=lambda item: item["updatedAt"], reverse=True)
        start = max(0, (page - 1) * page_size)
        end = start + page_size
        return {
            "items": items[start:end],
            "total": len(items),
            "page": page,
            "pageSize": page_size,
        }

    def create_project(self, data: dict[str, Any]) -> dict[str, Any]:
        project_id = f"PRJ-{next(self._counter):04d}"
        review_decision = str(data.get("reviewDecision") or "pending").strip().lower()
        if review_decision not in REVIEW_DECISION_LABELS:
            review_decision = "pending"
        project = {
            "id": project_id,
            "projectCode": str(data.get("projectCode") or project_id),
            "name": str(data.get("name") or project_id),
            "customerName": str(data.get("customerName") or ""),
            "customerId": str(data.get("customerId") or ""),
            "customerCanonicalName": str(data.get("customerCanonicalName") or ""),
            "materialCustomerId": str(data.get("materialCustomerId") or data.get("customerId") or ""),
            "materialCustomerName": str(data.get("materialCustomerName") or data.get("customerCanonicalName") or data.get("customerName") or ""),
            "materialProjectMode": str(data.get("materialProjectMode") or ""),
            "materialProjectId": str(data.get("materialProjectId") or ""),
            "materialProjectCode": str(data.get("materialProjectCode") or ""),
            "materialProjectName": str(data.get("materialProjectName") or data.get("name") or ""),
            "owner": str(data.get("owner") or data.get("customerName") or ""),
            "manager": str(data.get("manager") or ""),
            "deadline": str(data.get("deadline") or ""),
            "bidType": str(data.get("bidType") or "技术标"),
            "isKeyAccount": bool(data.get("isKeyAccount")),
            "keyAccountId": str(data.get("keyAccountId") or ""),
            "reviewDecision": review_decision,
            "reviewDecidedAt": now_iso() if review_decision in {"participate", "abandon"} else "",
            "reviewComment": str(data.get("reviewComment") or ""),
            "files": [],
            "templateFiles": [],
            "fileRecords": [],
            "templateFileRecords": [],
            "templateFallback": {
                "enabled": True,
                "sourceId": "system-default",
            },
            "currentStage": 1,
            "updatedAt": now_iso(),
            "parse_result": {
                "status": "idle",
                "parsedAt": "",
                "sourceFiles": [],
                "items": [],
                "summary": {
                    "fileCount": 0,
                    "extractedCount": 0,
                    "textLength": 0,
                    "textPreview": "",
                    "warnings": [],
                },
            },
            "parse_storage": {
                "projectDir": "",
                "combinedTextPath": "",
                "manifestPath": "",
                "documents": [],
            },
            "directory_state": {
                "status": "idle",
                "percentage": 0,
                "summary": "尚未生成目录。",
                "generatedAt": "",
                "output": None,
                "opencodeOutput": build_directory_opencode_output(),
                "events": [],
                "tasks": [
                    {"id": "task-1", "label": "解析章节线索", "status": "pending"},
                    {"id": "task-2", "label": "调用目录生成 skill", "status": "pending"},
                    {"id": "task-3", "label": "保存目录结果", "status": "pending"},
                ],
            },
            "outline_state": {
                "outlineVersion": 1,
                "reviewStatus": "draft",
                "generatedAt": "",
                "summary": {"totalNodeCount": 0},
                "nodes": [],
            },
            "fill_state": {
                "status": "idle",
                "percentage": 0,
                "filledAt": "",
                "runDurationSec": 0,
                "runDuration": "",
                "summary": "尚未触发填充，请点击“触发填充”后继续。",
                "output": None,
                "sections": [],
                "opencodeOutput": build_directory_opencode_output(),
                "events": [],
                "tasks": default_fill_tasks(),
            },
            "document_state": {
                "status": "ready",
                "documentId": f"DOC-{project_id}",
                "sourceFileName": f"{str(data.get('name') or project_id)}_正文.docx",
                "fileName": f"{str(data.get('name') or project_id)}_正文.docx",
                "fileType": "docx",
                "version": 1,
                "lastSavedAt": "",
                "onlyoffice": {
                    "documentKey": f"{project_id}-v1",
                    "title": f"{str(data.get('name') or project_id)}_正文.docx",
                    "user": {"id": "user-1", "name": "当前用户"},
                },
                "fallback": {
                    "content": "OnlyOffice 未接入前，这里先展示后端生成的占位文档内容。",
                },
            },
            "gap_state": {
                "recognitionStatus": "idle",
                "recognizedAt": "",
                "submittedForReview": False,
                "reviewConfirmed": False,
                "reviewedAt": "",
                "items": [],
                "submissions": [],
            },
            "review_document_state": {
                "parseStatus": "idle",
                "parsedAt": "",
                "documentId": f"REV-DOC-{project_id}",
                "sourceFileName": "",
                "fileName": f"{str(data.get('name') or project_id)}_S6审核备料预览.docx",
                "fileType": "docx",
                "content": "",
                "lastSavedAt": "",
                "version": 1,
                "documentKey": f"{project_id}-s6-v1",
            },
        }
        self._normalize_project_identity(project)
        self._projects[project_id] = project
        self._persist_project(project)
        return self._detail(project)

    def get_project(self, project_id: str) -> dict[str, Any]:
        return self._detail(self._require(project_id))

    def update_project(self, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
        project = self._require(project_id)
        for field in [
            "name",
            "projectCode",
            "customerName",
            "customerId",
            "customerCanonicalName",
            "materialCustomerId",
            "materialCustomerName",
            "materialProjectMode",
            "materialProjectId",
            "materialProjectCode",
            "materialProjectName",
            "owner",
            "manager",
            "deadline",
            "bidType",
        ]:
            if field in data:
                project[field] = str(data[field] or "") if field == "projectCode" else data[field]
        if "reviewDecision" in data:
            decision = str(data.get("reviewDecision") or "").strip().lower()
            if decision not in REVIEW_DECISION_LABELS:
                decision = "pending"
            project["reviewDecision"] = decision
            project["reviewDecidedAt"] = now_iso() if decision in {"participate", "abandon"} else ""
        if "reviewComment" in data:
            project["reviewComment"] = str(data.get("reviewComment") or "")
        self._normalize_project_identity(project)
        project["updatedAt"] = now_iso()
        self._persist_project(project)
        return self._detail(project)

    def delete_project(self, project_id: str) -> None:
        if project_id not in self._projects:
            raise KeyError(project_id)
        del self._projects[project_id]
        self._delete_project_record(project_id)

    def get_stages(self, project_id: str) -> list[dict[str, Any]]:
        project = self._require(project_id)
        stages: list[dict[str, Any]] = []
        for stage_id in range(1, 11):
            if stage_id < project["currentStage"]:
                status = "completed"
            elif stage_id == project["currentStage"]:
                status = "active"
            else:
                status = "pending"
            stages.append(
                {
                    "id": stage_id,
                    "name": STAGE_PROGRESS_NAMES[stage_id],
                    "status": status,
                    "isHuman": stage_id in {3, 5, 6, 9},
                }
            )
        return stages

    def update_stage(self, project_id: str, stage: int, data: dict[str, Any]) -> dict[str, Any]:
        project = self._require(project_id)
        status = str(data.get("status") or "").strip()
        if status == "completed":
            project["currentStage"] = min(10, max(project["currentStage"], stage + 1))
        elif status == "active":
            project["currentStage"] = max(1, min(10, stage))
        project["updatedAt"] = now_iso()
        self._persist_project(project)
        return {
            "message": "阶段状态已更新",
            "currentStage": project["currentStage"],
            "stageLabel": STAGE_NAMES[project["currentStage"]],
        }

    def complete_parse(
        self,
        project_id: str,
        tender_files: list[dict[str, Any]],
        template_files: list[dict[str, Any]],
        summary: dict[str, Any] | None = None,
        parse_storage: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project = self._require(project_id)
        parsed_at = now_iso()
        project["files"] = [item["name"] for item in tender_files]
        project["fileRecords"] = copy.deepcopy(tender_files)
        project["templateFileRecords"] = copy.deepcopy(template_files)
        project["templateFiles"] = [
            {
                "id": item["id"],
                "name": item["name"],
                "sizeLabel": item["size_label"],
            }
            for item in template_files
        ]
        source_files = [
            {
                "id": item["id"].replace("TEN", "SRC"),
                "name": item["name"],
                "type": self._source_file_type(item["name"]),
                "pageCount": 12,
                "size": item["size_label"],
            }
            for item in tender_files
        ]
        items: list[dict[str, Any]] = []
        source_file_lookup = {item["name"]: item for item in source_files}
        if summary and parse_storage:
            for document in parse_storage.get("documents", []):
                if source_file_lookup.get(document["name"]):
                    source_file_lookup[document["name"]]["pageCount"] = document.get("pageCount", "-")
                    source_file_lookup[document["name"]]["textLength"] = document.get("textLength", 0)
        project["parse_result"] = {
            "status": "completed",
            "parsedAt": parsed_at,
            "project": {
                "id": project["id"],
                "files": copy.deepcopy(project["files"]),
                "templateFiles": copy.deepcopy(project["templateFiles"]),
                "currentStage": project["currentStage"],
                "stageLabel": STAGE_NAMES[project["currentStage"]],
            },
            "sourceFiles": source_files,
            "items": items,
            "summary": summary or {
                "fileCount": len(source_files),
                "extractedCount": len(items),
                "textLength": 0,
                "textPreview": "",
                "warnings": [],
            },
        }
        project["parse_storage"] = copy.deepcopy(parse_storage or project.get("parse_storage") or {})
        project["updatedAt"] = parsed_at
        self._persist_project(project)
        return copy.deepcopy(project["parse_result"])

    def get_parse_result(self, project_id: str) -> dict[str, Any]:
        return copy.deepcopy(self._require(project_id)["parse_result"])

    def get_parse_storage(self, project_id: str) -> dict[str, Any]:
        return copy.deepcopy(self._require(project_id)["parse_storage"])

    def get_parse_inputs(
        self,
        project_id: str,
        *,
        include_fallback: bool = True,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        project = self._require(project_id)
        template_file_records = copy.deepcopy(project.get("templateFileRecords") or [])
        if include_fallback and not template_file_records and self._normalize_template_fallback(project)["enabled"]:
            from app.services import template_store as template_store_module

            fallback_record = template_store_module.resolve_fallback_bid_template_file(project_id)
            if fallback_record is not None:
                template_file_records = [fallback_record]
        return (
            copy.deepcopy(project.get("fileRecords") or []),
            template_file_records,
        )

    def get_template_fallback(self, project_id: str) -> dict[str, Any]:
        project = self._require(project_id)
        from app.services.template_store import fallback_bid_template_summary

        return {
            "projectId": project_id,
            "enabled": self._normalize_template_fallback(project)["enabled"],
            "sourceId": self._normalize_template_fallback(project)["sourceId"],
            "template": fallback_bid_template_summary(check_exists=True),
            "usesFallbackWhenProjectTemplateMissing": not bool(project.get("templateFileRecords")),
        }

    def update_template_fallback(self, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
        project = self._require(project_id)
        current = self._normalize_template_fallback(project)
        if "enabled" in data:
            current["enabled"] = bool(data.get("enabled"))
        if "sourceId" in data:
            current["sourceId"] = str(data.get("sourceId") or "system-default")
        project["templateFallback"] = current
        project["updatedAt"] = now_iso()
        self._persist_project(project)
        return self.get_template_fallback(project_id)

    def update_template_files(self, project_id: str, template_files: list[dict[str, Any]]) -> dict[str, Any]:
        project = self._require(project_id)
        project["templateFileRecords"] = copy.deepcopy(template_files)
        project["templateFiles"] = [
            {
                "id": item["id"],
                "name": item["name"],
                "sizeLabel": item["size_label"],
            }
            for item in template_files
        ]
        parse_result = project.get("parse_result") or {}
        if isinstance(parse_result, dict):
            parse_project = parse_result.get("project") or {}
            parse_project["id"] = project["id"]
            parse_project["templateFiles"] = copy.deepcopy(project["templateFiles"])
            parse_result["project"] = parse_project
            project["parse_result"] = parse_result
        project["updatedAt"] = now_iso()
        self._persist_project(project)
        return {
            "project": {
                "id": project["id"],
                "templateFiles": copy.deepcopy(project["templateFiles"]),
                "currentStage": project["currentStage"],
                "stageLabel": STAGE_NAMES[project["currentStage"]],
            },
            "templateFiles": copy.deepcopy(project["templateFiles"]),
            "updatedAt": project["updatedAt"],
        }

    def complete_directory_generation(self, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
        project = self._require(project_id)
        generated_at = now_iso()
        nodes = default_outline_nodes(project["name"])
        payload = {
            "status": "completed",
            "percentage": 100,
            "summary": "目录生成完成。",
            "generatedAt": generated_at,
            "output": {
                "fileName": f"{project['name']}_目录.docx",
                "fileType": "docx",
                "chapterCount": len(nodes),
            },
            "opencodeOutput": build_directory_opencode_output(),
            "events": [
                build_directory_event("目录生成完成。", level="success", step="done", at=generated_at),
            ],
            "tasks": [
                {"id": "task-1", "label": "解析章节线索", "status": "done"},
                {"id": "task-2", "label": "调用目录生成 skill", "status": "done"},
                {"id": "task-3", "label": "保存目录结果", "status": "done"},
            ],
        }
        project["directory_state"] = payload
        project["outline_state"] = {
            "outlineVersion": 1,
            "reviewStatus": "draft",
            "generatedAt": generated_at,
            "summary": {"totalNodeCount": self._count_nodes(nodes)},
            "nodes": nodes,
        }
        project["updatedAt"] = generated_at
        self._persist_project(project)
        return copy.deepcopy(payload)

    def start_directory_generation(self, project_id: str) -> dict[str, Any]:
        project = self._require(project_id)
        payload = {
            "status": "running",
            "percentage": 5,
            "summary": "已开始生成目录，正在准备招标文本与模板线索。",
            "generatedAt": "",
            "output": None,
            "opencodeOutput": build_directory_opencode_output(),
            "events": [
                build_directory_event(
                    "已开始生成目录任务，正在准备招标文本与模板线索。",
                    step="bootstrap",
                ),
            ],
            "tasks": [
                {"id": "task-1", "label": "解析章节线索", "status": "running"},
                {"id": "task-2", "label": "调用目录生成 skill", "status": "pending"},
                {"id": "task-3", "label": "保存目录结果", "status": "pending"},
            ],
        }
        project["directory_state"] = payload
        project["updatedAt"] = now_iso()
        self._persist_project(project)
        return copy.deepcopy(payload)

    def update_directory_generation_state(
        self,
        project_id: str,
        *,
        percentage: int | None = None,
        summary: str | None = None,
        tasks: list[dict[str, Any]] | None = None,
        status: str | None = None,
        event_message: str | None = None,
        event_level: str = "info",
        event_step: str = "general",
        opencode_output: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project = self._require(project_id)
        current = copy.deepcopy(project["directory_state"])
        if percentage is not None:
            current["percentage"] = max(0, min(100, int(percentage)))
        if summary is not None:
            current["summary"] = summary
        if tasks is not None:
            current["tasks"] = copy.deepcopy(tasks)
        if status is not None:
            current["status"] = status
        if opencode_output is not None:
            merged_output = build_directory_opencode_output()
            merged_output.update(copy.deepcopy(current.get("opencodeOutput") or {}))
            merged_output.update(copy.deepcopy(opencode_output))
            merged_output["parts"] = copy.deepcopy(merged_output.get("parts") or [])[-20:]
            current["opencodeOutput"] = merged_output
        if event_message:
            events = list(current.get("events") or [])
            events.append(
                build_directory_event(
                    event_message,
                    level=event_level,
                    step=event_step,
                )
            )
            current["events"] = events[-20:]
        project["directory_state"] = current
        project["updatedAt"] = now_iso()
        self._persist_project(project)
        return copy.deepcopy(current)

    def fail_directory_generation(
        self,
        project_id: str,
        message: str,
        tasks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        project = self._require(project_id)
        current = copy.deepcopy(project["directory_state"])
        current["status"] = "failed"
        current["summary"] = message
        current_output = build_directory_opencode_output()
        current_output.update(copy.deepcopy(current.get("opencodeOutput") or {}))
        if (
            current_output.get("status") != "idle"
            or current_output.get("sessionId")
            or current_output.get("providerId")
            or current_output.get("modelId")
            or current_output.get("parts")
        ):
            current_output["status"] = "failed"
        current["opencodeOutput"] = current_output
        if tasks is not None:
            current["tasks"] = copy.deepcopy(tasks)
        events = list(current.get("events") or [])
        events.append(build_directory_event(message, level="error", step="failed"))
        current["events"] = events[-20:]
        project["directory_state"] = current
        project["updatedAt"] = now_iso()
        self._persist_project(project)
        return copy.deepcopy(current)

    def save_generated_outline(
        self,
        project_id: str,
        nodes: list[dict[str, Any]],
        generated_at: str,
        summary: str,
        opencode_output: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project = self._require(project_id)
        current_state = copy.deepcopy(project.get("directory_state") or {})
        current_events = list(copy.deepcopy(current_state.get("events") or []))
        current_output = build_directory_opencode_output()
        current_output.update(copy.deepcopy(current_state.get("opencodeOutput") or {}))
        if opencode_output is not None:
            current_output.update(copy.deepcopy(opencode_output))
        current_output["parts"] = copy.deepcopy(current_output.get("parts") or [])[-20:]
        current_events.append(
            build_directory_event(
                f"目录生成完成，已输出 {len(nodes)} 个一级章节。",
                level="success",
                step="done",
                at=generated_at,
            )
        )
        payload = {
            "status": "completed",
            "percentage": 100,
            "summary": summary,
            "generatedAt": generated_at,
            "output": {
                "fileName": f"{project['name']}_目录.docx",
                "fileType": "docx",
                "chapterCount": len(nodes),
            },
            "opencodeOutput": current_output,
            "events": current_events[-20:],
            "tasks": [
                {"id": "task-1", "label": "解析章节线索", "status": "done"},
                {"id": "task-2", "label": "调用目录生成 skill", "status": "done"},
                {"id": "task-3", "label": "保存目录结果", "status": "done"},
            ],
        }
        project["directory_state"] = payload
        project["outline_state"] = {
            "outlineVersion": int(project["outline_state"].get("outlineVersion") or 0) + 1,
            "reviewStatus": "draft",
            "generatedAt": generated_at,
            "summary": {"totalNodeCount": self._count_nodes(nodes)},
            "nodes": copy.deepcopy(nodes),
        }
        project["updatedAt"] = generated_at
        self._persist_project(project)
        return copy.deepcopy(payload)

    def get_directory_state(self, project_id: str) -> dict[str, Any]:
        return copy.deepcopy(self._require(project_id)["directory_state"])

    def get_outline_state(self, project_id: str) -> dict[str, Any]:
        return copy.deepcopy(self._require(project_id)["outline_state"])

    def save_outline(self, project_id: str, nodes: list[dict[str, Any]]) -> dict[str, Any]:
        project = self._require(project_id)
        current = copy.deepcopy(project["outline_state"])
        current["outlineVersion"] = int(current.get("outlineVersion") or 1) + 1
        current["reviewStatus"] = "draft"
        current["summary"] = {"totalNodeCount": self._count_nodes(nodes)}
        current["nodes"] = copy.deepcopy(nodes)
        project["outline_state"] = current
        project["updatedAt"] = now_iso()
        self._persist_project(project)
        return copy.deepcopy(current)

    def regenerate_outline(self, project_id: str) -> dict[str, Any]:
        project = self._require(project_id)
        nodes = default_outline_nodes(project["name"])
        project["outline_state"] = {
            "outlineVersion": int(project["outline_state"].get("outlineVersion") or 1) + 1,
            "reviewStatus": "draft",
            "generatedAt": now_iso(),
            "summary": {"totalNodeCount": self._count_nodes(nodes)},
            "nodes": nodes,
        }
        project["updatedAt"] = now_iso()
        self._persist_project(project)
        return copy.deepcopy(project["outline_state"])

    def confirm_outline(self, project_id: str) -> dict[str, Any]:
        project = self._require(project_id)
        project["outline_state"]["reviewStatus"] = "confirmed"
        project["updatedAt"] = now_iso()
        self._persist_project(project)
        return {
            "message": "目录已确认",
            "outlineVersion": project["outline_state"]["outlineVersion"],
            "reviewStatus": "confirmed",
        }

    def get_gap_detection(self, project_id: str) -> dict[str, Any]:
        project = self._require(project_id)
        gap_state = self._ensure_gap_state(project)
        return self._build_gap_detection_payload(project, gap_state)

    def run_gap_detection(self, project_id: str) -> dict[str, Any]:
        project = self._require(project_id)
        gap_state = self._ensure_gap_state(project)
        items = self._build_gap_items_from_outline(project)
        gap_state.update(
            {
                "recognitionStatus": "completed",
                "recognizedAt": now_iso(),
                "submittedForReview": False,
                "reviewConfirmed": False,
                "reviewedAt": "",
                "items": items,
                "submissions": [],
            }
        )
        project["review_document_state"] = self._default_review_document_state(project)
        project["updatedAt"] = now_iso()
        self._persist_project(project)
        return self._build_gap_detection_payload(project, gap_state)

    def get_gap_filling(self, project_id: str) -> dict[str, Any]:
        project = self._require(project_id)
        gap_state = self._ensure_gap_state(project)
        if gap_state["recognitionStatus"] != "completed":
            raise ValueError("请先在 S4 触发缺口识别后再进入 S5。")
        return {
            "status": "ready",
            "recognizedAt": gap_state["recognizedAt"],
            "submittedForReview": bool(gap_state["submittedForReview"]),
            "items": copy.deepcopy(gap_state["items"]),
            "submissions": copy.deepcopy(gap_state["submissions"]),
        }

    def list_gap_submissions(self, project_id: str) -> dict[str, Any]:
        project = self._require(project_id)
        gap_state = self._ensure_gap_state(project)
        submissions = copy.deepcopy(gap_state["submissions"])
        return {"items": submissions, "total": len(submissions)}

    def submit_gap_material(self, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
        project = self._require(project_id)
        gap_state = self._ensure_gap_state(project)
        if gap_state["recognitionStatus"] != "completed":
            raise ValueError("请先在 S4 完成缺口识别。")

        missing_id = str(data.get("missingId") or "").strip()
        files = list(data.get("files") or [])
        if not missing_id:
            raise ValueError("missingId 不能为空。")
        if not files:
            raise ValueError("至少需要提交一个文件。")

        item = self._find_gap_item(gap_state, missing_id)
        receipts: list[dict[str, Any]] = []
        timestamp = now_iso()
        for index, file in enumerate(files, start=1):
            file_name = str(file.get("name") or f"{missing_id}-{index}.docx").strip() or f"{missing_id}-{index}.docx"
            receipt = {
                "receiptId": f"mr-{project_id}-{len(gap_state['submissions']) + index}",
                "projectId": project_id,
                "missingId": missing_id,
                "fileId": f"raw-{project_id}-{len(gap_state['submissions']) + index}",
                "fileName": file_name,
                "storedPath": f"项目素材/{project_id}/{str(data.get('bidType') or item.get('bidType') or '技术标')}",
                "action": "upload",
                "operator": str(data.get('operator') or "当前用户"),
                "submittedAt": timestamp,
                "traceId": f"mock-{project_id}-{len(gap_state['submissions']) + index}",
                "auditId": f"audit-{project_id}-{len(gap_state['submissions']) + index}",
            }
            receipts.append(receipt)

        gap_state["submissions"] = receipts + list(gap_state["submissions"])
        item["latestUploadAt"] = timestamp
        item["latestSubmissionId"] = receipts[0]["receiptId"]
        if item["status"] != "resolved":
            item["status"] = "checking"
        gap_state["submittedForReview"] = False
        gap_state["reviewConfirmed"] = False
        gap_state["reviewedAt"] = ""
        project["review_document_state"] = self._default_review_document_state(project)
        project["updatedAt"] = timestamp
        self._persist_project(project)
        return {
            "message": f"补料提交成功，共 {len(receipts)} 个文件。",
            "item": copy.deepcopy(item),
            "receipts": receipts,
            "payload": self.get_gap_filling(project_id),
            "traceId": receipts[0]["traceId"],
        }

    def update_gap_item(self, project_id: str, gap_id: str, data: dict[str, Any]) -> dict[str, Any]:
        project = self._require(project_id)
        gap_state = self._ensure_gap_state(project)
        if gap_state["recognitionStatus"] != "completed":
            raise ValueError("请先在 S4 完成缺口识别。")

        item = self._find_gap_item(gap_state, gap_id)
        action = str(data.get("action") or data.get("status") or "").strip()
        if action in {"skip", "skipped"}:
            item["status"] = "skipped"
            item["skipReason"] = str(data.get("reason") or item.get("skipReason") or "未填写原因")
            item["resolvedSource"] = ""
            item["resolvedAt"] = ""
        elif action in {"resolve", "resolved"}:
            source = data.get("source") or {}
            if isinstance(source, dict):
                source_name = str(source.get("name") or "")
            else:
                source_name = str(source)
            item["status"] = "resolved"
            item["resolvedSource"] = source_name.strip() or str(data.get("resolvedSource") or item.get("resolvedSource") or "已补录")
            item["skipReason"] = ""
            item["resolvedAt"] = now_iso()
        elif action in {"checking", "pending"}:
            item["status"] = action
        else:
            raise ValueError("不支持的缺口状态更新。")

        gap_state["submittedForReview"] = False
        gap_state["reviewConfirmed"] = False
        gap_state["reviewedAt"] = ""
        project["review_document_state"] = self._default_review_document_state(project)
        project["updatedAt"] = now_iso()
        self._persist_project(project)
        return {
            "message": "缺口状态已更新",
            "item": copy.deepcopy(item),
            "payload": self.get_gap_filling(project_id),
        }

    def patch_missing_material(self, project_id: str, missing_id: str, data: dict[str, Any]) -> dict[str, Any]:
        return self.update_gap_item(project_id, missing_id, data)

    def submit_gap_review(self, project_id: str) -> dict[str, Any]:
        project = self._require(project_id)
        gap_state = self._ensure_gap_state(project)
        if gap_state["recognitionStatus"] != "completed":
            raise ValueError("请先完成 S4 缺口识别后再提交审核。")

        pending = [item for item in gap_state["items"] if item["status"] not in {"resolved", "skipped"}]
        for item in pending:
            item["status"] = "skipped"
            item["skipReason"] = item.get("skipReason") or "MVP 阶段跳过 S5 备料，后续在素材库正式化后补齐。"
            item["resolvedSource"] = ""
            item["resolvedAt"] = ""

        gap_state["submittedForReview"] = True
        gap_state["reviewConfirmed"] = False
        gap_state["reviewedAt"] = ""
        project["updatedAt"] = now_iso()
        self._persist_project(project)
        return {
            "message": "S5 已跳过未处理缺口并提交审核。",
            "payload": self.get_gap_filling(project_id),
        }

    def get_review_items(self, project_id: str) -> dict[str, Any]:
        project = self._require(project_id)
        gap_state = self._ensure_gap_state(project)
        return self._build_review_payload(project, gap_state)

    def prepare_review_document(self, project_id: str) -> dict[str, Any]:
        project = self._require(project_id)
        gap_state = self._ensure_gap_state(project)
        if not gap_state["submittedForReview"]:
            raise ValueError("请先在 S5 提交审核后再触发 S6 解析。")

        pending = [item for item in gap_state["items"] if item["status"] not in {"resolved", "skipped"}]
        if pending:
            raise ValueError(f"仍有 {len(pending)} 项素材未处理，暂不可触发 S6 解析。")

        review_state = self._ensure_review_document_state(project)
        parsed_at = now_iso()
        review_state.update(
            {
                "parseStatus": "completed",
                "parsedAt": parsed_at,
                "sourceFileName": self._review_source_file_name(gap_state),
                "fileName": f"{project['name']}_S6审核备料预览.docx",
                "fileType": "docx",
                "content": self._build_review_document_content(project, gap_state),
                "lastSavedAt": parsed_at,
                "version": 1,
                "documentKey": f"{project_id}-s6-v1",
            }
        )
        project["updatedAt"] = parsed_at
        self._persist_project(project)
        return {
            "message": "S6 审核备料解析完成，可在 S6 预览解析文档。",
            "payload": copy.deepcopy(review_state),
        }

    def get_review_document_state(self, project_id: str) -> dict[str, Any]:
        project = self._require(project_id)
        return copy.deepcopy(self._ensure_review_document_state(project))

    def save_review_document_content(self, project_id: str, content: str) -> dict[str, Any]:
        project = self._require(project_id)
        review_state = self._ensure_review_document_state(project)
        next_version = int(review_state.get("version") or 1) + 1
        review_state.update(
            {
                "parseStatus": "completed",
                "content": content,
                "version": next_version,
                "lastSavedAt": now_iso(),
                "documentKey": f"{project_id}-s6-v{next_version}",
            }
        )
        project["updatedAt"] = review_state["lastSavedAt"]
        self._persist_project(project)
        return copy.deepcopy(review_state)

    def force_save_review_document(self, project_id: str) -> dict[str, Any]:
        project = self._require(project_id)
        review_state = self._ensure_review_document_state(project)
        next_version = int(review_state.get("version") or 1) + 1
        review_state.update(
            {
                "parseStatus": "completed",
                "version": next_version,
                "lastSavedAt": now_iso(),
                "documentKey": f"{project_id}-s6-v{next_version}",
            }
        )
        project["updatedAt"] = review_state["lastSavedAt"]
        self._persist_project(project)
        return copy.deepcopy(review_state)

    def confirm_review(self, project_id: str) -> dict[str, Any]:
        project = self._require(project_id)
        gap_state = self._ensure_gap_state(project)
        if not gap_state["submittedForReview"]:
            raise ValueError("请先在 S5 提交审核后再执行 S6 审核。")

        pending = [item for item in gap_state["items"] if item["status"] not in {"resolved", "skipped"}]
        if pending:
            raise ValueError(f"仍有 {len(pending)} 项素材未处理，暂不可确认审核。")

        gap_state["reviewConfirmed"] = True
        gap_state["reviewedAt"] = now_iso()
        project["updatedAt"] = gap_state["reviewedAt"]
        self._persist_project(project)
        return {
            "message": "S6 审核完成，已进入 S7 填充。",
            "reviewStatus": "confirmed",
            "payload": self._build_review_payload(project, gap_state),
        }

    def get_fill_state(self, project_id: str) -> dict[str, Any]:
        return copy.deepcopy(self._require(project_id)["fill_state"])

    def start_fill_generation(self, project_id: str) -> dict[str, Any]:
        project = self._require(project_id)
        payload = {
            "status": "running",
            "percentage": 5,
            "filledAt": "",
            "runDurationSec": 0,
            "runDuration": "",
            "summary": "已开始拼装技术标正文，正在准备 S2 目录、Wiki 与素材库。",
            "output": None,
            "sections": [],
            "opencodeOutput": build_directory_opencode_output(),
            "events": [
                build_directory_event(
                    "已开始技术标正文拼装任务，正在准备 S2 目录、Wiki 与素材库。",
                    step="bootstrap",
                ),
            ],
            "tasks": [
                {"id": "task-1", "label": "准备 S2 目录、Wiki 与素材库", "status": "running"},
                {"id": "task-2", "label": "调用技术标正文拼装 skill", "status": "pending"},
                {"id": "task-3", "label": "写入 Word 正文", "status": "pending"},
            ],
        }
        project["fill_state"] = payload
        project["updatedAt"] = now_iso()
        self._persist_project(project)
        return copy.deepcopy(payload)

    def update_fill_generation_state(
        self,
        project_id: str,
        *,
        percentage: int | None = None,
        summary: str | None = None,
        tasks: list[dict[str, Any]] | None = None,
        status: str | None = None,
        event_message: str | None = None,
        event_level: str = "info",
        event_step: str = "general",
        opencode_output: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project = self._require(project_id)
        current = copy.deepcopy(project["fill_state"])
        if percentage is not None:
            current["percentage"] = max(0, min(100, int(percentage)))
        if summary is not None:
            current["summary"] = summary
        if tasks is not None:
            current["tasks"] = copy.deepcopy(tasks)
        if status is not None:
            current["status"] = status
        if opencode_output is not None:
            merged_output = build_directory_opencode_output()
            merged_output.update(copy.deepcopy(current.get("opencodeOutput") or {}))
            merged_output.update(copy.deepcopy(opencode_output))
            merged_output["parts"] = copy.deepcopy(merged_output.get("parts") or [])[-20:]
            current["opencodeOutput"] = merged_output
        if event_message:
            events = list(current.get("events") or [])
            events.append(
                build_directory_event(
                    event_message,
                    level=event_level,
                    step=event_step,
                )
            )
            current["events"] = events[-20:]
        project["fill_state"] = current
        project["updatedAt"] = now_iso()
        self._persist_project(project)
        return copy.deepcopy(current)

    def fail_fill_generation(
        self,
        project_id: str,
        message: str,
        tasks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        project = self._require(project_id)
        current = copy.deepcopy(project["fill_state"])
        current["status"] = "failed"
        current["summary"] = message
        current_output = build_directory_opencode_output()
        current_output.update(copy.deepcopy(current.get("opencodeOutput") or {}))
        if (
            current_output.get("status") != "idle"
            or current_output.get("sessionId")
            or current_output.get("providerId")
            or current_output.get("modelId")
            or current_output.get("parts")
        ):
            current_output["status"] = "failed"
        current["opencodeOutput"] = current_output
        if tasks is not None:
            current["tasks"] = copy.deepcopy(tasks)
        events = list(current.get("events") or [])
        events.append(build_directory_event(message, level="error", step="failed"))
        current["events"] = events[-20:]
        project["fill_state"] = current
        project["updatedAt"] = now_iso()
        self._persist_project(project)
        return copy.deepcopy(current)

    def complete_fill_generation(self, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
        project = self._require(project_id)
        filled_at = now_iso()
        sections = [
            {
                "nodeId": "OL-1",
                "title": "项目概况",
                "generationMode": "generated",
                "evidenceRefs": [],
                "riskFlags": [],
            },
            {
                "nodeId": "OL-2",
                "title": "企业业绩",
                "generationMode": "placeholder",
                "evidenceRefs": [],
                "riskFlags": ["FACT_REQUIRED"],
            },
        ]
        project["fill_state"] = {
            "status": "completed",
            "percentage": 100,
            "filledAt": filled_at,
            "runDurationSec": 79,
            "runDuration": "1分19秒",
            "summary": "技术标正文拼装完成。",
            "output": {
                "fileName": f"{project['name']}_正文.docx",
                "fileType": "docx",
                "size": "2.8 MB",
                "fileUrl": f"/api/projects/{project_id}/document/file",
            },
            "sections": sections,
            "opencodeOutput": build_directory_opencode_output(),
            "events": [
                build_directory_event("技术标正文拼装完成。", level="success", step="done", at=filled_at),
            ],
            "tasks": [
                {"id": "task-1", "label": "准备 S2 目录、Wiki 与素材库", "status": "done"},
                {"id": "task-2", "label": "调用技术标正文拼装 skill", "status": "done"},
                {"id": "task-3", "label": "写入 Word 正文", "status": "done"},
            ],
        }
        project["document_state"]["sourceFileName"] = f"{project['name']}_正文.docx"
        project["document_state"]["fileName"] = f"{project['name']}_正文.docx"
        project["document_state"]["fallback"]["content"] = (
            f"# {project['name']}\n\n## 项目概况\n本稿为 MVP 占位正文。\n\n## 企业业绩\n【此处待补充真实业绩信息】"
        )
        project["updatedAt"] = filled_at
        self._persist_project(project)
        return copy.deepcopy(project["fill_state"])

    def save_fill_generation_result(
        self,
        project_id: str,
        *,
        summary: str,
        sections: list[dict[str, Any]],
        content: str,
        filled_at: str,
        run_duration_sec: int,
        file_size_bytes: int,
        opencode_output: dict[str, Any] | None = None,
        file_name: str | None = None,
        coverage: dict[str, Any] | None = None,
        assembly: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project = self._require(project_id)
        file_name = file_name or f"{project['name']}_正文.docx"
        current_state = copy.deepcopy(project.get("fill_state") or {})
        current_events = list(copy.deepcopy(current_state.get("events") or []))
        current_output = build_directory_opencode_output()
        current_output.update(copy.deepcopy(current_state.get("opencodeOutput") or {}))
        if opencode_output is not None:
            current_output.update(copy.deepcopy(opencode_output))
        current_output["parts"] = copy.deepcopy(current_output.get("parts") or [])[-20:]
        current_events.append(
            build_directory_event(
                f"技术标正文拼装完成，已输出 {len(sections)} 个目录章节。",
                level="success",
                step="done",
                at=filled_at,
            )
        )
        project["fill_state"] = {
            "status": "completed",
            "percentage": 100,
            "filledAt": filled_at,
            "runDurationSec": int(run_duration_sec),
            "runDuration": self._format_duration(run_duration_sec),
            "summary": summary,
            "output": {
                "fileName": file_name,
                "fileType": "docx",
                "size": self._format_file_size(file_size_bytes),
                "fileUrl": f"/api/projects/{project_id}/document/file",
            },
            "sections": copy.deepcopy(sections),
            "coverage": copy.deepcopy(coverage or {}),
            "assembly": copy.deepcopy(assembly or {}),
            "opencodeOutput": current_output,
            "events": current_events[-20:],
            "tasks": [
                {"id": "task-1", "label": "准备 S2 目录、Wiki 与素材库", "status": "done"},
                {"id": "task-2", "label": "调用技术标正文拼装 skill", "status": "done"},
                {"id": "task-3", "label": "写入 Word 正文", "status": "done"},
            ],
        }

        document_state = project["document_state"]
        next_version = int(document_state.get("version") or 1)
        if document_state.get("lastSavedAt"):
            next_version += 1
        document_state["status"] = "ready"
        document_state["sourceFileName"] = file_name
        document_state["fileName"] = file_name
        document_state["fileType"] = "docx"
        document_state["version"] = next_version
        document_state["lastSavedAt"] = filled_at
        document_state["fallback"]["content"] = content
        document_state["onlyoffice"]["title"] = file_name
        document_state["onlyoffice"]["documentKey"] = f"{project_id}-v{next_version}"

        project["updatedAt"] = filled_at
        self._persist_project(project)
        return copy.deepcopy(project["fill_state"])

    def get_coverage(self, project_id: str) -> dict[str, Any]:
        project = self._require(project_id)
        assembly_coverage = (project.get("fill_state") or {}).get("coverage")
        if isinstance(assembly_coverage, dict) and assembly_coverage:
            return copy.deepcopy(assembly_coverage)

        outline_nodes = list((project.get("outline_state") or {}).get("nodes") or [])
        if not outline_nodes:
            return {
                "percentage": 100,
                "fullCover": 0,
                "partialCover": 0,
                "noCover": 0,
                "tree": [],
                "partialItems": [],
                "noCoverItems": [],
            }

        sections = list((project.get("fill_state") or {}).get("sections") or [])
        section_status_map = {
            str(section.get("nodeId") or "").strip(): self._mode_to_coverage_status(section.get("generationMode"))
            for section in sections
            if str(section.get("nodeId") or "").strip()
        }

        tree = self._build_coverage_tree(outline_nodes, section_status_map)
        partial_items, no_cover_items = self._build_coverage_issue_lists(tree)
        full_cover, partial_cover, no_cover = self._summarize_coverage(tree)
        total = full_cover + partial_cover + no_cover
        percentage = 100 if total == 0 else round(((full_cover * 1.0) + (partial_cover * 0.5)) / total * 100)
        return {
            "percentage": percentage,
            "fullCover": full_cover,
            "partialCover": partial_cover,
            "noCover": no_cover,
            "tree": tree,
            "partialItems": partial_items,
            "noCoverItems": no_cover_items,
        }

    def get_document_state(self, project_id: str) -> dict[str, Any]:
        return copy.deepcopy(self._require(project_id)["document_state"])

    def save_document_content(self, project_id: str, content: str) -> dict[str, Any]:
        project = self._require(project_id)
        state = project["document_state"]
        next_version = int(state["version"] or 1) + 1
        state["version"] = next_version
        state["lastSavedAt"] = now_iso()
        state["onlyoffice"]["documentKey"] = f"{project_id}-v{next_version}"
        state["fallback"]["content"] = content
        project["updatedAt"] = state["lastSavedAt"]
        self._persist_project(project)
        return copy.deepcopy(state)

    def force_save_document(self, project_id: str) -> dict[str, Any]:
        project = self._require(project_id)
        state = project["document_state"]
        next_version = int(state["version"] or 1) + 1
        state["version"] = next_version
        state["lastSavedAt"] = now_iso()
        state["onlyoffice"]["documentKey"] = f"{project_id}-v{next_version}"
        project["updatedAt"] = state["lastSavedAt"]
        self._persist_project(project)
        return copy.deepcopy(state)

    def get_final_document(self, project_id: str) -> dict[str, Any]:
        state = self._require(project_id)["document_state"]
        return {
            "ready": True,
            "fileName": state["fileName"],
            "fileType": state["fileType"],
            "fileUrl": f"/api/projects/{project_id}/final-document/file",
            "lastSavedAt": state["lastSavedAt"],
            "version": state["version"],
        }

    def _ensure_gap_state(self, project: dict[str, Any]) -> dict[str, Any]:
        gap_state = project.get("gap_state")
        if not isinstance(gap_state, dict):
            gap_state = {}
            project["gap_state"] = gap_state
        gap_state.setdefault("recognitionStatus", "idle")
        gap_state.setdefault("recognizedAt", "")
        gap_state.setdefault("submittedForReview", False)
        gap_state.setdefault("reviewConfirmed", False)
        gap_state.setdefault("reviewedAt", "")
        gap_state.setdefault("items", [])
        gap_state.setdefault("submissions", [])
        return gap_state

    def _ensure_review_document_state(self, project: dict[str, Any]) -> dict[str, Any]:
        state = project.get("review_document_state")
        if not isinstance(state, dict):
            state = {}
            project["review_document_state"] = state
        state.setdefault("parseStatus", "idle")
        state.setdefault("parsedAt", "")
        state.setdefault("documentId", f"REV-DOC-{project['id']}")
        state.setdefault("sourceFileName", "")
        state.setdefault("fileName", f"{project['name']}_S6审核备料预览.docx")
        state.setdefault("fileType", "docx")
        state.setdefault("content", "")
        state.setdefault("lastSavedAt", "")
        state.setdefault("version", 1)
        state.setdefault("documentKey", f"{project['id']}-s6-v1")
        return state

    def _default_review_document_state(self, project: dict[str, Any]) -> dict[str, Any]:
        return {
            "parseStatus": "idle",
            "parsedAt": "",
            "documentId": f"REV-DOC-{project['id']}",
            "sourceFileName": "",
            "fileName": f"{project['name']}_S6审核备料预览.docx",
            "fileType": "docx",
            "content": "",
            "lastSavedAt": "",
            "version": 1,
            "documentKey": f"{project['id']}-s6-v1",
        }

    def _build_gap_items_from_outline(self, project: dict[str, Any]) -> list[dict[str, Any]]:
        outline_nodes = list((project.get("outline_state") or {}).get("nodes") or [])
        candidates = self._collect_outline_candidates(outline_nodes)
        if not candidates:
            candidates = [
                {"section": "项目概况", "title": "项目背景材料"},
                {"section": "技术方案", "title": "技术方案支撑材料"},
                {"section": "实施与保障", "title": "实施组织与资源证明"},
            ]

        items: list[dict[str, Any]] = []
        priorities = ["high", "high", "medium", "medium", "low", "low"]
        for index, candidate in enumerate(candidates[:6], start=1):
            items.append(
                {
                    "id": f"GAP-{index}",
                    "section": candidate["section"],
                    "title": candidate["title"],
                    "desc": f"请补充“{candidate['title']}”对应的佐证材料或说明。",
                    "priority": priorities[index - 1] if index - 1 < len(priorities) else "low",
                    "bidType": "技术标",
                    "status": "pending",
                    "skipReason": "",
                    "resolvedSource": "",
                    "resolvedAt": "",
                    "latestUploadAt": "",
                    "latestSubmissionId": "",
                }
            )
        return items

    def _collect_outline_candidates(
        self,
        nodes: list[dict[str, Any]],
        parents: list[str] | None = None,
    ) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        parent_titles = parents or []
        for node in nodes:
            title = str(node.get("title") or "").strip()
            children = list(node.get("children") or [])
            current_parents = parent_titles + ([title] if title else [])
            if children:
                result.extend(self._collect_outline_candidates(children, current_parents))
                continue
            if not title:
                continue
            section = " / ".join(parent_titles[-2:] or [title])
            result.append({"section": section, "title": title})
        return result

    def _build_gap_detection_payload(self, project: dict[str, Any], gap_state: dict[str, Any]) -> dict[str, Any]:
        items = copy.deepcopy(gap_state["items"])
        high_priority_count = sum(1 for item in items if item.get("priority") == "high")
        medium_priority_count = sum(1 for item in items if item.get("priority") == "medium")
        low_priority_count = max(0, len(items) - high_priority_count - medium_priority_count)
        return {
            "status": gap_state["recognitionStatus"],
            "recognizedAt": gap_state["recognizedAt"],
            "summary": {
                "totalMissing": len(items),
                "highPriorityCount": high_priority_count,
                "mediumPriorityCount": medium_priority_count,
                "lowPriorityCount": low_priority_count,
            },
            "items": items,
            "source": {
                "fromStage": "S4",
                "projectId": project["id"],
                "projectName": project["name"],
            },
        }

    def _find_gap_item(self, gap_state: dict[str, Any], gap_id: str) -> dict[str, Any]:
        for item in gap_state["items"]:
            if item.get("id") == gap_id:
                return item
        raise KeyError(gap_id)

    def _review_summary(self, gap_state: dict[str, Any]) -> dict[str, int]:
        items = list(gap_state["items"])
        return {
            "total": len(items),
            "resolvedCount": sum(1 for item in items if item["status"] == "resolved"),
            "skippedCount": sum(1 for item in items if item["status"] == "skipped"),
            "pendingCount": sum(1 for item in items if item["status"] not in {"resolved", "skipped"}),
        }

    def _build_review_payload(self, project: dict[str, Any], gap_state: dict[str, Any]) -> dict[str, Any]:
        latest_submission_by_missing_id: dict[str, dict[str, Any]] = {}
        for submission in gap_state["submissions"]:
            missing_id = str(submission.get("missingId") or "")
            if missing_id and missing_id not in latest_submission_by_missing_id:
                latest_submission_by_missing_id[missing_id] = submission

        items = []
        for item in gap_state["items"]:
            items.append(
                {
                    "id": item["id"],
                    "section": item["section"],
                    "title": item["title"],
                    "bidType": item.get("bidType") or "技术标",
                    "status": item["status"],
                    "resolvedSource": item.get("resolvedSource") or "",
                    "skipReason": item.get("skipReason") or "",
                    "resolvedAt": item.get("resolvedAt") or "",
                    "priority": item.get("priority") or "low",
                    "submission": copy.deepcopy(latest_submission_by_missing_id.get(item["id"])),
                }
            )

        review_state = self._ensure_review_document_state(project)
        return {
            "status": "ready" if gap_state["submittedForReview"] else "idle",
            "confirmed": bool(gap_state["reviewConfirmed"]),
            "reviewedAt": gap_state["reviewedAt"] or "",
            "summary": self._review_summary(gap_state),
            "items": items,
            "source": {
                "fromStage": "S5",
                "projectId": project["id"],
                "projectName": project["name"],
            },
            "parse": {
                "status": review_state["parseStatus"],
                "parsedAt": review_state["parsedAt"],
                "fileName": review_state["fileName"],
            },
        }

    def _review_source_file_name(self, gap_state: dict[str, Any]) -> str:
        for item in gap_state["items"]:
            if item.get("status") == "resolved" and item.get("resolvedSource"):
                return str(item["resolvedSource"])
        return "S5补料结果.docx"

    def _build_review_document_content(self, project: dict[str, Any], gap_state: dict[str, Any]) -> str:
        resolved_items = [item for item in gap_state["items"] if item["status"] == "resolved"]
        skipped_items = [item for item in gap_state["items"] if item["status"] == "skipped"]
        lines = [
            f"# {project['name']}（S6 审核备料解析稿）",
            "",
            "该文档由 S5 提交审核后自动生成，用于 S6 预览。",
            "",
            f"- 已补录：{len(resolved_items)} 项",
            f"- 未补录：{len(skipped_items)} 项",
            "",
            "## 已补录素材",
        ]
        if not resolved_items:
            lines.append("- 无")
        else:
            for index, item in enumerate(resolved_items, start=1):
                lines.append(f"{index}. {item['title']}（{item['section']}）")
                lines.append(f"   - 来源：{item.get('resolvedSource') or '已补录'}")

        lines.extend(["", "## 未补录素材"])
        if not skipped_items:
            lines.append("- 无")
        else:
            for index, item in enumerate(skipped_items, start=1):
                lines.append(f"{index}. {item['title']}（{item['section']}）")
                lines.append(f"   - 原因：{item.get('skipReason') or '未填写'}")
        return "\n".join(lines)

    @staticmethod
    def _count_nodes(nodes: list[dict[str, Any]]) -> int:
        total = 0
        for node in nodes:
            total += 1
            total += AppStore._count_nodes(node.get("children") or [])
        return total

    @staticmethod
    def _format_duration(seconds: int) -> str:
        total = max(0, int(seconds or 0))
        minutes = total // 60
        remain_seconds = total % 60
        if minutes <= 0:
            return f"{remain_seconds}秒"
        return f"{minutes}分{remain_seconds}秒"

    @staticmethod
    def _format_file_size(size_bytes: int) -> str:
        safe_size = max(0, int(size_bytes or 0))
        if safe_size < 1024:
            return f"{safe_size} B"
        if safe_size < 1024 * 1024:
            return f"{safe_size / 1024:.1f} KB"
        return f"{safe_size / (1024 * 1024):.1f} MB"

    @staticmethod
    def _mode_to_coverage_status(mode: Any) -> str:
        mode_text = str(mode or "").strip()
        if mode_text == "generated":
            return "full"
        if mode_text == "generated_with_placeholder":
            return "partial"
        return "none"

    def _build_coverage_tree(
        self,
        nodes: list[dict[str, Any]],
        section_status_map: dict[str, str],
        inherited_status: str | None = None,
    ) -> list[dict[str, Any]]:
        tree: list[dict[str, Any]] = []
        for node in nodes:
            node_id = str(node.get("id") or "")
            node_title = str(node.get("title") or "").strip() or "未命名章节"
            current_status = section_status_map.get(node_id) or inherited_status
            children = self._build_coverage_tree(
                node.get("children") or [],
                section_status_map,
                current_status,
            )
            if children:
                avg = sum(int(child.get("coverage") or 0) for child in children) / len(children)
                tree.append(
                    {
                        "id": node_id,
                        "title": node_title,
                        "coverage": round(avg),
                        "children": children,
                    }
                )
                continue

            leaf_status = current_status or "none"
            tree.append(
                {
                    "id": node_id,
                    "title": node_title,
                    "status": leaf_status,
                    "coverage": {"full": 100, "partial": 50, "none": 0}.get(leaf_status, 0),
                    "children": [],
                }
            )
        return tree

    def _build_coverage_issue_lists(
        self,
        tree: list[dict[str, Any]],
        path: list[str] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        partial_items: list[dict[str, Any]] = []
        no_cover_items: list[dict[str, Any]] = []
        current_path = path or []
        for node in tree:
            next_path = [*current_path, str(node.get("title") or "未命名章节")]
            children = list(node.get("children") or [])
            if children:
                nested_partial, nested_none = self._build_coverage_issue_lists(children, next_path)
                partial_items.extend(nested_partial)
                no_cover_items.extend(nested_none)
                continue

            item = {
                "id": str(node.get("id") or ""),
                "title": str(node.get("title") or "未命名章节"),
                "nodeTitle": " / ".join(current_path) if current_path else str(node.get("title") or "未命名章节"),
                "status": str(node.get("status") or "none"),
            }
            if item["status"] == "partial":
                partial_items.append(item)
            elif item["status"] == "none":
                no_cover_items.append(item)
        return partial_items, no_cover_items

    def _summarize_coverage(self, tree: list[dict[str, Any]]) -> tuple[int, int, int]:
        full_cover = 0
        partial_cover = 0
        no_cover = 0

        def visit(node: dict[str, Any]) -> None:
            nonlocal full_cover, partial_cover, no_cover
            children = list(node.get("children") or [])
            if children:
                for child in children:
                    visit(child)
                return

            status = str(node.get("status") or "none")
            if status == "full":
                full_cover += 1
            elif status == "partial":
                partial_cover += 1
            else:
                no_cover += 1

        for node in tree:
            visit(node)
        return full_cover, partial_cover, no_cover


store = AppStore()
