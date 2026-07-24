from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path

try:
    import pytest
except ModuleNotFoundError:  # pragma: no cover - local lightweight fallback
    class _PytestMark:
        def integration(self, obj):
            return obj

        def skipif(self, *_args, **_kwargs):
            def decorator(obj):
                return obj

            return decorator

    class _PytestFallback:
        mark = _PytestMark()

    pytest = _PytestFallback()


COMPOSE_FILE = Path(__file__).resolve().parents[2] / "docker-compose.yml"


@unittest.skipUnless(os.getenv("BID_RUN_INTEGRATION") == "1", "requires running opencode container")
@pytest.mark.integration
@pytest.mark.skipif(os.getenv("BID_RUN_INTEGRATION") != "1", reason="requires running opencode container")
class WikibuildContainerIntegrationTests(unittest.TestCase):
    def test_business_manifest_routes_to_business_wiki_runner_inside_opencode_container(self) -> None:
        container_script = """
import json
import subprocess
from pathlib import Path

root = Path("/tmp/wikibuild-business-test")
root.mkdir(parents=True, exist_ok=True)
manifest_path = root / "manifest.json"
output_path = root / "wiki_blueprint.json"
manifest = {
    "targetBidType": "商务标",
    "rootTitle": "商务标Wiki（自动生成）",
    "workDir": str(root),
    "outputFile": str(output_path),
    "materialInventory": {"items": [], "total": 0},
}
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
completed = subprocess.run(
    ["/usr/local/bin/wikibuild", str(manifest_path)],
    check=True,
    capture_output=True,
    text=True,
    encoding="utf-8",
)
response = json.loads(completed.stdout)
blueprint = json.loads(output_path.read_text(encoding="utf-8"))
nodes = blueprint.get("nodes") or []
cards_node = nodes[2] if len(nodes) > 2 and isinstance(nodes[2], dict) else {}
print(json.dumps({
    "response": response,
    "blueprintRootTitle": blueprint.get("rootTitle"),
    "blueprintNodeTitles": [node.get("title") for node in nodes if isinstance(node, dict)],
    "cardChildren": [node.get("title") for node in (cards_node.get("children") or []) if isinstance(node, dict)],
}, ensure_ascii=False))
""".strip()

        completed = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(COMPOSE_FILE),
                "exec",
                "-T",
                "opencode",
                "python3",
                "-c",
                container_script,
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        payload = json.loads(completed.stdout.strip())
        response = payload["response"]

        self.assertEqual(response["skill"], "bid-business-wiki-material-builder")
        self.assertEqual(
            response["nodeTitles"],
            [
                "01-素材总表",
                "02-模板模块映射表",
                "03-证据卡片",
                "04-待填写与待确认清单",
                "05-使用规则",
            ],
        )
        self.assertEqual(payload["blueprintRootTitle"], "商务标Wiki（自动生成）")
        self.assertEqual(payload["blueprintNodeTitles"], response["nodeTitles"])
        self.assertEqual(payload["cardChildren"], ["通用素材", "客户素材", "项目素材"])
