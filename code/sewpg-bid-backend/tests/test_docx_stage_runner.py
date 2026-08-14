"""阶段子进程隔离的契约：结果要拿得回来，失败要说得清楚，被 OOM 杀掉要认得出来。"""

from __future__ import annotations

import signal
import textwrap
from pathlib import Path

import pytest

from app.services.docx_stage_runner import DocxStageError, run_stage


def _script(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "stage_target.py"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def test_stage_returns_child_result(tmp_path: Path) -> None:
    script = _script(
        tmp_path,
        """
        def run(value):
            return {"echoed": value, "status": "completed"}
        """,
    )

    result = run_stage(
        f"path:{script}:run",
        args=["hello"],
        spec_path=tmp_path / "spec.json",
        label="回显",
    )

    assert result == {"echoed": "hello", "status": "completed"}


def test_stage_forwards_progress_events(tmp_path: Path) -> None:
    script = _script(
        tmp_path,
        """
        def run(progress_callback=None):
            progress_callback("assembling_progress", {"done": 1, "total": 2})
            progress_callback("assembling_progress", {"done": 2, "total": 2})
            return {"status": "completed"}
        """,
    )
    seen: list[tuple[str, dict]] = []

    run_stage(
        f"path:{script}:run",
        spec_path=tmp_path / "spec.json",
        label="进度",
        progress=True,
        progress_callback=lambda stage, details=None: seen.append((stage, details)),
    )

    assert seen == [
        ("assembling_progress", {"done": 1, "total": 2}),
        ("assembling_progress", {"done": 2, "total": 2}),
    ]


def test_stage_propagates_child_error_message(tmp_path: Path) -> None:
    script = _script(
        tmp_path,
        """
        def run():
            raise ValueError("素材缺少 material_id")
        """,
    )

    with pytest.raises(DocxStageError) as excinfo:
        run_stage(f"path:{script}:run", spec_path=tmp_path / "spec.json", label="失败")

    assert "素材缺少 material_id" in str(excinfo.value)
    assert not excinfo.value.out_of_memory
    assert "ValueError" in excinfo.value.detail


@pytest.mark.skipif(not hasattr(signal, "SIGKILL"), reason="SIGKILL 只有 POSIX 才有")
def test_stage_reports_out_of_memory_when_child_is_killed(tmp_path: Path) -> None:
    """被系统按内存杀掉时必须认出来并给出可操作的提示。

    这是"worker 被 OOM 打死→任务原样重跑"死循环的根因所在：父进程活着并能把
    失败如实写出去，循环才有出口。
    """
    script = _script(
        tmp_path,
        """
        import os, signal

        def run():
            os.kill(os.getpid(), signal.SIGKILL)
        """,
    )

    with pytest.raises(DocxStageError) as excinfo:
        run_stage(f"path:{script}:run", spec_path=tmp_path / "spec.json", label="内存超限")

    assert excinfo.value.out_of_memory
    assert "内存" in str(excinfo.value)


def test_stage_times_out_instead_of_hanging_forever(tmp_path: Path) -> None:
    script = _script(
        tmp_path,
        """
        import time

        def run():
            time.sleep(30)
        """,
    )

    with pytest.raises(DocxStageError, match="超时"):
        run_stage(
            f"path:{script}:run",
            spec_path=tmp_path / "spec.json",
            label="卡死",
            timeout_sec=1,
        )
