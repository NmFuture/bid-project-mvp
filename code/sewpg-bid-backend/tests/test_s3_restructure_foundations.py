from __future__ import annotations

import unittest

from app.services.derive_rules import check_numeric_closure, derive_core_facts
from app.services.gap_reviewer import review_fill_instructions
from app.services.kb_schema import KnowledgeLockStatus, card_from_fact_field
from app.services.wiki_health import inspect_wiki_dir


class S3RestructureFoundationTests(unittest.TestCase):
    def test_kb_card_from_confirmed_fact_is_locked(self) -> None:
        card = card_from_fact_field(
            {
                "label": "投标机型",
                "value": "SE-15530",
                "status": "confirmed",
                "confidence": 0.7,
                "sourceRefs": [{"type": "projectTurbineModel", "doc": "机型选择"}],
            }
        )

        self.assertEqual(card.lock_status, KnowledgeLockStatus.LOCKED_BY_USER)
        self.assertTrue(card.is_locked())
        self.assertEqual(card.to_dict()["field"], "投标机型")

    def test_derive_core_facts_computes_total_capacity(self) -> None:
        facts = {"单机容量": "10MW", "机组台数": "12台"}

        derived = derive_core_facts(facts)

        self.assertEqual(derived[0].field, "总装机容量")
        self.assertEqual(derived[0].value, "120")
        self.assertEqual(derived[0].unit, "MW")

    def test_numeric_closure_reports_capacity_mismatch(self) -> None:
        issues = check_numeric_closure({"单机容量": "10MW", "机组台数": "12台", "总装机容量": "130MW"})

        self.assertEqual(issues[0]["check"], "capacity_closure")

    def test_gap_reviewer_detects_cross_ref_model_mismatch(self) -> None:
        report = review_fill_instructions(
            [
                {
                    "doc_type": "appendix",
                    "locator": "附表C/行1",
                    "field_name": "投标机型",
                    "value": "SE-15530",
                    "path": "kb_lookup",
                    "evidence": "机型参数表",
                },
                {
                    "doc_type": "body",
                    "locator": "承诺函",
                    "field_name": "投标机型",
                    "value": "SE-16030",
                    "path": "kb_lookup",
                    "evidence": "承诺函",
                },
            ]
        )

        self.assertEqual(report["status"], "needs_review")
        self.assertTrue(any(item["check"] == "cross_ref" for item in report["issues"]))

    def test_wiki_health_reports_missing_cards(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            wiki_dir = Path(tmp) / "wiki"
            wiki_dir.mkdir()
            (wiki_dir / "rules.md").write_text("rules", encoding="utf-8")
            health = inspect_wiki_dir(wiki_dir)

        self.assertEqual(health.card_count, 0)
        self.assertIn("no_wiki_cards", health.warnings)


if __name__ == "__main__":
    unittest.main()
