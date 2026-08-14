"""cleanup-opencode-data.sh 回归测试：dry-run 不得静默吞 find 错误。

fake docker 模拟 compose ps / exec find；TEST_FIND_MODE 控制 find 行为：
- ok：输出 TEST_FIND_SIZES（换行分隔的字节数）
- empty：无输出（合法的 0 个文件）
- fail：stderr 报错并以非零退出（模拟卷/路径异常）
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile

CODE_ROOT = Path(__file__).resolve().parents[2]
CLEANUP_SCRIPT = CODE_ROOT / "scripts" / "cleanup-opencode-data.sh"

_FAKE_DOCKER = """#!/usr/bin/env bash
set -euo pipefail
# 参数形态：compose --project-directory X -f Y <subcommand...>
for arg in "$@"; do
  if [[ "${arg}" == "ps" ]]; then
    echo "opencode"
    exit 0
  fi
  if [[ "${arg}" == "exec" ]]; then
    case "${TEST_FIND_MODE}" in
      ok)
        printf '%s' "${TEST_FIND_SIZES}"
        exit 0
        ;;
      empty)
        exit 0
        ;;
      fail)
        echo "find: /root/.local/share/opencode: Input/output error" >&2
        exit 1
        ;;
    esac
  fi
done
exit 2
"""


def _create_rig() -> Path:
    root = Path(tempfile.mkdtemp(prefix="opencode-cleanup-test-"))
    (root / "docker-compose.yml").touch()
    shutil.copy2(CLEANUP_SCRIPT, root / CLEANUP_SCRIPT.name)
    fake_bin = root / "fake-bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(_FAKE_DOCKER, encoding="utf-8")
    fake_docker.chmod(0o755)
    return root


def _run_cleanup(root: Path, *arguments: str, find_mode: str, find_sizes: str = "") -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "PATH": f"{root / 'fake-bin'}:{os.environ['PATH']}",
        "TEST_FIND_MODE": find_mode,
        "TEST_FIND_SIZES": find_sizes,
    }
    return subprocess.run(
        ["bash", str(root / CLEANUP_SCRIPT.name), *arguments],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_dry_run_reports_scanned_files() -> None:
    root = _create_rig()
    try:
        completed = _run_cleanup(root, find_mode="ok", find_sizes="1048576\n2097152\n")

        assert completed.returncode == 0, completed.stderr
        assert "待清理：2 个文件，共 3.0 MiB。" in completed.stdout
        assert "dry-run" in completed.stdout
    finally:
        shutil.rmtree(root)


def test_dry_run_zero_files_is_legitimate() -> None:
    root = _create_rig()
    try:
        completed = _run_cleanup(root, find_mode="empty")

        assert completed.returncode == 0, completed.stderr
        assert "待清理：0 个文件" in completed.stdout
    finally:
        shutil.rmtree(root)


def test_dry_run_find_failure_fails_loudly() -> None:
    """find 失败必须显式报错退出，不得误报「0 个文件」。"""
    root = _create_rig()
    try:
        completed = _run_cleanup(root, find_mode="fail")

        assert completed.returncode != 0
        assert "Input/output error" in completed.stderr  # find 原始错误不吞
        assert "扫描" in completed.stderr and "失败" in completed.stderr
        assert "待清理：0 个文件" not in completed.stdout
    finally:
        shutil.rmtree(root)
