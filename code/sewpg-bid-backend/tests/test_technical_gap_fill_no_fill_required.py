"""填写质量门 no_fill_required 终态单测。

金标反评定位：招标原文已写满的附表（如 B.1.2 机型配置品牌表1）走完流程填 0 格，
按覆盖率被判 needs_review，混进缺口统计成为假缺口。空白模板自身没有待填单元格时
填 0 格是正确终态，应与 passed 同等放行。
"""
from __future__ import annotations

import unittest

from app.services.technical_gap_ai_fill import _build_fill_quality_report
from app.services.technical_gap_domain import (
    FILL_QUALITY_ACCEPTED_STATUSES,
    technical_gap_artifact_is_s7_ready,
)


def _result(*, no_fill_required: bool, filled: int, target: int, unfilled: int = 0) -> dict:
    return {
        "unfilledFields": [],
        # evidenceChainRate = len(evidenceRefs)/filled，需与已填格数同量级才过 0.85 门
        "evidenceRefs": [{"type": "selected_fact", "field": f"F{i}"} for i in range(filled)]
        + [{"type": "blank_source", "path": "x.docx"}],
        "fillReport": {
            "filledFieldCount": filled,
            "unfilledFieldCount": unfilled,
            "targetFieldCount": target,
            "noFillRequired": no_fill_required,
            "sourceCoverage": {"ruleSources": ["招标文件内容"], "ruleSourceSufficient": False},
        },
    }


class NoFillRequiredQualityGateTests(unittest.TestCase):
    def test_no_fill_required_status(self) -> None:
        report = _build_fill_quality_report(
            _result(no_fill_required=True, filled=0, target=0),
            output_exists=True,
        )
        self.assertEqual(report["status"], "no_fill_required")
        self.assertTrue(report["noFillRequired"])
        # 覆盖情况透出给业务判断规则是否需要补来源
        self.assertEqual(report["sourceCoverage"]["ruleSources"], ["招标文件内容"])

    def test_missing_output_is_not_no_fill_required(self) -> None:
        report = _build_fill_quality_report(
            _result(no_fill_required=True, filled=0, target=0),
            output_exists=False,
        )
        self.assertEqual(report["status"], "needs_review")

    def test_partially_filled_table_still_needs_review(self) -> None:
        # 有待填单元格但没填满：runner 不会置 noFillRequired，仍走覆盖率判定
        report = _build_fill_quality_report(
            _result(no_fill_required=False, filled=9, target=168, unfilled=159),
            output_exists=True,
        )
        self.assertEqual(report["status"], "needs_review")
        self.assertFalse(report["noFillRequired"])

    def test_filled_table_not_downgraded(self) -> None:
        report = _build_fill_quality_report(
            _result(no_fill_required=False, filled=30, target=30),
            output_exists=True,
        )
        self.assertEqual(report["status"], "passed")

    def test_no_fill_required_artifact_is_s7_ready(self) -> None:
        artifact = {"source": "ai_fill", "qualityReport": {"status": "no_fill_required"}}
        self.assertTrue(technical_gap_artifact_is_s7_ready(artifact))
        self.assertIn("no_fill_required", FILL_QUALITY_ACCEPTED_STATUSES)

    def test_needs_review_artifact_blocks_s7(self) -> None:
        artifact = {"source": "ai_fill", "qualityReport": {"status": "needs_review"}}
        self.assertFalse(technical_gap_artifact_is_s7_ready(artifact))


if __name__ == "__main__":
    unittest.main()
