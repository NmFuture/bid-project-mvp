"""被父章覆盖的子级保留自身候选素材（S3 树状改造·释放预备）单测。

S3 页面改造后，父章被人工「忽略」时子级要立刻按自身候选派生标签，
不重跑缺口识别。因此 planner 在覆盖分支不再输出空 candidateMaterials，
而是保留子级自己的候选（含展示分）；覆盖期间 matchedMaterials 仍为空、
覆盖字段语义不变。fixture 为脱敏合成素材，不含真实项目/客户/数据。
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

_SRC = (
    Path(__file__).resolve().parents[1]
    / "opencode"
    / "skills"
    / "bid-tech-gap-planner"
    / "scripts"
    / "run_from_manifest.py"
)
_SPEC = importlib.util.spec_from_file_location("tech_gap_covered_child_under_test", _SRC)
planner = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(planner)

_ROOT = "技术标/通用素材/示例"


def _toc_items() -> list[dict]:
    """第6章有整章正文素材；6.2.2 另有一份名称包含其标题的素材（非剥修饰同名，
    不触发同名夺回），应保持被覆盖且候选非空。"""
    rows = [
        ("第6章", "产品交付、考核及验收", 1),
        ("6.1", "技术资料和交付进度", 2),
        ("6.2", "试验和监造安排", 2),
        ("6.2.1", "我公司实施的试验和检验", 3),
        ("6.2.2", "型式试验报告", 3),
    ]
    return [
        {"order": i, "number": number, "title": title, "level": level, "material_refs": []}
        for i, (number, title, level) in enumerate(rows, start=1)
    ]


def _material_index() -> list[dict]:
    return [
        {
            "id": "M-CHAPTER-DOC",
            "name": "产品交付、考核及验收.docx",
            "folderPath": f"{_ROOT}/客户定制",
            "materialTier": "customer",
        },
        {
            "id": "M-CHILD-DOC",
            "name": "型式试验报告汇总.docx",
            "folderPath": f"{_ROOT}/专题",
            "materialTier": "standard",
        },
    ]


def _build_plan() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        toc_path = work / "toc.json"
        toc_path.write_text(
            json.dumps({"schema_version": "toc-v1", "items": _toc_items()}, ensure_ascii=False),
            encoding="utf-8",
        )
        parse_path = work / "parse_result.json"
        parse_path.write_text(json.dumps({}, ensure_ascii=False), encoding="utf-8")
        manifest = {
            "projectId": "PRJ-TEST",
            "bidType": "technical",
            "workDir": str(work),
            "tocJsonPath": str(toc_path),
            "parseResultPath": str(parse_path),
            "wikiDir": "",
            "materialIndex": _material_index(),
            "materialScope": {"readableScopes": [{"path": _ROOT}]},
        }
        return planner.build_gap_plan(manifest)


class CoveredChildCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        plan = _build_plan()
        self.plan = plan
        self.items = {str(item.get("number")): item for item in plan["items"]}

    def test_plan_keeps_all_toc_items(self) -> None:
        self.assertEqual(len(self.plan["items"]), len(_toc_items()))

    def test_child_stays_covered_with_empty_matched(self) -> None:
        chapter_id = str(self.items["第6章"].get("id"))
        child = self.items["6.2.2"]
        self.assertEqual(child.get("coverageRole"), "covered_by_parent")
        self.assertEqual(child.get("coveredByParent"), chapter_id)
        self.assertEqual(child.get("matchedMaterials"), [])

    def test_covered_child_keeps_own_candidates_with_score(self) -> None:
        child = self.items["6.2.2"]
        candidates = child.get("candidateMaterials") or []
        names = [str(m.get("name") or "") for m in candidates]
        self.assertIn("型式试验报告汇总.docx", names)
        for material in candidates:
            self.assertGreater(float(material.get("matchScore") or 0), 0)

    def test_covered_child_without_material_keeps_empty_candidates(self) -> None:
        # 没有任何可召回素材的子级，候选保持为空（释放后落「待人工补充」）。
        child = self.items["6.2.1"]
        self.assertEqual(child.get("coverageRole"), "covered_by_parent")
        self.assertEqual(child.get("candidateMaterials") or [], [])


if __name__ == "__main__":
    unittest.main()
