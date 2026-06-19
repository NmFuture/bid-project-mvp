from __future__ import annotations

import json
import unittest

from app.services.technical_wiki_preview_prompt import (
    PREVIEW_BATCH_SIZE,
    PREVIEW_SCHEMA_VERSION,
    build_batch_preview_prompt,
    build_preview_prompt,
    parse_batch_preview_reply,
    parse_preview_reply,
)


def _loader(text: str) -> dict:
    """简易 json_loader：剥代码块后 json.loads，模拟 OpencodeClient._parse_json_payload。"""
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        cleaned = cleaned.rsplit("```", 1)[0].strip()
    return json.loads(cleaned)


PROFILE = {
    "headings": [{"level": 1, "title": "总体方案"}, {"level": 2, "title": "供货范围"}],
    "paragraphs": ["本机组适用于低温环境。", "额定功率 5.0MW。"],
    "tableCount": 1,
}


class PreviewPromptModuleTests(unittest.TestCase):
    def test_constants_exposed(self) -> None:
        self.assertIsInstance(PREVIEW_SCHEMA_VERSION, int)
        self.assertIsInstance(PREVIEW_BATCH_SIZE, int)
        self.assertGreaterEqual(PREVIEW_BATCH_SIZE, 1)

    def test_build_preview_prompt_contains_context(self) -> None:
        prompt = build_preview_prompt("总体方案.docx", "技术标/标准文件/EW5.0/总体方案.docx", "标准文件", PROFILE)
        self.assertIn("总体方案.docx", prompt)
        self.assertIn("技术标/标准文件/EW5.0/总体方案.docx", prompt)
        self.assertIn("标准文件", prompt)
        self.assertIn("供货范围", prompt)  # heading 树
        self.assertIn("额定功率 5.0MW", prompt)  # 正文摘录
        self.assertIn("严格 JSON", prompt)

    def test_parse_preview_reply_normal_and_clip(self) -> None:
        reply = json.dumps(
            {
                "lead": "L" * 200,  # 超长，应裁到 120
                "points": ["a", "b", "c", "d", "e", "f", "g"],  # 超 5 条
                "keyParams": [{"label": "功率", "value": "5.0MW"}, {"bad": 1}],
                "retrievalHints": ["低温", "5MW", "", "海上"],
            }
        )
        preview = parse_preview_reply(reply, _loader)
        self.assertIsNotNone(preview)
        self.assertEqual(len(preview["lead"]), 120)
        self.assertEqual(len(preview["points"]), 5)
        self.assertEqual(preview["keyParams"], [{"label": "功率", "value": "5.0MW"}])
        self.assertEqual(preview["retrievalHints"], ["低温", "5MW", "海上"])

    def test_parse_preview_reply_empty_and_invalid(self) -> None:
        self.assertIsNone(parse_preview_reply("", _loader))
        self.assertIsNone(parse_preview_reply("not json at all", _loader))
        # lead 与 points 都空 -> 视为无效
        self.assertIsNone(parse_preview_reply(json.dumps({"lead": "", "points": []}), _loader))

    def test_parse_preview_reply_strips_code_fence(self) -> None:
        reply = "```json\n" + json.dumps({"lead": "导读", "points": ["要点"]}) + "\n```"
        preview = parse_preview_reply(reply, _loader)
        self.assertEqual(preview["lead"], "导读")

    def test_build_batch_prompt_contains_all_file_ids(self) -> None:
        items = [
            {"fileId": "RAW-0002", "name": "a.docx", "path": "p/a.docx", "tier_label": "标准文件", "profile": PROFILE},
            {"fileId": "RAW-0007", "name": "b.docx", "path": "p/b.docx", "tier_label": "客户定制", "profile": PROFILE},
        ]
        prompt = build_batch_preview_prompt(items)
        self.assertIn("RAW-0002", prompt)
        self.assertIn("RAW-0007", prompt)
        self.assertIn("previews", prompt)

    def test_parse_batch_splits_by_file_id(self) -> None:
        reply = json.dumps(
            {
                "previews": {
                    "RAW-0002": {"lead": "导读A", "points": ["A1"]},
                    "RAW-0007": {"lead": "导读B", "points": ["B1", "B2"]},
                }
            }
        )
        out = parse_batch_preview_reply(reply, _loader)
        self.assertEqual(set(out.keys()), {"RAW-0002", "RAW-0007"})
        self.assertEqual(out["RAW-0002"]["lead"], "导读A")
        self.assertEqual(out["RAW-0007"]["points"], ["B1", "B2"])

    def test_parse_batch_bad_one_does_not_drop_others(self) -> None:
        reply = json.dumps(
            {
                "previews": {
                    "RAW-0002": {"lead": "好的", "points": ["x"]},
                    "RAW-0003": {"lead": "", "points": []},  # 无效，应被丢弃
                }
            }
        )
        out = parse_batch_preview_reply(reply, _loader)
        self.assertIn("RAW-0002", out)
        self.assertNotIn("RAW-0003", out)

    def test_parse_batch_missing_file_absent_from_result(self) -> None:
        # 模型只回了部分 fileId：缺的不应出现在结果里（上层据此标 failed）。
        reply = json.dumps({"previews": {"RAW-0002": {"lead": "只有这个", "points": ["x"]}}})
        out = parse_batch_preview_reply(reply, _loader)
        self.assertEqual(set(out.keys()), {"RAW-0002"})

    def test_parse_batch_invalid_returns_empty(self) -> None:
        self.assertEqual(parse_batch_preview_reply("", _loader), {})
        self.assertEqual(parse_batch_preview_reply("not json", _loader), {})
        self.assertEqual(parse_batch_preview_reply(json.dumps({"nope": 1}), _loader), {})


if __name__ == "__main__":
    unittest.main()
