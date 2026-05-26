from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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
            manifest_path = self.write_manifest(
                Path(tmp),
                {
                    "bidType": "商务标",
                    "documents": [],
                },
            )
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
