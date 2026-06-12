"""Tests for the optional AI-judge layer in bid-tech-outline-generator.

The judge is a post-filter on the rule-based TOC items: when
``OUTLINE_JUDGE_ENABLED=true`` plus endpoint env vars are set, the skill
posts the items to an OpenAI-compatible chat API and drops items the LLM
flags as noise. The rule-based output remains authoritative on shape and
numbering — the LLM can only DROP, never add or modify.

These tests pin the contract so future changes can't silently disable the
guardrails or let a hallucinating LLM corrupt the TOC."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

OUTLINE_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "opencode" / "skills" / "bid-tech-outline-generator"
    / "scripts" / "run_from_manifest.py"
)


def load_outline_runner():
    spec = importlib.util.spec_from_file_location("outline_run_from_manifest", OUTLINE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["outline_run_from_manifest"] = module
    spec.loader.exec_module(module)
    return module


SAMPLE_ITEMS = [
    {"number": "第1章", "title": "项目概况",         "level": 1, "annotation": "保留"},
    {"number": "1.1",   "title": "项目背景",         "level": 2, "annotation": "保留"},
    {"number": "",      "title": "216",              "level": 2, "annotation": "新增-副表"},
    {"number": "",      "title": "367",              "level": 2, "annotation": "新增-副表"},
    {"number": "附表A.1","title": "投标机型总方案",   "level": 1, "annotation": "新增-副表"},
]


def _ok_chat_completion(verdicts: list[dict]) -> dict:
    """Shape an OpenAI-compatible chat-completion response with a JSON verdict array as content."""
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps(verdicts, ensure_ascii=False),
                }
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "completion_tokens_details": {"reasoning_tokens": 30}},
    }


class JudgeConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = load_outline_runner()
        # Drop any pre-existing OUTLINE_JUDGE_* vars from the host environment
        # so each test starts from a clean slate.
        for key in [k for k in os.environ if k.startswith("OUTLINE_JUDGE_")]:
            os.environ.pop(key, None)

    def test_judge_disabled_by_default(self) -> None:
        self.assertIsNone(self.runner._judge_config_from_env())

    def test_judge_disabled_when_partial_config(self) -> None:
        # Only enabled flag, no endpoint -> still treated as disabled
        os.environ["OUTLINE_JUDGE_ENABLED"] = "true"
        self.assertIsNone(self.runner._judge_config_from_env())

        os.environ["OUTLINE_JUDGE_BASE_URL"] = "https://api.example.com/v1"
        # Still missing api_key + model
        self.assertIsNone(self.runner._judge_config_from_env())

    def test_judge_enabled_with_full_config(self) -> None:
        os.environ.update({
            "OUTLINE_JUDGE_ENABLED": "true",
            "OUTLINE_JUDGE_BASE_URL": "https://api.example.com/v1",
            "OUTLINE_JUDGE_API_KEY": "sk-test",
            "OUTLINE_JUDGE_MODEL": "Pro/moonshotai/Kimi-K2.6",
            "OUTLINE_JUDGE_TIMEOUT_SEC": "300",
        })
        cfg = self.runner._judge_config_from_env()
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg["model"], "Pro/moonshotai/Kimi-K2.6")
        self.assertEqual(cfg["timeout_s"], 300)

    def test_judge_timeout_clamped(self) -> None:
        os.environ.update({
            "OUTLINE_JUDGE_ENABLED": "true",
            "OUTLINE_JUDGE_BASE_URL": "https://api.example.com/v1",
            "OUTLINE_JUDGE_API_KEY": "sk-test",
            "OUTLINE_JUDGE_MODEL": "m",
            "OUTLINE_JUDGE_TIMEOUT_SEC": "99999",  # absurd
        })
        cfg = self.runner._judge_config_from_env()
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg["timeout_s"], 1800)  # clamped to upper bound


class JudgeApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = load_outline_runner()
        self.tmp = tempfile.TemporaryDirectory()
        self.work_dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        for key in [k for k in os.environ if k.startswith("OUTLINE_JUDGE_")]:
            os.environ.pop(key, None)

    def _enable_judge(self) -> None:
        os.environ.update({
            "OUTLINE_JUDGE_ENABLED": "true",
            "OUTLINE_JUDGE_BASE_URL": "https://api.example.com/v1",
            "OUTLINE_JUDGE_API_KEY": "sk-test",
            "OUTLINE_JUDGE_MODEL": "Pro/moonshotai/Kimi-K2.6",
        })

    def test_judge_disabled_returns_items_unchanged(self) -> None:
        items_in = list(SAMPLE_ITEMS)
        items_out, review = self.runner._apply_outline_judge(items_in, self.work_dir)

        self.assertEqual(items_out, items_in)
        self.assertEqual(review["status"], "disabled")
        self.assertEqual(review["dropped_item_count"], 0)
        # audit file is still written so reviewers can see judge was off
        self.assertTrue((self.work_dir / "outline_judge_review.json").exists())

    def test_judge_drops_flagged_items(self) -> None:
        self._enable_judge()
        verdicts = [
            {"index": 0, "verdict": "KEEP", "reason": "real chapter"},
            {"index": 1, "verdict": "KEEP", "reason": "real section"},
            {"index": 2, "verdict": "DROP", "reason": "table cell numeric noise"},
            {"index": 3, "verdict": "DROP", "reason": "table cell numeric noise"},
            {"index": 4, "verdict": "KEEP", "reason": "real appendix"},
        ]
        with patch.object(self.runner, "_run_outline_judge", return_value={
            "verdicts": verdicts, "elapsed_s": 1.2, "model": "Pro/moonshotai/Kimi-K2.6",
            "raw_content": json.dumps(verdicts), "prompt_tokens": 100, "completion_tokens": 50,
        }):
            items_out, review = self.runner._apply_outline_judge(list(SAMPLE_ITEMS), self.work_dir)

        self.assertEqual([it["title"] for it in items_out], ["项目概况", "项目背景", "投标机型总方案"])
        self.assertEqual(review["status"], "applied")
        self.assertEqual(review["dropped_item_count"], 2)
        self.assertEqual(review["kept_item_count"], 3)
        self.assertEqual(
            sorted(d["title"] for d in review["dropped_titles"]),
            ["216", "367"],
        )

    def test_judge_error_falls_back_to_unfiltered_items(self) -> None:
        self._enable_judge()
        with patch.object(self.runner, "_run_outline_judge", side_effect=RuntimeError("boom")):
            items_out, review = self.runner._apply_outline_judge(list(SAMPLE_ITEMS), self.work_dir)

        # Items pass through untouched on error.
        self.assertEqual([it["title"] for it in items_out], [it["title"] for it in SAMPLE_ITEMS])
        self.assertEqual(review["status"], "error")
        self.assertIn("RuntimeError", review["error"])
        self.assertIn("boom", review["error"])

    def test_judge_too_aggressive_is_rejected(self) -> None:
        """A hallucinating model that DROPs more than half the items is treated
        as a misfire — items pass through unchanged. This is the safety net
        that prevents an LLM from accidentally wiping out the TOC."""

        self._enable_judge()
        verdicts = [{"index": i, "verdict": "DROP", "reason": "hallucinated"} for i in range(len(SAMPLE_ITEMS))]
        with patch.object(self.runner, "_run_outline_judge", return_value={
            "verdicts": verdicts, "elapsed_s": 1.0, "model": "Pro/moonshotai/Kimi-K2.6",
            "raw_content": json.dumps(verdicts), "prompt_tokens": 100, "completion_tokens": 50,
        }):
            items_out, review = self.runner._apply_outline_judge(list(SAMPLE_ITEMS), self.work_dir)

        # All items survived because the verdict was rejected
        self.assertEqual(len(items_out), len(SAMPLE_ITEMS))
        self.assertEqual(review["status"], "rejected_too_aggressive")

    def test_judge_invalid_index_silently_ignored(self) -> None:
        """Indices outside the input list are dropped from consideration so a
        garbage verdict can't reach into the wrong slot."""

        self._enable_judge()
        verdicts = [
            {"index": 999, "verdict": "DROP", "reason": "off the end"},
            {"index": -1, "verdict": "DROP", "reason": "negative"},
            {"index": 2, "verdict": "DROP", "reason": "valid drop"},
        ]
        with patch.object(self.runner, "_run_outline_judge", return_value={
            "verdicts": verdicts, "elapsed_s": 1.0, "model": "m",
            "raw_content": json.dumps(verdicts), "prompt_tokens": 100, "completion_tokens": 50,
        }):
            items_out, review = self.runner._apply_outline_judge(list(SAMPLE_ITEMS), self.work_dir)

        # Only index 2 was actually dropped; out-of-bounds indices ignored.
        self.assertEqual(len(items_out), len(SAMPLE_ITEMS) - 1)
        self.assertNotIn("216", [it["title"] for it in items_out])
        self.assertEqual(review["dropped_item_count"], 1)


class JudgeRoutePersistenceTests(unittest.TestCase):
    """Audit trail must always land at ``outline_judge_review.json`` so a human
    reviewer can see what the LLM did (or that it didn't run)."""

    def setUp(self) -> None:
        self.runner = load_outline_runner()
        self.tmp = tempfile.TemporaryDirectory()
        self.work_dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        for key in [k for k in os.environ if k.startswith("OUTLINE_JUDGE_")]:
            os.environ.pop(key, None)

    def test_persists_disabled_review(self) -> None:
        self.runner._apply_outline_judge(list(SAMPLE_ITEMS), self.work_dir)
        path = self.work_dir / "outline_judge_review.json"
        self.assertTrue(path.exists())
        review = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(review["status"], "disabled")
        self.assertEqual(review["schema_version"], "bid-toc-outline-judge-v1")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
