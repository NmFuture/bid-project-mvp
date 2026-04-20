from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services.opencode_client import OpencodeClient


class OpencodeClientTests(unittest.TestCase):
    def test_extract_outline_json_repairs_invalid_json_once(self) -> None:
        client = OpencodeClient()
        response = {
            "parts": [
                {
                    "type": "text",
                    "text": '{"summary":"目录生成完成","nodes":[{"id":"OL-1","title":"项目概况","children":[],}]}',
                }
            ]
        }

        with patch.object(
            client,
            "_repair_json_payload",
            return_value='{"summary":"目录生成完成","nodes":[{"id":"OL-1","title":"项目概况","children":[]}]}',
        ) as repair:
            parsed = client._extract_outline_json(response)

        repair.assert_called_once()
        self.assertEqual(parsed["summary"], "目录生成完成")
        self.assertEqual(parsed["nodes"][0]["title"], "项目概况")

    def test_extract_outline_json_promotes_repair_failure(self) -> None:
        client = OpencodeClient()
        response = {
            "parts": [
                {
                    "type": "text",
                    "text": "{invalid json}",
                }
            ]
        }

        with patch.object(
            client,
            "_repair_json_payload",
            side_effect=RuntimeError("修复失败"),
        ) as repair:
            with self.assertRaises(RuntimeError) as context:
                client._extract_outline_json(response)

        repair.assert_called_once()
        self.assertIn("opencode JSON 解析失败", str(context.exception))
