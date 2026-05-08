from __future__ import annotations

from typing import Any

from app.services.store import store


_STAGE_PROGRESS = {
    "S0": 0.10,
    "S1": 0.25,
    "S2": 0.40,
    "S3": 0.55,
    "S4": 0.70,
    "S5": 0.85,
    "S6": 1.00,
}


def _project_card(item: dict[str, Any], workspace_slug: str) -> dict[str, Any]:
    stage = str(item.get("currentStage") or "").strip()
    return {
        "id": item.get("id"),
        "name": item.get("name") or item.get("id"),
        "customer": item.get("customerCanonicalName") or item.get("customerName") or "",
        "keyAccount": False,
        "workspace": workspace_slug,
        "stage": stage,
        "stageLabel": item.get("stageLabel") or stage or "未开始",
        "progress": _STAGE_PROGRESS.get(stage, 0.0),
        "deadline": item.get("deadline") or "",
        "updatedAt": item.get("updatedAt") or "",
    }


def _running_count(items: list[dict[str, Any]]) -> int:
    return sum(1 for it in items if str(it.get("currentStage") or "") not in {"S6", ""})


def _delivered_count(items: list[dict[str, Any]]) -> int:
    return sum(1 for it in items if str(it.get("currentStage") or "") == "S6")


def _build_t(tech_items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "greeting": "聚焦技术标在跑项目",
        "metrics": [
            {"key": "running", "label": "在跑项目", "value": _running_count(tech_items), "trend": "", "tone": "primary", "icon": "engineering"},
            {"key": "thisWeek", "label": "已完成", "value": _delivered_count(tech_items), "trend": "", "tone": "success", "icon": "task_alt"},
            {"key": "todo", "label": "待我处理", "value": 0, "trend": "", "tone": "warn", "icon": "pending_actions"},
            {"key": "aiSaved", "label": "AI 累计省时", "value": "0h", "trend": "本周", "tone": "info", "icon": "bolt"},
        ],
        "projects": [_project_card(it, "tech") for it in tech_items],
        "todos": [],
        "activity": [],
    }


def _build_b(business_items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "greeting": "聚焦商务标在跑项目",
        "metrics": [
            {"key": "running", "label": "在跑项目", "value": _running_count(business_items), "trend": "", "tone": "primary", "icon": "request_quote"},
            {"key": "thisWeek", "label": "已完成", "value": _delivered_count(business_items), "trend": "", "tone": "success", "icon": "task_alt"},
            {"key": "reject", "label": "待确认否决项", "value": 0, "trend": "", "tone": "error", "icon": "gpp_maybe"},
            {"key": "aiSaved", "label": "AI 累计省时", "value": "0h", "trend": "本周", "tone": "info", "icon": "bolt"},
        ],
        "projects": [_project_card(it, "business") for it in business_items],
        "todos": [],
        "activity": [],
    }


def _build_tb(tech_items: list[dict[str, Any]], business_items: list[dict[str, Any]]) -> dict[str, Any]:
    by_id: dict[str, dict[str, Any]] = {}
    for it in tech_items:
        pid = str(it.get("id") or "")
        if not pid:
            continue
        by_id.setdefault(pid, {
            "id": pid,
            "name": it.get("name") or pid,
            "customer": it.get("customerCanonicalName") or it.get("customerName") or "",
            "deadline": it.get("deadline") or "",
            "tech": None,
            "business": None,
        })
        stage = str(it.get("currentStage") or "")
        by_id[pid]["tech"] = {
            "stage": stage,
            "stageLabel": it.get("stageLabel") or stage or "未开始",
            "progress": _STAGE_PROGRESS.get(stage, 0.0),
            "status": "running" if stage and stage != "S6" else "done",
        }
    for it in business_items:
        pid = str(it.get("id") or "")
        if not pid:
            continue
        by_id.setdefault(pid, {
            "id": pid,
            "name": it.get("name") or pid,
            "customer": it.get("customerCanonicalName") or it.get("customerName") or "",
            "deadline": it.get("deadline") or "",
            "tech": None,
            "business": None,
        })
        stage = str(it.get("currentStage") or "")
        by_id[pid]["business"] = {
            "stage": stage,
            "stageLabel": it.get("stageLabel") or stage or "未开始",
            "progress": _STAGE_PROGRESS.get(stage, 0.0),
            "status": "running" if stage and stage != "S6" else "done",
        }
    parallel = sorted(by_id.values(), key=lambda x: x.get("deadline") or "")
    total_running = _running_count(tech_items) + _running_count(business_items)
    total_delivered = _delivered_count(tech_items) + _delivered_count(business_items)
    return {
        "greeting": f"{len(by_id)} 个项目在跑",
        "metrics": [
            {"key": "running", "label": "在跑项目", "value": total_running, "trend": "", "tone": "primary", "icon": "workspaces"},
            {"key": "highPrio", "label": "高优先级", "value": 0, "trend": "", "tone": "error", "icon": "priority_high"},
            {"key": "thisWeek", "label": "已完成", "value": total_delivered, "trend": "", "tone": "success", "icon": "task_alt"},
            {"key": "aiSaved", "label": "团队 AI 累计省时", "value": "0h", "trend": "本周", "tone": "info", "icon": "bolt"},
        ],
        "projectsParallel": parallel,
        "todos": [],
        "activity": [],
    }


class DashboardService:
    async def build(self, user: dict[str, Any]) -> dict[str, Any]:
        role = str(user.get("role") or "member")
        tech_items: list[dict[str, Any]] = []
        business_items: list[dict[str, Any]] = []
        if role in {"T", "TB"}:
            tech_items = store.list_projects(bid_type="技术标", page_size=50).get("items", [])
        if role in {"B", "TB"}:
            business_items = store.list_projects(bid_type="商务标", page_size=50).get("items", [])

        if role == "T":
            payload = _build_t(tech_items)
        elif role == "B":
            payload = _build_b(business_items)
        elif role == "TB":
            payload = _build_tb(tech_items, business_items)
        else:
            payload = {
                "greeting": "暂无可用工作台",
                "metrics": [],
                "projects": [],
                "todos": [],
                "activity": [],
            }

        payload["role"] = role
        return payload


dashboard_service = DashboardService()
