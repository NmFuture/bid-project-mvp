"""S2 技术标目录的并行章节执行器：章节/附表并行决策会话、串行接力与受控收口。

从 outline_generation 拆出；对外仍经 app.services.outline_generation 门面 re-export。
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import logging
import os
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from app.core.config import settings
from app.services.agent_engine.concurrency import AGENT_CONCURRENCY_BUDGET
from app.services.agent_engine.opencode_engine import OpencodeEngine
from app.services.file_utils import run_awaitable_sync
from app.services.bid_runtime_state import build_directory_opencode_output
from app.services.system_settings import system_settings_service

OUTLINE_SKILL_NAME = "bid-tech-outline-generator"
TECH_OUTLINE_FINALIZE_COMMAND = "s2outline finalize"
TECH_OUTLINE_FINALIZE_EARLY_COMMAND = "s2outline-finalize"
TECH_OUTLINE_HANDOFF_DECISION_UNITS = 1
TECH_OUTLINE_CHAPTER_WORKERS = settings.tech_outline_chapter_workers
TECH_OUTLINE_TOTAL_WORKERS = TECH_OUTLINE_CHAPTER_WORKERS + 1
# 章节决策会话的并发池：B4（engine-06）起从全局并发预算派生，章节数（+1 附表）
# 只是预算内的上限，总并发恒 ≤ AGENT_CONCURRENCY_BUDGET，不再与各池叠加。
_TECH_OUTLINE_REQUEST_SLOTS = AGENT_CONCURRENCY_BUDGET.derive(TECH_OUTLINE_TOTAL_WORKERS)

logger = logging.getLogger(__name__)


class _ChapterParallelUnsupported(RuntimeError):
    pass


_DECISION_PROGRESS_READ_INTERVAL_SECONDS = 3.0


class _ChapterDecisionAggregator:
    """汇总并行章节会话的判定计数，节流上报 decision_progress。

    计数读取挂在各章节的流式回调上（消息更新即触发），读的是各章节工作区
    决策状态的只读快照；读失败只跳过本次，不影响生成主流程。
    """

    def __init__(
        self,
        chapters: list[dict[str, Any]],
        progress_callback: Callable[[str, dict[str, Any] | None], None] | None,
        *,
        appendix_total: int = 0,
    ) -> None:
        self._totals = {
            str(chapter["chapter_id"]): int(chapter.get("item_count") or 0)
            for chapter in chapters
        }
        self._decided = {chapter_id: 0 for chapter_id in self._totals}
        self._appendix_total = max(0, int(appendix_total))
        self._appendix_decided = 0
        self._done: set[str] = set()
        self._last_read = {chapter_id: 0.0 for chapter_id in self._totals}
        self._last_reported: tuple[int, int, int] | None = None
        self._lock = threading.Lock()
        self._callback = progress_callback

    def should_read(self, chapter_id: str) -> bool:
        if self._callback is None:
            return False
        now = time.monotonic()
        with self._lock:
            if now - self._last_read.get(chapter_id, 0.0) < _DECISION_PROGRESS_READ_INTERVAL_SECONDS:
                return False
            self._last_read[chapter_id] = now
            return True

    def update(self, chapter_id: str, decided_count: int) -> None:
        with self._lock:
            total = self._totals.get(chapter_id, 0)
            current = self._decided.get(chapter_id, 0)
            self._decided[chapter_id] = max(current, min(decided_count, total))
            payload = self._changed_payload_locked()
            self._emit(payload)

    def update_appendix(self, decided_count: int) -> None:
        with self._lock:
            self._appendix_decided = max(
                self._appendix_decided,
                min(max(0, decided_count), self._appendix_total),
            )
            payload = self._changed_payload_locked()
            self._emit(payload)

    def mark_done(self, chapter_id: str) -> None:
        with self._lock:
            self._done.add(chapter_id)
            self._decided[chapter_id] = self._totals.get(chapter_id, 0)
            payload = self._changed_payload_locked()
            self._emit(payload)

    def emit_initial(self) -> None:
        with self._lock:
            payload = self._changed_payload_locked(force=True)
            self._emit(payload)

    def _changed_payload_locked(self, force: bool = False) -> dict[str, Any] | None:
        chapter_decided = sum(self._decided.values())
        chapter_total = sum(self._totals.values())
        chapters_done = len(self._done)
        signature = (chapter_decided, self._appendix_decided, chapters_done)
        if not force and self._last_reported == signature:
            return None
        self._last_reported = signature
        if self._appendix_total <= 0:
            return {
                "phase": "chapters",
                "decided": chapter_decided,
                "total": chapter_total,
                "chaptersDone": chapters_done,
                "chaptersTotal": len(self._totals),
            }
        return {
            "phase": "parallel",
            "decided": chapter_decided + self._appendix_decided,
            "total": chapter_total + self._appendix_total,
            "chapterDecided": chapter_decided,
            "chapterTotal": chapter_total,
            "appendixDecided": self._appendix_decided,
            "appendixTotal": self._appendix_total,
            "chaptersDone": chapters_done,
            "chaptersTotal": len(self._totals),
        }

    def _emit(self, payload: dict[str, Any] | None) -> None:
        if payload is None or self._callback is None:
            return
        try:
            self._callback("decision_progress", payload)
        except Exception:
            # 进度上报绝不打断生成主流程
            pass
TECHNICAL_SUGGESTION_ACTIONS = {"必要", "建议增加", "建议删除", "待确认"}


def _load_technical_outline_runner() -> Any:
    module_name = "_sewpg_bid_technical_outline_runner"
    loaded = sys.modules.get(module_name)
    if loaded is not None:
        return loaded
    script_path = (
        Path(__file__).resolve().parents[2]
        / "opencode"
        / "skills"
        / OUTLINE_SKILL_NAME
        / "scripts"
        / "run_from_manifest.py"
    )
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载技术标目录 Skill：{script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _capture_trusted_technical_outline_input(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    template_file = Path(str(manifest.get("templateFile") or "")).expanduser()
    output_file = Path(str(manifest.get("outputFile") or "")).expanduser()
    if not template_file.is_file():
        raise RuntimeError(f"技术标历史模板不存在：{template_file}")
    if not str(manifest.get("outputFile") or "").strip():
        raise RuntimeError("技术标目录 manifest 缺少 outputFile。")
    runner = _load_technical_outline_runner()
    try:
        structure = runner.extract_template_structure(template_file)
        raw_tender_files = manifest.get("tenderFiles")
        tender_files = copy.deepcopy(raw_tender_files) if isinstance(raw_tender_files, list) else []
        appendix_inventory = runner.extract_tender_appendix_inventory(tender_files)
        appendix_items = runner.review_workflow.decision_appendix_items_from_inventory(
            appendix_inventory
        )
        tender_inputs_digest = (
            runner.review_workflow.tender_input_fingerprint(tender_files)
            if tender_files
            else ""
        )
    except SystemExit as exc:
        raise RuntimeError(f"技术标可信输入提取失败：{exc}") from exc
    return {
        "templateFile": str(template_file.resolve()),
        "templateFileSha256": hashlib.sha256(template_file.read_bytes()).hexdigest(),
        "outputFile": str(output_file.resolve()),
        "templateStructure": copy.deepcopy(structure),
        "tenderFiles": tender_files,
        "tenderInputsDigest": tender_inputs_digest,
        "appendixItems": copy.deepcopy(appendix_items),
    }


def _finalize_current_technical_outline(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["_runtimeRequireComposedOutline"] = True
    runner = _load_technical_outline_runner()
    try:
        return runner.finalize_manifest(manifest, manifest_path)
    except SystemExit as exc:
        raise RuntimeError(str(exc)) from exc


def _build_outline_handoff_prompt(manifest_path: Path, handoff_index: int) -> str:
    first_pass = handoff_index == 1
    startup = (
        "先执行一次 `s2outline prepare`，再将招标目录按 `next_cursor` 分页读到 complete=true。"
        if first_pass
        else (
            "步骤 1 和步骤 2 已由前序会话完整完成。继续使用现有决策状态；"
            "不要重复执行 prepare，不要执行 template-headings、headings、next-batch 或 review-batch，"
            "也不要重新读取全量模板或招标目录。直接从 decision-next 开始当前决策单元。"
        )
    )
    mandatory_start = (
        ""
        if first_pass
        else (
            "加载 Skill 后，第一条非 Skill 工具调用必须是 Bash，且 command 必须精确等于："
            f"`s2outline decision-next {manifest_path}`。"
            "禁止调用 Read、Glob、Grep，也不要执行 pwd、ls、cat 或搜索 manifest；"
            "manifest 路径已经给出，不需要探路。"
        )
    )
    return f"""
Use the {OUTLINE_SKILL_NAME} skill.

这是 S2 技术标目录的第 {handoff_index} 个受控接力会话。
manifest：{manifest_path}

{startup}
{mandatory_start}
本会话只做模板正文目录的自主判断：循环调用 `decision-next`，每个决策单元是一个一级章的章根加它下面的全部二级节点（三级节点跟随二级父节点，不单独判断）。按 Skill 自主使用 `search` 和 `section` 阅读相关招标原文，再提交“保留 / 建议增加 / 建议删除”。最多完成 {TECH_OUTLINE_HANDOFF_DECISION_UNITS} 个成功提交的决策单元；不足时做到 `decision-next complete=true` 为止。

本会话不得执行 appendix-next、review-complete、decisions、compose 或 finalize。到达本会话边界后立即停止，不要继续读后续章节；只返回一个简短 JSON：{{"workflowStage":"decision_checkpoint"}}。
""".strip()


def _build_outline_chapter_prompt(
    manifest_path: Path,
    chapter: dict[str, Any],
) -> str:
    return f"""
Use the {OUTLINE_SKILL_NAME} skill.

这是 S2 技术标目录的独立章节决策会话，只处理一级章：{chapter.get('number')} {chapter.get('title')}（chapter_id={chapter.get('chapter_id')}）。
manifest：{manifest_path}

准备产物已经由后端生成，不要执行 `s2outline prepare`。先用 `template-headings` 按 `next_cursor` 读完模板目录，再用 `headings` 按 `next_cursor` 读完整本招标目录，以便识别跨章等价项。
然后循环执行 `decision-next`。决策只到二级：`decision-next` 返回本章章根和它下面的全部二级节点，三级节点跟随二级父节点，不单独判断。按 Skill 自主使用 `search`、`section`、`read` 阅读相关招标原文，完成“保留 / 建议增加 / 建议删除”三类判断并执行 `decision-batch`，直到 `decision-next complete=true`。
若 `decision-next` 返回 `authoring_mode=sparse_chapter`（本章模板二级节点稀疏），按其 `decision_steps` 执行：自主圈定本章对应的少数上级章节后，用 `section --max-chars 30000` 连续通读，不做搜索式发散（search 全会话最多 2 次），从已读原文提炼响应单元并一次提交全部新增。
不要执行 `appendix-next`、`review-complete`、`decisions`、`compose` 或 `finalize`，也不要处理其他一级章。完成后只返回简短 JSON：{{"workflowStage":"chapter_complete"}}。
""".strip()


def _build_outline_appendix_prompt(manifest_path: Path) -> str:
    return f"""
Use the {OUTLINE_SKILL_NAME} skill.

这是 S2 技术标目录的附表决策会话。模板正文各章的三类判断已由并行章节会话全部完成并合并，本会话只做技术附表判断。
manifest：{manifest_path}

不要执行 `s2outline prepare`、`template-headings`、`headings`、`decision-next`、`decision-batch`、`review-corrections`、`review-complete`、`decisions`、`compose` 或 `finalize`，也不要改判正文章节。

从 `s2outline appendix-next {manifest_path} --max-items 40` 开始，按 Skill 第 4 步循环判断并用 `appendix-decision-batch` 提交，直到 `appendix-next` 返回 `complete=true`。需要证据时用 `search`、`section` 阅读招标原文。完成后只返回简短 JSON：{{"workflowStage":"appendix_complete"}}。
""".strip()


def _build_outline_appendix_predecision_prompt(manifest_path: Path) -> str:
    return f"""
Use the {OUTLINE_SKILL_NAME} skill.

这是 S2 技术标目录的附表并行预判会话。正文章节会话正在同时运行；本会话只判断每个附表 include 或 exclude，不生成节点、不挂载目录、不写正文决策。
manifest：{manifest_path}

不要执行 `s2outline prepare`、`template-headings`、`headings`、`decision-next`、`decision-batch`、`appendix-next`、`appendix-decision-batch`、`review-corrections`、`review-complete`、`decisions`、`compose` 或 `finalize`。

从 `s2outline appendix-predecision-next {manifest_path} --max-items 40` 开始，按 Skill 的附表判断规则逐项判断，并用 `appendix-predecision-batch` 提交。提交项只能包含 `appendix_id`、`decision`、`reason`。需要证据时用 `search`、`section` 阅读招标原文，直到 next 返回 `complete=true`。完成后只返回简短 JSON：{{"workflowStage":"appendix_predecision_complete"}}。
""".strip()


def _run_outline_appendix_session(
    manifest_path: Path,
    *,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    runner = _load_technical_outline_runner()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    work_dir = Path(str(manifest.get("workDir") or manifest_path.parent)).expanduser()
    structure = json.loads(
        (work_dir / "template_structure.json").read_text(encoding="utf-8")
    )
    appendix_items = runner.review_workflow.decision_appendix_items(work_dir)
    if not appendix_items:
        return {
            "sessionId": "",
            "state": {"complete": True, "decidedCount": 0, "remainingCount": 0},
            "opencodeOutput": build_directory_opencode_output(status="received"),
        }
    binding = runner._strict_workflow_binding(manifest, work_dir)

    def validate_complete() -> dict[str, Any]:
        return runner.decision_workflow.appendix_decision_progress(
            work_dir,
            structure,
            appendix_items,
            workflow_binding=binding,
        )

    appendix_total = len(appendix_items)
    last_progress_read = [0.0]

    def emit_appendix_progress(decided: int) -> None:
        if progress_callback:
            progress_callback(
                "decision_progress",
                {"phase": "appendix", "decided": decided, "total": appendix_total},
            )

    def stream_delta(details: dict[str, Any]) -> None:
        progress_callback("outline_delta", {**details, "suppressPercentage": True})
        now = time.monotonic()
        if now - last_progress_read[0] < _DECISION_PROGRESS_READ_INTERVAL_SECONDS:
            return
        last_progress_read[0] = now
        try:
            snapshot = validate_complete()
        except (Exception, SystemExit):
            return
        emit_appendix_progress(int(snapshot.get("decidedCount") or 0))

    emit_appendix_progress(0)
    # 保留直建：显式传 opencode 专有 timeout_ms（覆盖 DB timeoutMs 默认），非「只要默认引擎」。
    result = run_awaitable_sync(OpencodeEngine(
        timeout_ms=int(settings.opencode_timeout_sec * 1000),
    ).run_outline_decision_session(
        _build_outline_appendix_prompt(manifest_path),
        session_title="S2 附表决策",
        completion_validator=validate_complete,
        session_ready_callback=(
            (lambda details: progress_callback("outline_session_ready", details))
            if progress_callback
            else None
        ),
        stream_callback=stream_delta if progress_callback else None,
        session_phase="appendix_decision",
    ))
    emit_appendix_progress(appendix_total)
    return result


def _close_technical_outline_without_llm(manifest_path: Path) -> dict[str, Any]:
    """并行章节与附表决策完成后，由后端直跑受控收口命令，替代串行 LLM 收口会话。

    不再执行 LLM 全局复核：5 次实测复核仅 1 次改判且为重复既有章节的负价值
    产出，历史重大缺陷（空章）也未被其捕获；质量兜底交给下游人工审核与
    finalize 强校验。review-complete 仅在决策状态上盖全局复核章。
    """
    runner = _load_technical_outline_runner()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    review_payload = json.dumps(
        {
            "review_summary": (
                "并行章节决策与附表决策已全部提交并通过受控合并；"
                "按配置跳过 LLM 全局复核，由后端执行受控收口，质量由人工审核兜底。"
            ),
            "issues": [],
        },
        ensure_ascii=False,
    )
    try:
        runner.dispatch_command("review-complete", manifest, manifest_path, [review_payload])
        runner.dispatch_command("decisions", manifest, manifest_path, [])
        runner.dispatch_command("compose", manifest, manifest_path, [])
    except SystemExit as exc:
        raise RuntimeError(f"技术标目录受控收口失败：{exc}") from exc
    return _finalize_current_technical_outline(manifest_path)


def _outline_chapter_base_urls() -> list[str]:
    configured = [
        item.strip().rstrip("/")
        for item in os.getenv("OPENCODE_CHAPTER_BASE_URLS", "").split(",")
        if item.strip()
    ]
    return configured or [str(settings.opencode_base_url).rstrip("/")]


def _prepare_outline_chapter_workspaces(
    manifest_path: Path,
    structure: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Path], Path, dict[str, str]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    work_dir = Path(str(manifest.get("workDir") or manifest_path.parent)).expanduser()
    runner = _load_technical_outline_runner()
    runner.write_template_structure(manifest, manifest_path)
    chapters = list(runner.decision_workflow.decision_chapters(structure)["chapters"])
    chapter_root = work_dir.parent / f".{work_dir.name}-chapter-decisions"
    if chapter_root.exists():
        shutil.rmtree(chapter_root)
    chapter_root.mkdir(parents=True)

    chapter_manifests: dict[str, Path] = {}
    baseline_files = [path for path in work_dir.iterdir() if path.is_file()]
    for index, chapter in enumerate(chapters, start=1):
        chapter_id = str(chapter["chapter_id"])
        chapter_dir = chapter_root / f"chapter-{index:02d}"
        chapter_dir.mkdir()
        for source in baseline_files:
            shutil.copy2(source, chapter_dir / source.name)
        chapter_manifest = copy.deepcopy(manifest)
        chapter_manifest["workDir"] = str(chapter_dir)
        chapter_manifest["outputFile"] = str(chapter_dir / "toc.json")
        chapter_manifest["_runtimeDecisionChapterId"] = chapter_id
        chapter_manifest_path = chapter_dir / "s2_input.json"
        chapter_manifest_path.write_text(
            json.dumps(chapter_manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        chapter_manifests[chapter_id] = chapter_manifest_path

    cursor = 0
    while True:
        headings = runner.dispatch_command(
            "headings",
            manifest,
            manifest_path,
            ["--cursor", str(cursor), "--page-size", "200"],
        )
        if headings.get("requires_full_review"):
            shutil.rmtree(chapter_root, ignore_errors=True)
            raise _ChapterParallelUnsupported("招标文件缺少可分页目录结构")
        if headings.get("complete"):
            break
        cursor = int(headings["next_cursor"])
    workflow_binding = runner._strict_workflow_binding(manifest, work_dir) or {}
    return chapters, chapter_manifests, chapter_root, workflow_binding


def _prepare_outline_appendix_workspace(
    manifest_path: Path,
    chapter_root: Path,
) -> Path:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    work_dir = Path(str(manifest.get("workDir") or manifest_path.parent)).expanduser()
    appendix_dir = chapter_root / "appendix"
    appendix_dir.mkdir()
    for source in work_dir.iterdir():
        if source.is_file():
            shutil.copy2(source, appendix_dir / source.name)
    (appendix_dir / "outline_decision_state.json").unlink(missing_ok=True)
    appendix_manifest = copy.deepcopy(manifest)
    appendix_manifest["workDir"] = str(appendix_dir)
    appendix_manifest["outputFile"] = str(appendix_dir / "toc.json")
    appendix_manifest_path = appendix_dir / "s2_input.json"
    appendix_manifest_path.write_text(
        json.dumps(appendix_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return appendix_manifest_path


def _run_parallel_outline_chapters(
    manifest_path: Path,
    structure: dict[str, Any],
    *,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    runner = _load_technical_outline_runner()
    chapters, chapter_manifests, chapter_root, workflow_binding = (
        _prepare_outline_chapter_workspaces(manifest_path, structure)
    )
    appendix_manifest_path = _prepare_outline_appendix_workspace(
        manifest_path,
        chapter_root,
    )
    appendix_manifest = json.loads(
        appendix_manifest_path.read_text(encoding="utf-8")
    )
    appendix_work_dir = Path(str(appendix_manifest["workDir"]))
    appendix_items = runner.review_workflow.decision_appendix_items(
        appendix_work_dir
    )
    session_ids: dict[str, str] = {}
    chapter_base_urls = _outline_chapter_base_urls()
    model_config = system_settings_service.get_opencode_model_config_sync()
    chapter_indexes = {
        str(chapter["chapter_id"]): index for index, chapter in enumerate(chapters)
    }
    aggregator = _ChapterDecisionAggregator(
        chapters,
        progress_callback,
        appendix_total=len(appendix_items),
    )

    def run_chapter(chapter: dict[str, Any]) -> tuple[str, str]:
        chapter_id = str(chapter["chapter_id"])
        chapter_manifest_path = chapter_manifests[chapter_id]
        chapter_manifest = json.loads(chapter_manifest_path.read_text(encoding="utf-8"))
        chapter_work_dir = Path(str(chapter_manifest["workDir"]))

        def validate_complete() -> dict[str, Any]:
            binding = runner._strict_workflow_binding(chapter_manifest, chapter_work_dir) or {}
            return runner.decision_workflow.chapter_decision_progress(
                chapter_work_dir,
                structure,
                chapter_id,
                workflow_binding=binding,
            )

        def session_ready(details: dict[str, Any]) -> None:
            if progress_callback:
                progress_callback(
                    "outline_session_ready",
                    {**details, "chapterId": chapter_id, "chapterTitle": chapter.get("title")},
                )

        def stream_delta(details: dict[str, Any]) -> None:
            if progress_callback:
                progress_callback("outline_delta", {**details, "suppressPercentage": True})
            if aggregator.should_read(chapter_id):
                try:
                    snapshot = validate_complete()
                except (Exception, SystemExit):
                    return
                aggregator.update(chapter_id, int(snapshot.get("decidedCount") or 0))

        # 保留直建：章节并行按 base_url 分发到多个 opencode 实例（专有构造参数 base_url/timeout_ms/model_config/request_slots）。
        result = run_awaitable_sync(OpencodeEngine(
            base_url=chapter_base_urls[chapter_indexes[chapter_id] % len(chapter_base_urls)],
            timeout_ms=int(settings.opencode_timeout_sec * 1000),
            model_config=model_config,
            request_slots=_TECH_OUTLINE_REQUEST_SLOTS,
        ).run_outline_decision_session(
            _build_outline_chapter_prompt(chapter_manifest_path, chapter),
            session_title=f"S2 目录决策·{chapter.get('number') or chapter_id}",
            completion_validator=validate_complete,
            session_ready_callback=session_ready,
            stream_callback=stream_delta if progress_callback else None,
        ))
        return chapter_id, str(result["sessionId"])

    def run_appendix() -> dict[str, Any]:
        appendix_binding = (
            runner._strict_workflow_binding(appendix_manifest, appendix_work_dir) or {}
        )

        def validate_complete() -> dict[str, Any]:
            return runner.decision_workflow.appendix_decision_progress(
                appendix_work_dir,
                structure,
                appendix_items,
                workflow_binding=appendix_binding,
            )

        def session_ready(details: dict[str, Any]) -> None:
            if progress_callback:
                progress_callback(
                    "outline_session_ready",
                    {**details, "phase": "appendix"},
                )

        def stream_delta(details: dict[str, Any]) -> None:
            if progress_callback:
                progress_callback(
                    "outline_delta",
                    {**details, "suppressPercentage": True},
                )
            try:
                snapshot = validate_complete()
            except (Exception, SystemExit):
                return
            aggregator.update_appendix(int(snapshot.get("decidedCount") or 0))

        aggregator.update_appendix(0)
        # 保留直建：附表并行预判按 base_url 分发到多个 opencode 实例（专有构造参数 base_url/timeout_ms/model_config/request_slots）。
        result = run_awaitable_sync(OpencodeEngine(
            base_url=chapter_base_urls[len(chapters) % len(chapter_base_urls)],
            timeout_ms=int(settings.opencode_timeout_sec * 1000),
            model_config=model_config,
            request_slots=_TECH_OUTLINE_REQUEST_SLOTS,
        ).run_outline_decision_session(
            _build_outline_appendix_predecision_prompt(appendix_manifest_path),
            session_title="S2 附表并行预判",
            completion_validator=validate_complete,
            session_ready_callback=session_ready,
            stream_callback=stream_delta if progress_callback else None,
            session_phase="appendix_predecision",
        ))
        aggregator.update_appendix(len(appendix_items))
        return result

    appendix_result: dict[str, Any] | None = None
    appendix_predecided = not appendix_items
    try:
        aggregator.emit_initial()
        with ThreadPoolExecutor(
            max_workers=min(
                TECH_OUTLINE_TOTAL_WORKERS,
                max(1, len(chapters) + (1 if appendix_items else 0)),
            )
        ) as executor:
            futures: dict[Any, tuple[str, Any]] = {
                executor.submit(run_chapter, chapter): ("chapter", chapter)
                for chapter in chapters
            }
            if appendix_items:
                futures[executor.submit(run_appendix)] = ("appendix", None)
            chapter_failures: list[tuple[str, BaseException]] = []
            for future in as_completed(futures):
                kind, target = futures[future]
                if kind == "appendix":
                    try:
                        appendix_result = future.result()
                        appendix_predecided = True
                    except (Exception, SystemExit) as exc:
                        logger.warning(
                            "附表并行预判失败，将在章节合并后串行降级：%s",
                            exc,
                        )
                    continue
                # 章节失败不当场掀桌：先把其余章节收完，再统一决定怎么降级。
                try:
                    chapter_id, session_id = future.result()
                except (Exception, SystemExit) as exc:
                    failed_id = str((target or {}).get("chapter_id") or "")
                    chapter_failures.append((failed_id, exc))
                    logger.warning("S2 章节决策失败：%s：%s", failed_id, exc)
                    continue
                session_ids[chapter_id] = session_id
                aggregator.mark_done(chapter_id)

        # 合并要求每章判完（decision_workflow.merge_chapter_decisions），部分合并会把
        # 半成品写进主状态，所以这里不做部分合并，直接降级到调用方已有的串行接力：
        # 主 work_dir 未被并行阶段写过，串行会从头把所有判断补齐。
        if chapter_failures:
            failed_ids = "、".join(chapter_id or "未知章节" for chapter_id, _ in chapter_failures)
            raise _ChapterParallelUnsupported(
                f"S2 章节并行决策有 {len(chapter_failures)} 章未完成（{failed_ids}），改用串行接力"
            ) from chapter_failures[0][1]

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        work_dir = Path(str(manifest.get("workDir") or manifest_path.parent)).expanduser()
        runner.decision_workflow.merge_chapter_decisions(
            work_dir,
            structure,
            {
                chapter_id: Path(
                    json.loads(path.read_text(encoding="utf-8"))["workDir"]
                )
                for chapter_id, path in chapter_manifests.items()
            },
            workflow_binding=workflow_binding,
        )
        if appendix_predecided and appendix_items:
            try:
                runner.decision_workflow.materialize_appendix_predecisions(
                    work_dir,
                    appendix_work_dir,
                    structure,
                    appendix_items,
                    workflow_binding=workflow_binding,
                )
            except (Exception, SystemExit) as exc:
                appendix_predecided = False
                logger.warning(
                    "附表并行预判物化失败，将改用串行附表会话：%s",
                    exc,
                )
    except SystemExit as exc:
        raise RuntimeError(str(exc)) from exc
    except Exception:
        raise
    else:
        shutil.rmtree(chapter_root, ignore_errors=True)
    return {
        "chapterSessionIds": [
            session_ids[str(chapter["chapter_id"])] for chapter in chapters
        ],
        "appendixResult": appendix_result,
        "appendixPredecided": appendix_predecided,
    }


def _technical_outline_handoff_state(
    manifest_path: Path,
    *,
    previous_decided_count: int,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    runner = _load_technical_outline_runner()
    try:
        progress = runner.dispatch_command("decision-next", manifest, manifest_path, [])
    except SystemExit as exc:
        raise RuntimeError(str(exc)) from exc
    decided_count = int(progress.get("decided_count") or 0)
    complete = bool(progress.get("complete"))
    if not complete and decided_count <= previous_decided_count:
        raise RuntimeError(
            "S2 目录接力会话没有提交新的目录判断，已停止以避免空转。"
        )
    return {
        "complete": complete,
        "decidedCount": decided_count,
        "remainingCount": int(progress.get("remaining_count") or 0),
    }


def _build_outline_finalize_prompt(manifest_path: Path) -> str:
    return f"""
Use the {OUTLINE_SKILL_NAME} skill.

这是 S2 技术标目录的最终收口会话。模板正文目录的三类判断已经由前序接力会话全部完成并持久化。

manifest：{manifest_path}

不要执行 `s2outline prepare`、`template-headings`、`decision-next`、`decision-batch`、`next-batch` 或 `review-batch`。不要直接读取或修改 `outline_decision_state.json`、`outline_authoring_decisions.json`、`toc.json` 或 Skill 脚本，只使用 `s2outline` 受控命令。

从 `s2outline appendix-next {manifest_path} --max-items 40` 开始，按 Skill 完成技术附表判断。随后只做一次全局复核：用 `s2outline headings --review` 按 `next_cursor` 从头分页读完整本招标目录，逐项查漏；疑似缺项必须用 `s2outline section` 详读原文，必要时用 `search` 定位后继续详读。发现遗漏或误判就用 `review-corrections` 写回并重新复核，不能只写在总结里。

确认无问题后依次执行 `s2outline review-complete`、`s2outline decisions`、`s2outline compose` 和 `{TECH_OUTLINE_FINALIZE_COMMAND} {manifest_path}`。最后原样返回 finalize 的严格 JSON，不加 Markdown 或解释。
""".strip()


