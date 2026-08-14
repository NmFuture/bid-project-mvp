"""把单个文档处理阶段放进独立子进程执行。

大文档处理一旦超出容器内存上限，OOM killer 杀掉的是整个 worker 进程：任务来不及被
标成失败，恢复逻辑会把它原样放回队列再跑一遍，同一份素材于是反复把 worker 打死
（线上出现过连续 10 轮、82 分钟）。把每个阶段放进子进程后，超限时死的只是子进程，
父进程能拿到退出信号，如实把失败和原因写给前端，并且阶段结束时内存全额归还系统。

协议：父进程把调用规格写成 JSON，子进程执行后按行输出 JSON 事件（progress / result /
error）。库的日志走 stderr，由父进程转发到自己的 logger，容器日志观感不变。
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# 单个阶段的墙钟上限：卡死时也要有个终点，不能无限等下去。
STAGE_TIMEOUT_SEC = int(os.getenv("DOCX_STAGE_TIMEOUT_SEC", "3600"))

_EVENT_PREFIX = "@@DOCX_STAGE@@"


class DocxStageError(RuntimeError):
    """子进程阶段失败。out_of_memory 为真时表示被系统按内存杀掉。"""

    def __init__(self, message: str, *, out_of_memory: bool = False, detail: str = "") -> None:
        super().__init__(message)
        self.out_of_memory = out_of_memory
        self.detail = detail


def _emit(event: dict[str, Any]) -> None:
    sys.stdout.write(_EVENT_PREFIX + json.dumps(event, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _resolve_target(target: str) -> Callable[..., Any]:
    """target 支持两种写法：`module:function`，或 `path:<脚本路径>:<函数名>`。"""
    if target.startswith("path:"):
        # 从右侧切函数名：脚本路径里可能带盘符冒号（Windows）。
        file_path, _, func_name = target[len("path:") :].rpartition(":")
        if not file_path or not func_name:
            raise RuntimeError(f"阶段目标格式不正确：{target}")
        spec = importlib.util.spec_from_file_location("_docx_stage_target", file_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"无法加载阶段脚本：{file_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return getattr(module, func_name)
    module_name, _, func_name = target.partition(":")
    if not module_name or not func_name:
        raise RuntimeError(f"阶段目标格式不正确：{target}")
    return getattr(importlib.import_module(module_name), func_name)


def _run_child(spec_path: Path) -> int:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    func = _resolve_target(str(spec["target"]))
    kwargs = dict(spec.get("kwargs") or {})
    if spec.get("progress"):
        kwargs["progress_callback"] = lambda stage, details=None: _emit(
            {"kind": "progress", "stage": stage, "details": details}
        )
    payload = func(*list(spec.get("args") or []), **kwargs)
    _emit({"kind": "result", "payload": payload})
    return 0


def _pump_stderr(stream: Any, label: str) -> None:
    for line in iter(stream.readline, ""):
        text = line.rstrip()
        if text:
            logger.info("[%s] %s", label, text)
    stream.close()


def _pump_events(stream: Any, events: "queue.Queue[dict[str, Any] | None]") -> None:
    try:
        for line in iter(stream.readline, ""):
            if not line.startswith(_EVENT_PREFIX):
                continue
            try:
                events.put(json.loads(line[len(_EVENT_PREFIX) :]))
            except json.JSONDecodeError:
                continue
    finally:
        stream.close()
        events.put(None)


def run_stage(
    target: str,
    *,
    args: list[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
    spec_path: Path,
    label: str,
    progress: bool = False,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
    timeout_sec: int | None = None,
) -> Any:
    """在子进程里执行一个文档处理阶段，返回它的结果。

    子进程被系统按内存杀掉时抛 DocxStageError(out_of_memory=True)，调用方据此把
    任务标成失败并给出可操作的提示，而不是让整个 worker 陪葬。
    """
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(
        json.dumps(
            {
                "target": target,
                "args": args or [],
                "kwargs": kwargs or {},
                "progress": bool(progress),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # 子进程按后端根目录找 app 包，不依赖父进程的当前工作目录。
    backend_root = str(Path(__file__).resolve().parents[2])
    existing_path = os.environ.get("PYTHONPATH") or ""
    child_env = {
        **os.environ,
        "PYTHONUNBUFFERED": "1",
        # 事件流按 UTF-8 收发：默认编码随平台变化会把中文摘要打成乱码。
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": os.pathsep.join([backend_root, existing_path]) if existing_path else backend_root,
    }
    command = [sys.executable, "-m", __name__, str(spec_path)]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=child_env,
    )
    stderr_pump = threading.Thread(
        target=_pump_stderr,
        args=(process.stderr, label),
        daemon=True,
        name=f"docx-stage-{label}",
    )
    stderr_pump.start()

    # 事件读取放到线程里，主线程只负责盯着墙钟：子进程真卡死时不能把父进程也拖住。
    events: "queue.Queue[dict[str, Any] | None]" = queue.Queue()
    stdout_pump = threading.Thread(
        target=_pump_events,
        args=(process.stdout, events),
        daemon=True,
        name=f"docx-stage-out-{label}",
    )
    stdout_pump.start()

    limit_sec = timeout_sec or STAGE_TIMEOUT_SEC
    deadline = time.monotonic() + limit_sec
    result: Any = None
    got_result = False
    failure: dict[str, Any] | None = None
    try:
        while True:
            if time.monotonic() > deadline:
                raise DocxStageError(f"{label} 阶段超时未完成（上限 {limit_sec} 秒）。")
            try:
                event = events.get(timeout=1.0)
            except queue.Empty:
                continue
            if event is None:
                break
            kind = event.get("kind")
            if kind == "progress":
                if progress_callback:
                    progress_callback(str(event.get("stage") or ""), event.get("details"))
            elif kind == "result":
                result = event.get("payload")
                got_result = True
            elif kind == "error":
                failure = event
        returncode = process.wait(timeout=max(1.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        raise DocxStageError(f"{label} 阶段超时未完成（上限 {limit_sec} 秒）。")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        stderr_pump.join(timeout=2)
        stdout_pump.join(timeout=2)

    if returncode == 0 and got_result:
        return result

    if returncode < 0:
        signal_number = -returncode
        if signal_number == 9:
            raise DocxStageError(
                f"{label} 阶段内存超出容器上限被系统终止。请确认该项目素材体量，"
                f"或提高 worker 的内存配额后重试。",
                out_of_memory=True,
            )
        raise DocxStageError(f"{label} 阶段被信号 {signal_number} 终止。", out_of_memory=signal_number == 9)

    detail = str((failure or {}).get("traceback") or "")
    message = str((failure or {}).get("message") or "") or f"{label} 阶段异常退出（退出码 {returncode}）。"
    raise DocxStageError(message, detail=detail)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if len(sys.argv) != 2:
        print("usage: python -m app.services.docx_stage_runner <spec.json>", file=sys.stderr)
        return 2
    try:
        return _run_child(Path(sys.argv[1]))
    except Exception as exc:  # noqa: BLE001 - 失败要把原因原样带回父进程
        import traceback

        _emit({"kind": "error", "message": str(exc), "traceback": traceback.format_exc()})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
