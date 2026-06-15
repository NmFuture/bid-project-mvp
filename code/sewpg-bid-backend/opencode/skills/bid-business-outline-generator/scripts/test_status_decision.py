import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import status_decision as status


class StatusDecisionTest(unittest.TestCase):
    def test_strong_current_format_or_high_value_evidence_suggests_necessary(self):
        section = {"id": "sec-1", "title": "投标保证金承诺函", "level": 2}
        candidate = {
            "scope": "high_value_area",
            "evidence_strength": "strong",
            "evidence_category": "bid_bond",
            "source_kind": "table_cell",
            "source_ref": {"source_file": "招标文件.docx", "block_id": "b-1"},
        }

        decision = status.decide_required_status(section, [candidate])

        self.assertNotIn("required_status", decision)
        self.assertEqual(decision["suggested_required_status"], "必要")
        self.assertEqual(decision["evidence_scope"], "high_value_area")
        self.assertEqual(decision["evidence_strength"], "strong")
        self.assertIn("high_value_area", decision["suggested_reason"])
        self.assertIn("bid_bond", decision["suggested_reason"])

    def test_weak_reference_and_history_fallback_suggest_pending_with_reason(self):
        weak = status.decide_required_status(
            {"id": "sec-1", "title": "授权委托书", "level": 2},
            [{"scope": "broad_clause", "evidence_strength": "weak", "match_reason": "纯引用句"}],
        )
        fallback = status.decide_required_status(
            {"id": "sec-2", "title": "历史保留项", "level": 2},
            [{"scope": "history_fallback", "evidence_strength": "fallback"}],
        )

        self.assertNotIn("required_status", weak)
        self.assertNotIn("required_status", fallback)
        self.assertEqual(weak["suggested_required_status"], "待确认")
        self.assertEqual(fallback["suggested_required_status"], "待确认")
        self.assertIn("弱证据", weak["suggested_reason"])
        self.assertIn("历史目录", fallback["suggested_reason"])

    def test_child_can_inherit_parent_format_scope_as_medium_suggestion(self):
        decision = status.decide_required_status(
            {"id": "sec-child", "title": "企业规模", "level": 3},
            [],
            parent_decision={
                "evidence_scope": "format_area",
                "evidence_strength": "strong",
                "evidence_category": "format_appendix",
            },
        )

        self.assertNotIn("required_status", decision)
        self.assertEqual(decision["suggested_required_status"], "待确认")
        self.assertEqual(decision["evidence_scope"], "parent_context")
        self.assertEqual(decision["evidence_strength"], "medium")
        self.assertIn("继承父项", decision["suggested_reason"])


if __name__ == "__main__":
    unittest.main()
