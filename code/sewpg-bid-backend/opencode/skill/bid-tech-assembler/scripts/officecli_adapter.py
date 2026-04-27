"""
OfficeCLI 适配层

为 bid-assembler 的最终 docx 产物提供只读审计能力：
- OpenXML schema 校验
- OfficeCLI issues 扫描
- 文档统计信息采集

当前适配层不修改最终文档，只生成结构化 JSON 报告。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, List

from .config import ProjectConfig

logger = logging.getLogger(__name__)


class OfficeCliAdapter:
    """封装 officecli 调用，供流水线在生成后自动审计。"""

    ISSUE_TYPES = ("format", "content", "structure")

    def __init__(self, config: ProjectConfig):
        self.config = config
        self.binary = self._resolve_binary()

    def _resolve_binary(self) -> str:
        configured = (self.config.officecli_binary or "officecli").strip()
        if not configured:
            return ""
        if os.path.isabs(configured):
            return configured if os.path.exists(configured) else ""
        return shutil.which(configured) or ""

    def audit_docx(self, docx_path: str) -> Dict[str, Any]:
        """
        审计一个 docx 文件，并将报告写入 project output 目录。

        返回报告 dict，至少包含：
        - status
        - report_path
        - summary
        """
        report_path = self.config.get_officecli_report_path()
        report: Dict[str, Any] = {
            "status": "disabled",
            "report_path": report_path,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "document": os.path.abspath(docx_path),
            "binary": self.binary or (self.config.officecli_binary or "officecli"),
            "validate": {},
            "issues": {},
            "stats": {},
            "summary": {
                "validation_error_count": 0,
                "issue_count": 0,
                "issue_counts_by_type": {},
            },
        }

        if not self.config.officecli_enabled:
            report["status"] = "disabled"
            report["message"] = "project.json 已禁用 officecli 审计"
            return self._write_report(report)

        if not os.path.exists(docx_path):
            report["status"] = "error"
            report["message"] = f"文档不存在: {docx_path}"
            return self._write_report(report)

        if not self.binary:
            report["status"] = "unavailable"
            report["message"] = "未找到 officecli，可通过 officecli_binary 指定路径"
            return self._write_report(report)

        try:
            issue_limit = str(max(int(self.config.officecli_issue_limit or 50), 1))
            report["validate"] = self._run_json(["validate", docx_path, "--json"])
            report["issues"]["all"] = self._run_json(
                ["view", docx_path, "issues", "--limit", issue_limit, "--json"]
            )
            for issue_type in self.ISSUE_TYPES:
                report["issues"][issue_type] = self._run_json(
                    [
                        "view",
                        docx_path,
                        "issues",
                        "--type",
                        issue_type,
                        "--limit",
                        issue_limit,
                        "--json",
                    ]
                )
            report["stats"] = self._run_json(["view", docx_path, "stats", "--json"])
            failures = self._collect_failures(report)
            if failures:
                report["status"] = "error"
                report["message"] = "；".join(failures)
            else:
                report["status"] = "ok"
        except Exception as exc:
            report["status"] = "error"
            report["message"] = f"officecli 审计失败: {exc}"

        report["summary"] = self._build_summary(report)
        return self._write_report(report)

    def _run_json(self, args: List[str]) -> Dict[str, Any]:
        command = [self.binary, *args]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )

        payload: Dict[str, Any] = {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
            "parsed": {},
            "success": completed.returncode == 0,
            "valid_json": False,
        }

        if completed.stdout.strip():
            try:
                payload["parsed"] = json.loads(completed.stdout)
                payload["valid_json"] = True
            except json.JSONDecodeError:
                payload["parsed"] = {}
        elif completed.returncode == 0:
            payload["valid_json"] = False

        if completed.returncode != 0:
            logger.warning("officecli 命令失败: %s", " ".join(command))
        elif not payload["valid_json"]:
            logger.warning("officecli 命令未返回有效 JSON: %s", " ".join(command))

        return payload

    def _collect_failures(self, report: Dict[str, Any]) -> List[str]:
        failures: List[str] = []
        checks = [
            ("validate", report.get("validate", {})),
            ("stats", report.get("stats", {})),
            ("issues.all", (report.get("issues") or {}).get("all", {})),
        ]
        for issue_type in self.ISSUE_TYPES:
            checks.append(
                (f"issues.{issue_type}", (report.get("issues") or {}).get(issue_type, {}))
            )

        for label, result in checks:
            if not isinstance(result, dict):
                failures.append(f"{label} 返回结果缺失")
                continue
            if not result.get("success"):
                failures.append(f"{label} 命令失败")
                continue
            if not result.get("valid_json"):
                failures.append(f"{label} 未返回有效 JSON")

        return failures

    def _build_summary(self, report: Dict[str, Any]) -> Dict[str, Any]:
        summary = {
            "validation_error_count": self._extract_validation_error_count(
                report.get("validate", {})
            ),
            "issue_count": self._extract_issue_count(
                report.get("issues", {}).get("all", {})
            ),
            "issue_counts_by_type": {},
        }

        for issue_type in self.ISSUE_TYPES:
            summary["issue_counts_by_type"][issue_type] = self._extract_issue_count(
                report.get("issues", {}).get(issue_type, {})
            )

        stats_data = ((report.get("stats") or {}).get("parsed") or {}).get("data") or {}
        if stats_data:
            summary["paragraphs"] = stats_data.get("paragraphs", 0)
            summary["words"] = stats_data.get("words", 0)

        return summary

    @staticmethod
    def _extract_validation_error_count(result: Dict[str, Any]) -> int:
        data = ((result or {}).get("parsed") or {}).get("data") or {}
        count = data.get("count")
        if isinstance(count, int):
            return count
        errors = data.get("errors") or []
        return len(errors) if isinstance(errors, list) else 0

    @staticmethod
    def _extract_issue_count(result: Dict[str, Any]) -> int:
        data = ((result or {}).get("parsed") or {}).get("data") or {}
        for key in ("Count", "count"):
            value = data.get(key)
            if isinstance(value, int):
                return value
        issues = data.get("Issues") or data.get("issues") or []
        return len(issues) if isinstance(issues, list) else 0

    def _write_report(self, report: Dict[str, Any]) -> Dict[str, Any]:
        report_path = report["report_path"]
        os.makedirs(os.path.dirname(os.path.abspath(report_path)), exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info("OfficeCLI 审计报告已保存: %s", report_path)
        return report
