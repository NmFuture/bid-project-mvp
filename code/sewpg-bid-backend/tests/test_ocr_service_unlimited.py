from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services.ocr_service import ocr_service


class UnlimitedOcrServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_unlimited_ocr_image_request_uses_required_recipe(self) -> None:
        captured = {}

        async def fake_post(*_args, **kwargs):
            captured.update(kwargs)

            class Response:
                status_code = 200

                @staticmethod
                def json():
                    return {
                        "choices": [
                            {
                                "message": {
                                    "content": "<|ref|>Project: Wind Farm<|/ref|><|det|>[[1,2,3,4]]<|/det|>"
                                }
                            }
                        ]
                    }

            return Response()

        config = {
            "baseUrl": "http://unlimited-ocr:8000/v1",
            "model": "baidu/Unlimited-OCR",
            "timeoutMs": 60000,
            "maxTokens": 8192,
        }
        with patch("httpx.AsyncClient.post", side_effect=fake_post):
            text, raw = await ocr_service._ocr_image(b"\x89PNG\r\n\x1a\nfake", "image/png", config)

        payload = captured["json"]
        self.assertEqual(payload["model"], "baidu/Unlimited-OCR")
        self.assertEqual(payload["messages"][0]["content"][0]["text"], "<image>document parsing.")
        self.assertTrue(payload["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertFalse(payload["skip_special_tokens"])
        self.assertEqual(payload["vllm_xargs"], {"ngram_size": 35, "window_size": 128})
        self.assertNotIn("images_config", payload)
        self.assertNotIn("custom_params", payload)
        self.assertEqual(text, "Project: Wind Farm")
        self.assertGreaterEqual(raw["_latencyMs"], 0)

    async def test_regular_ocr_request_keeps_existing_prompt_shape(self) -> None:
        captured = {}

        async def fake_post(*_args, **kwargs):
            captured.update(kwargs)

            class Response:
                status_code = 200

                @staticmethod
                def json():
                    return {"choices": [{"message": {"content": "Project: Wind Farm"}}]}

            return Response()

        config = {
            "baseUrl": "http://deepseek-ocr:8000/v1",
            "model": "deepseek-ai/DeepSeek-OCR",
            "timeoutMs": 60000,
            "maxTokens": 2048,
        }
        with patch("httpx.AsyncClient.post", side_effect=fake_post):
            text, _ = await ocr_service._ocr_image(b"\x89PNG\r\n\x1a\nfake", "image/png", config)

        payload = captured["json"]
        self.assertEqual(payload["messages"][0]["content"][0]["type"], "image_url")
        self.assertEqual(payload["messages"][0]["content"][1], {"type": "text", "text": "Free OCR."})
        self.assertNotIn("skip_special_tokens", payload)
        self.assertNotIn("vllm_xargs", payload)
        self.assertEqual(text, "Project: Wind Farm")


if __name__ == "__main__":
    unittest.main()
