"""harness-09：skill 命令别名运行时注册的回归覆盖。

命令别名不再由 Dockerfile 构建期 printf 固化，事实源是
`opencode/skills/commands.json`，容器启动时由 docker-entrypoint.sh 的
`register_skill_commands` 生成 `/usr/local/bin` 下的 wrapper（含子命令白名单）。

本模块从 entrypoint 里抠出生成器的 Python heredoc，用临时 BIN_DIR 真实执行：
1. 注册表与 skills 目录实际内容一致（16 个别名、script 都存在）；
2. 生成的 wrapper 语法合法、可执行，白名单外子命令被拒绝（exit 64）；
3. 新增 dummy skill 只需登记 commands.json，不改 Dockerfile 即可获得别名；
4. STAGES.md 两张映射表的别名列与注册表一一对应（harness-11 协同约束）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
OPENCODE_DIR = BACKEND_ROOT / "opencode"
SKILLS_DIR = OPENCODE_DIR / "skills"
REGISTRY_PATH = SKILLS_DIR / "commands.json"
ENTRYPOINT = OPENCODE_DIR / "docker-entrypoint.sh"
STAGES_MD = SKILLS_DIR / "STAGES.md"

EXPECTED_ALIASES = {
    "s1parse",
    "s2toc",
    "s2outline",
    "business-outline",
    "btplnav",
    "businessassemble",
    "businessformat",
    "s4gap",
    "businessgap",
    "businesstablefill",
    "s4fill-prepare",
    "s4fill-apply",
    "s4wordfill",
    "factcurate",
    "xrefindex",
    "wikibuild",
}

ALIAS_NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]*")


def load_registry() -> dict[str, dict]:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return {entry["name"]: entry for entry in registry["commands"]}


def extract_generator_script() -> str:
    """从 entrypoint 中抠出 register_skill_commands 的 Python heredoc 正文。"""
    text = ENTRYPOINT.read_text(encoding="utf-8")
    func_start = text.index("register_skill_commands() {")
    heredoc_start = text.index("python3 - <<'PY'\n", func_start) + len("python3 - <<'PY'\n")
    heredoc_end = text.index("\nPY\n", heredoc_start)
    return text[heredoc_start:heredoc_end]


def run_generator(skills_dir: Path, bin_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", "-c", extract_generator_script()],
        env={**os.environ, "SKILLS_DIR": str(skills_dir), "BIN_DIR": str(bin_dir)},
        capture_output=True,
        text=True,
        check=False,
    )


@unittest.skipUnless(shutil.which("sh") and shutil.which("python3"), "需要 sh 与 python3")
class SkillCommandRegistrationTests(unittest.TestCase):
    def test_registry_covers_expected_aliases_and_existing_scripts(self) -> None:
        entries = load_registry()

        self.assertEqual(set(entries), EXPECTED_ALIASES)
        for name, entry in entries.items():
            script = entry["script"]
            self.assertFalse(script.startswith("/"), name)
            self.assertNotIn("..", Path(script).parts, name)
            self.assertTrue((SKILLS_DIR / script).is_file(), f"{name}: {script}")
            if "subcommands" in entry:
                self.assertNotIn("argv", entry, name)
            if "argv" in entry:
                self.assertIn("{manifest}", entry["argv"], name)

    def test_generator_creates_executable_posix_wrappers_for_all_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            completed = run_generator(SKILLS_DIR, bin_dir)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            generated = {path.name for path in bin_dir.iterdir()}
            self.assertEqual(generated, EXPECTED_ALIASES)
            for name in EXPECTED_ALIASES:
                wrapper = bin_dir / name
                content = wrapper.read_text(encoding="utf-8")
                self.assertTrue(content.startswith("#!/bin/sh\n"), name)
                self.assertTrue(wrapper.stat().st_mode & stat.S_IXUSR, name)
                syntax = subprocess.run(
                    ["sh", "-n", str(wrapper)], capture_output=True, text=True, check=False
                )
                self.assertEqual(syntax.returncode, 0, f"{name}: {syntax.stderr}")

    def test_whitelisted_wrapper_rejects_unknown_subcommand(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            completed = run_generator(SKILLS_DIR, bin_dir)
            self.assertEqual(completed.returncode, 0, completed.stderr)

            rejected = subprocess.run(
                ["sh", str(bin_dir / "s2outline"), "rm-rf-everything", "/tmp/x.json"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(rejected.returncode, 64)
            self.assertIn("usage: s2outline", rejected.stderr)

            rejected_btplnav = subprocess.run(
                ["sh", str(bin_dir / "btplnav"), "shell", "/tmp/x.json"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(rejected_btplnav.returncode, 64)
            self.assertIn("usage: btplnav", rejected_btplnav.stderr)

    def test_single_manifest_wrapper_requires_exactly_one_argument(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            completed = run_generator(SKILLS_DIR, bin_dir)
            self.assertEqual(completed.returncode, 0, completed.stderr)

            for args in ([], ["/tmp/a.json", "/tmp/b.json"]):
                rejected = subprocess.run(
                    ["sh", str(bin_dir / "s4gap"), *args],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(rejected.returncode, 64)
                self.assertIn("usage: s4gap", rejected.stderr)

    def test_generator_fails_loudly_when_registry_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            empty_skills = Path(tmp) / "skills"
            empty_skills.mkdir()
            completed = run_generator(empty_skills, Path(tmp) / "bin")

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("commands.json", completed.stderr)

    def test_new_skill_registered_without_dockerfile_change(self) -> None:
        """harness-09 验收路径：加 skill = 加目录 + 登记 commands.json，重跑注册即可用。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_dir = root / "skills"
            shutil.copytree(
                SKILLS_DIR,
                skills_dir,
                ignore=shutil.ignore_patterns("__pycache__"),
            )

            dummy = skills_dir / "bid-tech-dummy" / "scripts"
            dummy.mkdir(parents=True)
            (dummy / "run_from_manifest.py").write_text(
                "import json, sys\nprint(json.dumps(sys.argv[1:]))\n", encoding="utf-8"
            )
            registry = json.loads((skills_dir / "commands.json").read_text(encoding="utf-8"))
            registry["commands"].append(
                {
                    "name": "dummyrun",
                    "script": "bid-tech-dummy/scripts/run_from_manifest.py",
                    "usage": "dummyrun <manifest>",
                    "argv": ["--manifest", "{manifest}", "--response", "summary"],
                }
            )
            (skills_dir / "commands.json").write_text(
                json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            bin_dir = root / "bin"
            completed = run_generator(skills_dir, bin_dir)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                {path.name for path in bin_dir.iterdir()}, EXPECTED_ALIASES | {"dummyrun"}
            )

            invoked = subprocess.run(
                ["sh", str(bin_dir / "dummyrun"), "/tmp/manifest.json"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(invoked.returncode, 0, invoked.stderr)
            self.assertEqual(
                json.loads(invoked.stdout),
                ["--manifest", "/tmp/manifest.json", "--response", "summary"],
            )

    def test_generator_rejects_unsafe_registry_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_dir = root / "skills"
            skills_dir.mkdir()
            (skills_dir / "runner.py").write_text("print('ok')\n", encoding="utf-8")
            bin_dir = root / "bin"

            for entry in (
                {"name": "bad name", "script": "runner.py", "usage": "x <manifest>"},
                {"name": "evil", "script": "../escape.py", "usage": "evil <manifest>"},
                {
                    "name": "inject",
                    "script": "runner.py",
                    "usage": "inject <manifest>",
                    "argv": ["--manifest", "{manifest}", "$(rm -rf /)"],
                },
                {
                    "name": "dup",
                    "script": "runner.py",
                    "usage": "dup <manifest>",
                    "argv": ["{manifest}"],
                },
            ):
                if entry["name"] == "dup":
                    commands = [entry, dict(entry)]
                else:
                    commands = [entry]
                (skills_dir / "commands.json").write_text(
                    json.dumps({"commands": commands}), encoding="utf-8"
                )
                completed = run_generator(skills_dir, bin_dir)
                self.assertNotEqual(completed.returncode, 0, entry["name"])
                self.assertIn("skill 命令注册失败", completed.stderr)

    def test_dockerfile_no_longer_bakes_wrappers(self) -> None:
        dockerfile = (OPENCODE_DIR / "Dockerfile").read_text(encoding="utf-8")

        self.assertNotIn("> /usr/local/bin/s1parse", dockerfile)
        self.assertNotIn("printf '%s\\n'", dockerfile)
        for name in EXPECTED_ALIASES:
            self.assertNotIn(f"> /usr/local/bin/{name}", dockerfile)

    def test_stages_md_alias_columns_match_registry(self) -> None:
        """harness-11 协同：STAGES.md 两表别名列与 commands.json 互相对应。"""
        registry_names = set(load_registry())
        stages_text = STAGES_MD.read_text(encoding="utf-8")

        table_aliases: set[str] = set()
        for line in stages_text.splitlines():
            if not line.startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) < 4 or cells[0].startswith("-") or cells[0] == "用户侧阶段":
                continue
            for token in re.findall(r"`([^`]+)`", cells[2]):
                if ALIAS_NAME_RE.fullmatch(token):
                    table_aliases.add(token)

        for alias in table_aliases:
            self.assertIn(alias, registry_names, f"STAGES.md 别名未登记: {alias}")
        for name in registry_names:
            self.assertIn(f"`{name}`", stages_text, f"注册表别名未写入 STAGES.md: {name}")


if __name__ == "__main__":
    unittest.main()
