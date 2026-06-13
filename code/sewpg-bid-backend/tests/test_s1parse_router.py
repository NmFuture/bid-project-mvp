from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from app.services.system_settings import system_settings_service


ROUTER_PATH = Path(__file__).resolve().parents[1] / "opencode" / "skill" / "s1parse_router.py"


def load_router_module():
    module_name = "s1parse_router_test"
    spec = importlib.util.spec_from_file_location(module_name, ROUTER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


ROUTER = load_router_module()


class S1ParseRouterTests(unittest.TestCase):
    def write_manifest(self, root: Path, payload: dict[str, object]) -> Path:
        manifest_path = root / "manifest.json"
        manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest_path

    def test_resolve_runner_prefers_parse_profile_for_business_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = self.write_manifest(
                Path(tmp),
                {
                    "parseProfile": "business",
                    "bidType": "技术标",
                    "documents": [],
                },
            )

            runner = ROUTER.resolve_runner(manifest_path)

        self.assertEqual(runner.name, "run_from_manifest.py")
        self.assertIn("bid-business-tender-structured-parser", str(runner))

    def test_resolve_runner_routes_business_bid_type_to_business_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = self.write_manifest(
                Path(tmp),
                {
                    "bidType": "商务标",
                    "documents": [],
                },
            )

            runner = ROUTER.resolve_runner(manifest_path)

        self.assertEqual(runner.name, "run_from_manifest.py")
        self.assertIn("bid-business-tender-structured-parser", str(runner))

    def test_resolve_runner_defaults_unknown_bid_type_to_technical_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = self.write_manifest(
                Path(tmp),
                {
                    "bidType": "未知标类",
                    "documents": [],
                },
            )

            runner = ROUTER.resolve_runner(manifest_path)

        self.assertEqual(runner.name, "run_from_manifest.py")
        self.assertIn("bid-tech-tender-structured-parser", str(runner))

    def test_main_dispatches_manifest_to_resolved_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = self.write_manifest(Path(tmp), {"bidType": "商务标", "documents": []})
            resolved_runner = Path("/tmp/fake-business-runner.py")

            with (
                patch.object(ROUTER, "resolve_runner", return_value=resolved_runner) as resolve_runner,
                patch.object(ROUTER.runpy, "run_path") as run_path,
                patch.object(sys, "argv", ["s1parse_router.py", str(manifest_path)]),
            ):
                ROUTER.main()
                self.assertEqual(sys.argv, [str(resolved_runner), str(manifest_path.resolve())])

        resolve_runner.assert_called_once_with(manifest_path.resolve())
        run_path.assert_called_once_with(str(resolved_runner), run_name="__main__")

    def test_main_dispatches_business_stage_to_resolved_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = self.write_manifest(Path(tmp), {"parseProfile": "business", "documents": []})
            resolved_runner = Path("/tmp/fake-business-runner.py")

            with (
                patch.object(ROUTER, "resolve_runner", return_value=resolved_runner) as resolve_runner,
                patch.object(ROUTER.runpy, "run_path") as run_path,
                patch.object(sys, "argv", ["s1parse_router.py", "finalize", str(manifest_path)]),
            ):
                ROUTER.main()
                self.assertEqual(sys.argv, [str(resolved_runner), "finalize", str(manifest_path.resolve())])

        resolve_runner.assert_called_once_with(manifest_path.resolve())
        run_path.assert_called_once_with(str(resolved_runner), run_name="__main__")

    def test_main_dispatches_business_navigation_extra_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = self.write_manifest(Path(tmp), {"parseProfile": "business", "documents": []})
            resolved_runner = Path("/tmp/fake-business-runner.py")

            with (
                patch.object(ROUTER, "resolve_runner", return_value=resolved_runner) as resolve_runner,
                patch.object(ROUTER.runpy, "run_path") as run_path,
                patch.object(
                    sys,
                    "argv",
                    ["s1parse_router.py", "search", str(manifest_path), "递交截止", "--limit", "5"],
                ),
            ):
                ROUTER.main()
                self.assertEqual(
                    sys.argv,
                    [str(resolved_runner), "search", str(manifest_path.resolve()), "递交截止", "--limit", "5"],
                )

        resolve_runner.assert_called_once_with(manifest_path.resolve())
        run_path.assert_called_once_with(str(resolved_runner), run_name="__main__")

    def test_main_dispatches_business_submit_extra_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = self.write_manifest(Path(tmp), {"parseProfile": "business", "documents": []})
            resolved_runner = Path("/tmp/fake-business-runner.py")
            submitted_json = '[{"key":"projectName","value":"测试项目","evidenceIds":["DOC-1:B000001"]}]'

            with (
                patch.object(ROUTER, "resolve_runner", return_value=resolved_runner) as resolve_runner,
                patch.object(ROUTER.runpy, "run_path") as run_path,
                patch.object(
                    sys,
                    "argv",
                    ["s1parse_router.py", "submit", str(manifest_path), "projectBasics", submitted_json],
                ),
            ):
                ROUTER.main()
                self.assertEqual(
                    sys.argv,
                    [str(resolved_runner), "submit", str(manifest_path.resolve()), "projectBasics", submitted_json],
                )

        resolve_runner.assert_called_once_with(manifest_path.resolve())
        run_path.assert_called_once_with(str(resolved_runner), run_name="__main__")

    def test_main_rejects_stage_for_technical_runner_with_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = self.write_manifest(Path(tmp), {"parseProfile": "technical", "documents": []})
            stderr = io.StringIO()

            with (
                patch.object(sys, "argv", ["s1parse_router.py", "finalize", str(manifest_path)]),
                redirect_stderr(stderr),
                self.assertRaises(SystemExit) as raised,
            ):
                ROUTER.main()

        self.assertEqual(raised.exception.code, 64)
        self.assertIn("stage argument is only supported for business s1parse", stderr.getvalue())

    def test_docker_s1parse_wrapper_forwards_agentic_commands(self) -> None:
        dockerfile = ROUTER_PATH.parents[1] / "Dockerfile"

        content = dockerfile.read_text(encoding="utf-8")

        self.assertIn('if [ "$#" -lt 1 ]; then', content)
        self.assertIn(
            "usage: s1parse [prepare|overview|search|read|table|window|submit|status|validate|finalize] <manifest> [...]",
            content,
        )
        self.assertIn('exec python3 /workspace/.opencode/skills/s1parse_router.py "$@"', content)

    def test_opencode_docker_context_excludes_legacy_skill_snapshots(self) -> None:
        dockerignore = ROUTER_PATH.parents[1] / ".dockerignore"

        content = dockerignore.read_text(encoding="utf-8")

        self.assertIn("skill/skill-*", content)

    def test_opencode_config_denies_task_tool_delegation(self) -> None:
        config_path = ROUTER_PATH.parents[1] / "opencode.json"

        config = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(config["permission"]["task"], "deny")
        self.assertEqual(config["permission"]["read"], "deny")

    def test_opencode_config_allows_headless_data_volumes(self) -> None:
        config_path = ROUTER_PATH.parents[1] / "opencode.json"

        config = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(
            config["permission"]["external_directory"],
            {
                "/data/parsed/**": "allow",
                "/data/documents/**": "allow",
                "/data/uploads/**": "allow",
                "/tmp/**": "allow",
            },
        )

    def test_opencode_runtime_config_denies_task_tool_delegation(self) -> None:
        config = system_settings_service._opencode_runtime_config(
            {
                "providerId": "mimo",
                "modelId": "demo-model",
                "baseUrl": "https://llm.example.com/v1",
            }
        )

        self.assertEqual(config["permission"]["task"], "deny")
        self.assertEqual(config["permission"]["read"], "deny")

    def test_opencode_runtime_config_allows_headless_data_volumes(self) -> None:
        config = system_settings_service._opencode_runtime_config(
            {
                "providerId": "mimo",
                "modelId": "demo-model",
                "baseUrl": "https://llm.example.com/v1",
            }
        )

        self.assertEqual(
            config["permission"]["external_directory"],
            {
                "/data/parsed/**": "allow",
                "/data/documents/**": "allow",
                "/data/uploads/**": "allow",
                "/tmp/**": "allow",
            },
        )

    def test_opencode_entrypoint_generated_runtime_config_denies_read_tool(self) -> None:
        entrypoint = ROUTER_PATH.parents[1] / "docker-entrypoint.sh"

        content = entrypoint.read_text(encoding="utf-8")

        self.assertIn('"task": "deny"', content)
        self.assertIn('"read": "deny"', content)

    def test_opencode_entrypoint_generated_runtime_config_allows_headless_data_volumes(self) -> None:
        entrypoint = ROUTER_PATH.parents[1] / "docker-entrypoint.sh"

        content = entrypoint.read_text(encoding="utf-8")

        self.assertIn('"/data/parsed/**": "allow"', content)
        self.assertIn('"/data/documents/**": "allow"', content)
        self.assertIn('"/data/uploads/**": "allow"', content)
        self.assertIn('"/tmp/**": "allow"', content)

    def test_opencode_entrypoint_merges_external_directory_permissions_into_existing_runtime_config(self) -> None:
        entrypoint = ROUTER_PATH.parents[1] / "docker-entrypoint.sh"

        content = entrypoint.read_text(encoding="utf-8")

        self.assertIn("write_effective_config()", content)
        self.assertIn("write_effective_config \"${RUNTIME_CONFIG_PATH}\"", content)
        self.assertIn('export OPENCODE_CONFIG="${EFFECTIVE_CONFIG_PATH}"', content)
        self.assertNotIn('export OPENCODE_CONFIG="${RUNTIME_CONFIG_PATH}"', content)

    def test_opencode_entrypoint_effective_config_preserves_existing_runtime_and_adds_data_volume_allowlist(self) -> None:
        entrypoint = ROUTER_PATH.parents[1] / "docker-entrypoint.sh"
        entrypoint_text = entrypoint.read_text(encoding="utf-8")
        heredoc_start = entrypoint_text.index("python3 - \"$1\" \"${EFFECTIVE_CONFIG_PATH}\" <<'PY'\n")
        heredoc_start = entrypoint_text.index("\n", heredoc_start) + 1
        heredoc_end = entrypoint_text.index("\nPY\n}", heredoc_start)
        merge_script = entrypoint_text[heredoc_start:heredoc_end]

        source_payload = json.dumps(
            {
                "$schema": "https://opencode.ai/config.json",
                "model": "mimo/demo-model",
                "permission": {
                    "bash": "allow",
                    "external_directory": {
                        "/already/allowed/**": "allow",
                    },
                },
            },
            ensure_ascii=False,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "runtime.json"
            target = root / "effective.json"
            source.write_text(source_payload, encoding="utf-8")

            subprocess.run(
                [sys.executable, "-c", merge_script, str(source), str(target)],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            effective = json.loads(target.read_text(encoding="utf-8"))

        self.assertEqual(effective["model"], "mimo/demo-model")
        self.assertEqual(effective["permission"]["bash"], "allow")
        self.assertEqual(effective["permission"]["external_directory"]["/already/allowed/**"], "allow")
        self.assertEqual(effective["permission"]["external_directory"]["/data/parsed/**"], "allow")
        self.assertEqual(effective["permission"]["external_directory"]["/data/documents/**"], "allow")
        self.assertEqual(effective["permission"]["external_directory"]["/data/uploads/**"], "allow")
        self.assertEqual(effective["permission"]["external_directory"]["/tmp/**"], "allow")
