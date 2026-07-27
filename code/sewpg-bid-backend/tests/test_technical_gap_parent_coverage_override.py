"""整章覆盖被同名素材夺回时的子节归属（金标反评 R3c）单测。

金标反评发现的失效模式：某小节标题与一份标准文件同名（如「试验、检验和监造」
「项目验收」），该小节把上级整章模板的覆盖夺了回来，并连带把自己的子节一起
接管；但同名只证明这份素材解释得了小节自身，子节的正文实际仍出自上级整章
模板，于是子节被判到一份内容完全对不上的素材。

规则：同名夺回的节点若拿不出标题树覆盖证据，就不向子节延伸覆盖，子节继续
沿用更上一级的覆盖源。fixture 为脱敏合成素材，不含真实项目/客户/数据。
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
_SPEC = importlib.util.spec_from_file_location("tech_gap_parent_coverage_under_test", _SRC)
planner = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(planner)

_ROOT = "技术标/通用素材/示例"


def _toc_items() -> list[dict]:
    """第6章有整章待填写模板；6.2 与一份标准文件同名；6.2.x 是 6.2 的子节。"""
    rows = [
        ("第6章", "产品交付、考核及验收", 1),
        ("6.1", "技术资料和交付进度", 2),
        ("6.2", "试验、检验和监造", 2),
        ("6.2.1", "我公司实施的试验和检验", 3),
        ("6.2.2", "型式试验报告", 3),
        ("6.2.3", "机组全功率试验", 3),
    ]
    return [
        {"order": i, "number": number, "title": title, "level": level, "material_refs": []}
        for i, (number, title, level) in enumerate(rows, start=1)
    ]


def _material_index() -> list[dict]:
    return [
        {
            "id": "M-CHAPTER-TPL",
            "name": "待填写-产品交付、考核及验收.docx",
            "folderPath": f"{_ROOT}/客户定制",
            "materialTier": "customer",
            "requiresFill": True,
        },
        {
            "id": "M-SECTION-NAME",
            "name": "试验、检验和监造.docx",
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


class ParentCoverageOverrideTests(unittest.TestCase):
    def setUp(self) -> None:
        plan = _build_plan()
        self.items = {str(item.get("number")): item for item in plan["items"]}

    def _material_names(self, number: str) -> list[str]:
        item = self.items[number]
        return [str(m.get("name") or "") for m in item.get("matchedMaterials") or []]

    def test_chapter_template_covers_chapter(self) -> None:
        chapter = self.items["第6章"]
        self.assertEqual(chapter.get("coverageRole"), "chapter_master")
        self.assertEqual(self._material_names("第6章"), ["待填写-产品交付、考核及验收.docx"])

    def test_same_name_section_keeps_its_own_match(self) -> None:
        # 同名夺回本身仍然成立：6.2 自己该判给同名素材。
        self.assertEqual(self._material_names("6.2"), ["试验、检验和监造.docx"])
        self.assertEqual(self.items["6.2"].get("coveredByParent"), "")

    def test_children_fall_back_to_chapter_template(self) -> None:
        # 6.2 拿不出标题树证据 → 不接管子节，子节继续由第6章整章模板覆盖。
        chapter_id = str(self.items["第6章"].get("id"))
        for number in ("6.2.1", "6.2.2", "6.2.3"):
            child = self.items[number]
            self.assertEqual(child.get("coverageRole"), "covered_by_parent", number)
            self.assertEqual(child.get("coveredByParent"), chapter_id, number)

    def test_outline_evidence_restores_child_coverage(self) -> None:
        # 反向用例：同名素材的标题树能解释过半子节时，允许它接管子节。
        index = _material_index()
        for material in index:
            if material["id"] == "M-SECTION-NAME":
                material["documentOutline"] = [
                    {"title": "我公司实施的试验和检验"},
                    {"title": "型式试验报告"},
                    {"title": "机组全功率试验"},
                ]
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            toc_path = work / "toc.json"
            toc_path.write_text(
                json.dumps({"schema_version": "toc-v1", "items": _toc_items()}, ensure_ascii=False),
                encoding="utf-8",
            )
            parse_path = work / "parse_result.json"
            parse_path.write_text(json.dumps({}, ensure_ascii=False), encoding="utf-8")
            plan = planner.build_gap_plan(
                {
                    "projectId": "PRJ-TEST",
                    "bidType": "technical",
                    "workDir": str(work),
                    "tocJsonPath": str(toc_path),
                    "parseResultPath": str(parse_path),
                    "wikiDir": "",
                    "materialIndex": index,
                    "materialScope": {"readableScopes": [{"path": _ROOT}]},
                }
            )
        items = {str(item.get("number")): item for item in plan["items"]}
        section_id = str(items["6.2"].get("id"))
        self.assertEqual(items["6.2.2"].get("coveredByParent"), section_id)


if __name__ == "__main__":
    unittest.main()
