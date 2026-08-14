"""harness-08：docker-entrypoint.sh 模型回退单点化的回归覆盖。

以 sh 子进程真实执行 entrypoint 的三条配置链（runtime.json 改写 / INTERNAL_LLM /
legacy 回退），验证：
1. 三条链解析出的模型一致；
2. big-pickle 入参（含 provider 组合与限定串两种形态）正确映射为
   deepseek/deepseek-v4-flash；
3. 自定义模型原样透传，不被回退逻辑误伤。

entrypoint 末尾 `exec "$@"`，测试以 `sh -c 'cat "$OPENCODE_CONFIG"'` 作为被 exec
的命令读取最终生效配置；路径经 OPENCODE_HOME / OPENCODE_WORKSPACE_DIR /
OPENCODE_RUNTIME_CONFIG_PATH 重定向到临时目录，不碰真实 /workspace。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

OPENCODE_DIR = Path(__file__).resolve().parents[1] / "opencode"
ENTRYPOINT = OPENCODE_DIR / "docker-entrypoint.sh"
OPENCODE_JSON = OPENCODE_DIR / "opencode.json"


@unittest.skipUnless(shutil.which("sh") and shutil.which("python3"), "需要 sh 与 python3")
class EntrypointModelResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.home = root / "opencode-home"
        self.workspace = root / "workspace"
        self.workspace.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run_entrypoint(self, extra_env: dict[str, str]) -> dict:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "OPENCODE_HOME": str(self.home),
            "OPENCODE_WORKSPACE_DIR": str(self.workspace),
            # 默认指向不存在的路径，避免宿主机真实 /data 目录影响分支选择；
            # runtime 分支用例经 extra_env 覆盖为真实文件。
            "OPENCODE_RUNTIME_CONFIG_PATH": str(Path(self._tmp.name) / "absent-runtime.json"),
            # harness-09：entrypoint 启动时会按 commands.json 注册 skill 命令 wrapper，
            # 测试用真实 skills 目录作为注册源，wrapper 输出到临时 bin，不碰 /usr/local/bin。
            "OPENCODE_SKILLS_DIR": str(OPENCODE_DIR / "skills"),
            "OPENCODE_SKILL_BIN_DIR": str(Path(self._tmp.name) / "skill-bin"),
            **extra_env,
        }
        result = subprocess.run(
            ["sh", str(ENTRYPOINT), "sh", "-c", 'cat "$OPENCODE_CONFIG"'],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=60,
        )
        return json.loads(result.stdout)

    def _write_runtime_config(self, payload: dict) -> dict[str, str]:
        runtime_path = Path(self._tmp.name) / "opencode.runtime.json"
        runtime_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return {"OPENCODE_RUNTIME_CONFIG_PATH": str(runtime_path)}

    def _seed_legacy_opencode_json(self) -> None:
        shutil.copy(OPENCODE_JSON, self.workspace / "opencode.json")

    # ---- runtime.json 改写分支 ----

    def test_runtime_branch_maps_big_pickle_and_migrates_provider(self) -> None:
        env = self._write_runtime_config(
            {
                "$schema": "https://opencode.ai/config.json",
                "model": "opencode/big-pickle",
                "provider": {
                    "opencode": {
                        "npm": "@ai-sdk/openai-compatible",
                        "options": {"baseURL": "https://llm.example.com/v1"},
                        "models": {"big-pickle": {"name": "big-pickle"}},
                    }
                },
            }
        )
        config = self._run_entrypoint(env)
        self.assertEqual(config["model"], "deepseek/deepseek-v4-flash")
        self.assertNotIn("opencode", config["provider"])
        self.assertEqual(config["provider"]["deepseek"]["name"], "deepseek")
        self.assertIn("deepseek-v4-flash", config["provider"]["deepseek"]["models"])

    def test_runtime_branch_preserves_custom_model(self) -> None:
        env = self._write_runtime_config({"model": "mimo/demo-model"})
        config = self._run_entrypoint(env)
        self.assertEqual(config["model"], "mimo/demo-model")

    # ---- INTERNAL_LLM 分支 ----

    def test_internal_llm_branch_maps_big_pickle(self) -> None:
        config = self._run_entrypoint(
            {
                "INTERNAL_LLM_BASE_URL": "http://internal-llm:8000/v1",
                "OPENCODE_PROVIDER_ID": "opencode",
                "OPENCODE_MODEL_ID": "big-pickle",
            }
        )
        self.assertEqual(config["model"], "deepseek/deepseek-v4-flash")
        provider = config["provider"]["deepseek"]
        self.assertEqual(provider["options"]["baseURL"], "http://internal-llm:8000/v1")
        self.assertIn("deepseek-v4-flash", provider["models"])

    def test_internal_llm_branch_maps_qualified_big_pickle(self) -> None:
        config = self._run_entrypoint(
            {
                "INTERNAL_LLM_BASE_URL": "http://internal-llm:8000/v1",
                "OPENCODE_MODEL_ID": "opencode/big-pickle",
            }
        )
        self.assertEqual(config["model"], "deepseek/deepseek-v4-flash")

    def test_internal_llm_branch_preserves_custom_model(self) -> None:
        config = self._run_entrypoint(
            {
                "INTERNAL_LLM_BASE_URL": "http://internal-llm:8000/v1",
                "OPENCODE_PROVIDER_ID": "deepseek",
                "OPENCODE_MODEL_ID": "deepseek-v4-pro",
            }
        )
        self.assertEqual(config["model"], "deepseek/deepseek-v4-pro")

    def test_internal_llm_branch_preserves_slash_in_model_id(self) -> None:
        config = self._run_entrypoint(
            {
                "INTERNAL_LLM_BASE_URL": "http://internal-llm:8000/v1",
                "OPENCODE_PROVIDER_ID": "deepseek",
                "OPENCODE_MODEL_ID": "deepseek-ai/DeepSeek-V3",
            }
        )
        self.assertEqual(config["model"], "deepseek/deepseek-ai/DeepSeek-V3")

    # ---- legacy 回退分支 ----

    def test_legacy_branch_maps_big_pickle(self) -> None:
        self._seed_legacy_opencode_json()
        config = self._run_entrypoint(
            {
                "OPENCODE_PROVIDER_ID": "opencode",
                "OPENCODE_MODEL_ID": "big-pickle",
            }
        )
        self.assertEqual(config["model"], "deepseek/deepseek-v4-flash")
        # 其余 opencode.json 配置原样保留
        self.assertEqual(config["permission"]["task"], "deny")

    # ---- 三条链一致性 ----

    def test_three_branches_resolve_same_default_model(self) -> None:
        runtime_env = self._write_runtime_config({"model": "opencode/big-pickle"})
        runtime_model = self._run_entrypoint(runtime_env)["model"]

        internal_model = self._run_entrypoint(
            {
                "INTERNAL_LLM_BASE_URL": "http://internal-llm:8000/v1",
                "OPENCODE_PROVIDER_ID": "opencode",
                "OPENCODE_MODEL_ID": "big-pickle",
            }
        )["model"]

        self._seed_legacy_opencode_json()
        legacy_model = self._run_entrypoint(
            {
                "OPENCODE_PROVIDER_ID": "opencode",
                "OPENCODE_MODEL_ID": "big-pickle",
            }
        )["model"]

        self.assertEqual(runtime_model, "deepseek/deepseek-v4-flash")
        self.assertEqual(internal_model, runtime_model)
        self.assertEqual(legacy_model, runtime_model)


if __name__ == "__main__":
    unittest.main()
