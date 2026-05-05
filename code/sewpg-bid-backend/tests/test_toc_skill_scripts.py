from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from openpyxl import Workbook


ASSEMBLER_SCRIPT_DIR = (
    Path(__file__).resolve().parents[1]
    / "opencode"
    / "skill"
    / "bid-tech-assembler"
    / "scripts"
)
OUTLINE_SCRIPT_DIR = (
    Path(__file__).resolve().parents[1]
    / "opencode"
    / "skill"
    / "bid-tech-outline-generator"
    / "scripts"
)
WIKI_SCRIPT_DIR = (
    Path(__file__).resolve().parents[1]
    / "opencode"
    / "skill"
    / "bid-tech-wiki-material-builder"
    / "scripts"
)
GAP_PLANNER_SCRIPT_DIR = (
    Path(__file__).resolve().parents[1]
    / "opencode"
    / "skill"
    / "bid-tech-gap-planner"
    / "scripts"
)
TABLE_FILLER_SCRIPT_DIR = (
    Path(__file__).resolve().parents[1]
    / "opencode"
    / "skill"
    / "bid-tech-table-filler"
    / "scripts"
)
WORD_FILLER_SCRIPT_DIR = (
    Path(__file__).resolve().parents[1]
    / "opencode"
    / "skill"
    / "bid-tech-word-placeholder-filler"
    / "scripts"
)


def load_assembler_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ASSEMBLER_SCRIPT_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_outline_script(name: str):
    module_name = f"outline_{name}"
    spec = importlib.util.spec_from_file_location(module_name, OUTLINE_SCRIPT_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_wiki_script(name: str):
    module_name = f"wiki_{name}"
    spec = importlib.util.spec_from_file_location(module_name, WIKI_SCRIPT_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_gap_planner_script(name: str):
    module_name = f"gap_planner_{name}"
    spec = importlib.util.spec_from_file_location(module_name, GAP_PLANNER_SCRIPT_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_table_filler_script(name: str):
    module_name = f"table_filler_{name}"
    spec = importlib.util.spec_from_file_location(module_name, TABLE_FILLER_SCRIPT_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_word_filler_script(name: str):
    module_name = f"word_filler_{name}"
    spec = importlib.util.spec_from_file_location(module_name, WORD_FILLER_SCRIPT_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def json_load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TocSkillScriptTests(unittest.TestCase):
    def test_bid_gap_planner_routes_fill_template_material_to_ai_fill(self) -> None:
        gap_runner = load_gap_planner_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            toc_path = root / "toc.json"
            parse_path = root / "parse.json"
            toc_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {"number": "第1章", "title": "标前概述", "level": 1},
                            {"number": "1.1", "title": "技术评分标准索引表", "level": 2},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            parse_path.write_text(json.dumps({"structured": {}}, ensure_ascii=False), encoding="utf-8")
            manifest = {
                "projectId": "PRJ-TEST",
                "projectName": "测试项目",
                "bidType": "技术标",
                "tocJsonPath": str(toc_path),
                "parseResultPath": str(parse_path),
                "materialScope": {"paths": ["技术标/客户素材/华能集团"]},
                "projectTurbineModel": {"model": "EW10.0-220上置"},
                "materialIndex": [
                    {
                        "id": "RAW-0453",
                        "name": "待填写-技术评分标准索引表.docx",
                        "folderPath": "技术标/客户素材/华能集团/技术标-标前概述",
                        "materialTier": "customer",
                        "hasCleanedWord": True,
                        "cleanedFileName": "待填写-技术评分标准索引表.docx",
                        "requiresFill": True,
                        "placeholderCount": 3,
                        "placeholderLabels": ["投标机型", "投标方案", "章节索引"],
                    }
                ],
            }

            plan = gap_runner.build_gap_plan(manifest)

        item = next(entry for entry in plan["items"] if entry["number"] == "1.1")
        self.assertEqual(item["decision"], "fill_required")
        self.assertEqual(item["status"], "needs_input")
        self.assertEqual(item["usage"], "section_fill")
        self.assertEqual(item["matchedMaterials"], [])
        self.assertEqual(item["fillTasks"][0]["skill"], "bid-tech-word-placeholder-filler")
        self.assertEqual(item["fillTasks"][0]["blankSource"]["id"], "RAW-0453")
        self.assertEqual(item["fillTasks"][0]["blankSource"]["placeholderCount"], 3)
        self.assertEqual(item["candidateMaterials"][0]["id"], "RAW-0453")

    def test_bid_gap_planner_requires_one_result_per_confirmed_toc_item(self) -> None:
        gap_runner = load_gap_planner_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            toc_path = root / "toc.json"
            parse_path = root / "parse.json"
            toc_items = [
                {"number": "第1章", "title": "标前概述", "level": 1},
                {"number": "1.1", "title": "技术评分标准索引表", "level": 2},
                {"number": "1.2", "title": "与华能集团签署的战略合作协议", "level": 2},
                {"number": "1.3", "title": "缺失专题", "level": 2},
            ]
            toc_path.write_text(json.dumps({"items": toc_items}, ensure_ascii=False), encoding="utf-8")
            parse_path.write_text(json.dumps({"structured": {}}, ensure_ascii=False), encoding="utf-8")
            manifest = {
                "projectId": "PRJ-TEST",
                "projectName": "测试项目",
                "bidType": "技术标",
                "tocJsonPath": str(toc_path),
                "parseResultPath": str(parse_path),
                "materialScope": {"paths": ["技术标/客户素材/华能集团"]},
                "projectTurbineModel": {"model": "EW10.0-220上置"},
                "materialIndex": [
                    {
                        "id": "RAW-0453",
                        "name": "待填写-技术评分标准索引表.docx",
                        "folderPath": "技术标/客户素材/华能集团/技术标-标前概述",
                        "materialTier": "customer",
                        "requiresFill": True,
                        "placeholderCount": 2,
                    },
                    {
                        "id": "RAW-0454",
                        "name": "固定-与华能集团签署的战略合作协议.docx",
                        "folderPath": "技术标/客户素材/华能集团/技术标-标前概述",
                        "materialTier": "customer",
                    },
                ],
            }

            plan = gap_runner.build_gap_plan(manifest)

        self.assertEqual(plan["summary"]["totalTocItems"], len(toc_items))
        self.assertEqual(len(plan["items"]), len(toc_items))
        self.assertEqual([item["number"] for item in plan["items"]], [item["number"] for item in toc_items])
        self.assertEqual(plan["integrity"]["coverageStatus"], "passed")
        self.assertEqual(plan["items"][1]["decision"], "fill_required")
        self.assertEqual(plan["items"][2]["decision"], "ready")
        self.assertEqual(plan["items"][3]["decision"], "material_required")

    def test_bid_gap_planner_carries_parse_fields_to_appendix_tasks(self) -> None:
        gap_runner = load_gap_planner_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            toc_path = root / "toc.json"
            parse_path = root / "parse.json"
            appendix_doc = root / "APPX-A1.docx"
            Document().save(appendix_doc)
            toc_path.write_text(
                json.dumps({"items": [{"number": "附表A.1", "title": "附表A.1 投标机型总方案信息表", "level": 2}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            parse_path.write_text(
                json.dumps(
                    {
                        "items": [
                            *[
                                {
                                    "id": f"REQ-NOISE-{idx}",
                                    "type": "项目基础信息",
                                    "title": "招标人",
                                    "value": f"噪声字段{idx}",
                                    "sourceFile": "招标文件.docx",
                                }
                                for idx in range(180)
                            ],
                            {
                                "id": "REQ-SCALE",
                                "type": "项目基础信息",
                                "title": "标段规模",
                                "value": "600MW",
                                "sourceFile": "招标文件.docx",
                            }
                        ],
                        "structured": {
                            "appendices": [
                                {
                                    "id": "APPX-A1",
                                    "title": "附表A.1 投标机型总方案信息表",
                                    "docxPath": str(appendix_doc),
                                }
                            ]
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            plan = gap_runner.build_gap_plan(
                {
                    "projectId": "PRJ-TEST",
                    "projectName": "测试项目",
                    "tocJsonPath": str(toc_path),
                    "parseResultPath": str(parse_path),
                    "materialIndex": [],
                }
            )

        task = plan["items"][0]["appendixTasks"][0]
        self.assertEqual(task["availableParseFields"][0]["id"], "REQ-SCALE")
        self.assertEqual(task["availableParseFields"][0]["label"], "标段规模")
        self.assertGreater(len(task["availableParseFields"]), 160)

    def test_bid_gap_planner_summary_stdout_exposes_coverage_counts(self) -> None:
        gap_runner = load_gap_planner_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            toc_path = root / "toc.json"
            parse_path = root / "parse.json"
            manifest_path = root / "s4_gap_input.json"
            output_path = root / "gap_plan.json"
            toc_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {"number": "第1章", "title": "标前概述", "level": 1},
                            {"number": "1.1", "title": "技术评分标准索引表", "level": 2},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            parse_path.write_text(json.dumps({"structured": {}}, ensure_ascii=False), encoding="utf-8")
            manifest_path.write_text(
                json.dumps(
                    {
                        "projectId": "PRJ-TEST",
                        "projectName": "测试项目",
                        "bidType": "技术标",
                        "tocJsonPath": str(toc_path),
                        "parseResultPath": str(parse_path),
                        "materialScope": {"paths": ["技术标/客户素材/华能集团"]},
                        "projectTurbineModel": {"model": "EW10.0-220上置"},
                        "materialIndex": [],
                        "outputFile": str(output_path),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.object(sys, "argv", ["run_from_manifest.py", "--manifest", str(manifest_path)]), \
                patch("builtins.print") as mocked_print:
                gap_runner.main()

            response = json.loads(mocked_print.call_args.args[0])

        self.assertEqual(response["tocItemCount"], 2)
        self.assertEqual(response["itemCount"], 2)
        self.assertEqual(response["coverageStatus"], "passed")

    def test_bid_gap_planner_uses_project_commitment_chapter_word_for_chapter_four_children(self) -> None:
        gap_runner = load_gap_planner_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            toc_path = root / "toc.json"
            parse_path = root / "parse.json"
            toc_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {"number": "第4章", "title": "项目技术承诺函", "level": 1},
                            {"number": "4.1", "title": "发电小时数承诺函", "level": 2},
                            {"number": "4.2", "title": "投标机组可利用率承诺", "level": 2},
                            {"number": "4.3", "title": "投标机组功率曲线保证率承诺", "level": 2},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            parse_path.write_text(json.dumps({"structured": {}}, ensure_ascii=False), encoding="utf-8")
            manifest = {
                "projectId": "PRJ-TEST",
                "projectName": "测试项目",
                "bidType": "技术标",
                "tocJsonPath": str(toc_path),
                "parseResultPath": str(parse_path),
                "materialScope": {"paths": ["技术标/项目素材/MAT-HN-CHIFENG-001"]},
                "projectTurbineModel": {"model": "EW10.0-220上置"},
                "materialIndex": [
                    {
                        "id": "RAW-0472",
                        "name": "定制-项目技术承诺函.docx",
                        "folderPath": "技术标/项目素材/MAT-HN-CHIFENG-001/技术标-项目技术承诺函",
                        "materialTier": "project",
                        "hasCleanedWord": True,
                        "cleanedFileName": "定制-项目技术承诺函.docx",
                        "requiresFill": True,
                        "placeholderCount": 1,
                        "placeholderLabels": ["项目承诺函"],
                    }
                ],
            }

            plan = gap_runner.build_gap_plan(manifest)

        parent = next(item for item in plan["items"] if item["number"] == "第4章")
        self.assertEqual(parent["decision"], "fill_required")
        self.assertEqual(parent["status"], "needs_input")
        self.assertEqual(parent["usage"], "chapter_fill")
        self.assertEqual(parent["coverageRole"], "chapter_master")
        self.assertEqual(parent["fillTasks"][0]["blankSource"]["id"], "RAW-0472")
        for number in ["4.1", "4.2", "4.3"]:
            child = next(item for item in plan["items"] if item["number"] == number)
            self.assertEqual(child["decision"], "fill_required")
            self.assertEqual(child["status"], "needs_input")
            self.assertEqual(child["usage"], "covered_by_parent")
            self.assertEqual(child["coverageRole"], "covered_by_parent")
            self.assertEqual(child["coveredByParent"], parent["id"])
            self.assertEqual(child["matchedMaterials"], [])
            self.assertEqual(child["fillTasks"], [])

    def test_bid_gap_planner_uses_standard_delivery_acceptance_word_for_chapter_six_children(self) -> None:
        gap_runner = load_gap_planner_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            toc_path = root / "toc.json"
            parse_path = root / "parse.json"
            toc_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {"number": "第6章", "title": "产品交付、考核及验收", "level": 1},
                            {"number": "6.1", "title": "技术资料和交付进度", "level": 2},
                            {"number": "6.2", "title": "试验、检验和监造", "level": 2},
                            {"number": "6.3", "title": "设备安装、调试与试运行", "level": 2},
                            {"number": "6.4", "title": "考核指标", "level": 2},
                            {"number": "6.5", "title": "项目验收", "level": 2},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            parse_path.write_text(json.dumps({"structured": {}}, ensure_ascii=False), encoding="utf-8")
            manifest = {
                "projectId": "PRJ-TEST",
                "projectName": "测试项目",
                "bidType": "技术标",
                "tocJsonPath": str(toc_path),
                "parseResultPath": str(parse_path),
                "materialScope": {"paths": ["技术标/通用素材"]},
                "projectTurbineModel": {"model": "EW10.0-220上置"},
                "materialIndex": [
                    {
                        "id": "RAW-0429",
                        "name": "待填写-产品交付、考核及验收.docx",
                        "folderPath": "技术标/通用素材/技术标-产品交付、考核及验收",
                        "materialTier": "standard",
                        "hasCleanedWord": True,
                        "cleanedFileName": "待填写-产品交付、考核及验收.docx",
                        "requiresFill": True,
                        "placeholderCount": 1,
                        "placeholderLabels": ["招标要求"],
                    }
                ],
            }

            plan = gap_runner.build_gap_plan(manifest)

        parent = next(item for item in plan["items"] if item["number"] == "第6章")
        self.assertEqual(parent["decision"], "fill_required")
        self.assertEqual(parent["status"], "needs_input")
        self.assertEqual(parent["usage"], "chapter_fill")
        self.assertEqual(parent["coverageRole"], "chapter_master")
        self.assertEqual(parent["fillTasks"][0]["blankSource"]["id"], "RAW-0429")
        for number in ["6.1", "6.2", "6.3", "6.4", "6.5"]:
            child = next(item for item in plan["items"] if item["number"] == number)
            self.assertEqual(child["decision"], "fill_required")
            self.assertEqual(child["status"], "needs_input")
            self.assertEqual(child["usage"], "covered_by_parent")
            self.assertEqual(child["coverageRole"], "covered_by_parent")
            self.assertEqual(child["coveredByParent"], parent["id"])
            self.assertEqual(child["matchedMaterials"], [])
            self.assertEqual(child["fillTasks"], [])

    def test_bid_gap_planner_generically_uses_parent_chapter_word_for_any_chapter_children(self) -> None:
        gap_runner = load_gap_planner_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            toc_path = root / "toc.json"
            parse_path = root / "parse.json"
            toc_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {"number": "第8章", "title": "运输安装与验收方案", "level": 1},
                            {"number": "8.1", "title": "运输组织方案", "level": 2},
                            {"number": "8.2", "title": "安装调试计划", "level": 2},
                            {"number": "8.3", "title": "验收交付安排", "level": 2},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            parse_path.write_text(json.dumps({"structured": {}}, ensure_ascii=False), encoding="utf-8")
            manifest = {
                "projectId": "PRJ-TEST",
                "projectName": "测试项目",
                "bidType": "技术标",
                "tocJsonPath": str(toc_path),
                "parseResultPath": str(parse_path),
                "materialScope": {"paths": ["技术标/项目素材/MAT-TEST"]},
                "projectTurbineModel": {"model": "EW10.0-220上置"},
                "materialIndex": [
                    {
                        "id": "RAW-0800",
                        "name": "定制-运输安装与验收方案.docx",
                        "folderPath": "技术标/项目素材/MAT-TEST/技术标-运输安装与验收方案",
                        "materialTier": "project",
                        "hasCleanedWord": True,
                        "cleanedFileName": "定制-运输安装与验收方案.docx",
                    },
                    {
                        "id": "RAW-0801",
                        "name": "固定-运输组织方案.docx",
                        "folderPath": "技术标/项目素材/MAT-TEST/技术标-运输安装与验收方案/子节",
                        "materialTier": "project",
                    },
                ],
            }

            plan = gap_runner.build_gap_plan(manifest)

        parent = next(item for item in plan["items"] if item["number"] == "第8章")
        self.assertEqual(parent["decision"], "ready")
        self.assertEqual(parent["status"], "matched")
        self.assertEqual(parent["usage"], "chapter_master")
        self.assertEqual(parent["coverageRole"], "chapter_master")
        self.assertEqual(parent["matchedMaterials"][0]["id"], "RAW-0800")
        for number in ["8.1", "8.2", "8.3"]:
            child = next(item for item in plan["items"] if item["number"] == number)
            self.assertEqual(child["decision"], "ready")
            self.assertEqual(child["status"], "matched")
            self.assertEqual(child["usage"], "covered_by_parent")
            self.assertEqual(child["coverageRole"], "covered_by_parent")
            self.assertEqual(child["coveredByParent"], parent["id"])
            self.assertEqual(child["matchedMaterials"], [])
            self.assertEqual(child["fillTasks"], [])

    def test_bid_gap_planner_uses_generic_chapter_title_match_for_wind_resource_chapter(self) -> None:
        gap_runner = load_gap_planner_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            toc_path = root / "toc.json"
            parse_path = root / "parse.json"
            toc_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {"number": "第3章", "title": "风资源评估与机位排布方案", "level": 1},
                            {"number": "3.1", "title": "项目概况", "level": 2},
                            {"number": "3.2", "title": "风资源分析", "level": 2},
                            {"number": "3.3", "title": "机组选型", "level": 2},
                            {"number": "3.4", "title": "方案及发电量结果", "level": 2},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            parse_path.write_text(json.dumps({"structured": {}}, ensure_ascii=False), encoding="utf-8")
            manifest = {
                "projectId": "PRJ-TEST",
                "projectName": "测试项目",
                "bidType": "技术标",
                "tocJsonPath": str(toc_path),
                "parseResultPath": str(parse_path),
                "materialScope": {"paths": ["技术标/项目素材/MAT-HN-CHIFENG-001"]},
                "projectTurbineModel": {"model": "EW10.0-220上置"},
                "materialIndex": [
                    {
                        "id": "RAW-0471",
                        "name": "定制-项目风资源评估与机组选型排布及发电量计算.docx",
                        "folderPath": "技术标/项目素材/MAT-HN-CHIFENG-001/技术标-专题方案要求",
                        "materialTier": "project",
                    },
                    {
                        "id": "RAW-0473",
                        "name": "定制-风资源评估与机位排布方案.docx",
                        "folderPath": "技术标/项目素材/MAT-HN-CHIFENG-001/技术标-风资源评估与机位排布方案",
                        "materialTier": "project",
                        "hasCleanedWord": True,
                        "cleanedFileName": "定制-风资源评估与机位排布方案.docx",
                    },
                    {
                        "id": "RAW-0478",
                        "name": "风资源评估报告.docx",
                        "folderPath": "技术标/项目素材/MAT-HN-CHIFENG-001/风资源评估报告",
                        "materialTier": "project",
                    },
                ],
            }

            plan = gap_runner.build_gap_plan(manifest)

        parent = next(item for item in plan["items"] if item["number"] == "第3章")
        self.assertEqual(parent["decision"], "ready")
        self.assertEqual(parent["status"], "matched")
        self.assertEqual(parent["coverageRole"], "chapter_master")
        self.assertEqual(parent["matchedMaterials"][0]["id"], "RAW-0473")
        self.assertNotIn("RAW-0478", [item["id"] for item in parent["matchedMaterials"]])
        for number in ["3.1", "3.2", "3.3", "3.4"]:
            child = next(item for item in plan["items"] if item["number"] == number)
            self.assertEqual(child["coverageRole"], "covered_by_parent")
            self.assertEqual(child["coveredByParent"], parent["id"])
            self.assertEqual(child["matchedMaterials"], [])

    def test_bid_gap_planner_filters_toc_refs_by_allowed_material_index(self) -> None:
        gap_runner = load_gap_planner_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            toc_path = root / "toc.json"
            parse_path = root / "parse.json"
            toc_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "number": "1.2",
                                "title": "与华能集团签署的战略合作协议",
                                "level": 2,
                                "material_refs": [
                                    {
                                        "id": "RAW-OUTSIDE",
                                        "docx": "技术标/客户素材/其他客户/战略合作协议.docx",
                                    }
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            parse_path.write_text(json.dumps({"structured": {}}, ensure_ascii=False), encoding="utf-8")
            manifest = {
                "projectId": "PRJ-TEST",
                "projectName": "测试项目",
                "bidType": "技术标",
                "tocJsonPath": str(toc_path),
                "parseResultPath": str(parse_path),
                "materialScope": {"paths": ["技术标/客户素材/华能集团"]},
                "projectTurbineModel": {"model": "EW10.0-220上置"},
                "materialIndex": [
                    {
                        "id": "RAW-ALLOWED",
                        "name": "固定-其他资料.docx",
                        "folderPath": "技术标/客户素材/华能集团/其他",
                        "materialTier": "customer",
                    }
                ],
            }

            plan = gap_runner.build_gap_plan(manifest)

        item = plan["items"][0]
        self.assertEqual(item["decision"], "material_required")
        self.assertEqual(item["status"], "missing")
        self.assertEqual(item["matchedMaterials"], [])

    def test_bid_wiki_builder_writes_full_blueprint_and_returns_small_summary(self) -> None:
        wiki_runner = load_wiki_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "wiki_manifest.json"
            output_file = root / "wiki_blueprint.json"
            manifest = {
                "targetBidType": "技术标",
                "rootTitle": "技术标Wiki（自动生成）",
                "workDir": str(root),
                "outputFile": str(output_file),
                "materialInventory": {
                    "items": [
                        {
                            "id": "M1",
                            "title": "总体方案",
                            "name": "总体方案.docx",
                            "path": "技术标/通用素材/总体方案.docx",
                            "identityScope": "general",
                            "materialTier": "general",
                            "group": "总体方案",
                            "headings": [{"title": "总体方案"}],
                        }
                    ]
                },
            }
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

            response = wiki_runner.run_manifest(manifest, manifest_path)

            self.assertEqual(response["outputFile"], str(output_file))
            self.assertIn("nodeTitles", response)
            self.assertLess(len(json.dumps(response, ensure_ascii=False)), 1000)
            blueprint = json_load(output_file)
            self.assertEqual(blueprint["rootTitle"], "技术标Wiki（自动生成）")
            self.assertEqual(
                [node["title"] for node in blueprint["nodes"]],
                ["01-素材总表", "02-章节映射表", "03-素材卡片", "04-待填写清单", "05-使用规则"],
            )
            cards_node = next(node for node in blueprint["nodes"] if node["title"] == "03-素材卡片")
            self.assertEqual(cards_node["children"][0]["children"][0]["children"][0]["title"], "总体方案")

    def test_bid_outline_generator_preserves_appendix_search_text_and_appends_last(self) -> None:
        outline_runner = load_outline_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.docx"
            tender = root / "tender.docx"
            output = root / "toc.json"
            evidence = root / "evidence.json"

            template_doc = Document()
            template_doc.add_paragraph("第1章 风资源评估与机位排布方案", style="Heading 1")
            template_doc.add_paragraph("1.1 项目风资源评估与机组选型排布及发电量计算", style="Heading 2")
            template_doc.add_paragraph("第2章 产品交付、考核及验收", style="Heading 1")
            template_doc.save(template)

            tender_doc = Document()
            tender_doc.add_paragraph("技术附表E 项目风资源评估及机组选型排布及发电量计算 194")
            tender_doc.add_paragraph("附表E.3推荐机型各机位发电量成果表 195")
            tender_doc.save(tender)

            manifest = {
                "projectId": "PRJ-TEST",
                "projectName": "测试项目",
                "workDir": str(root),
                "templateFile": str(template),
                "tenderFiles": [{"id": "TEN-1", "name": "tender.docx", "path": str(tender)}],
                "outputFile": str(output),
                "evidenceFile": str(evidence),
            }
            result = outline_runner.run_manifest(manifest, root / "s2_input.json")

            toc = json_load(output)
            titles = [item["title"] for item in toc["items"]]
            self.assertEqual(titles[-1], "推荐机型各机位发电量成果表")
            self.assertEqual(toc["items"][-1]["number"], "附表E.3")
            self.assertEqual(
                toc["items"][-1]["source_refs"][0]["searchText"],
                "附表E.3推荐机型各机位发电量成果表",
            )
            self.assertTrue(Path(result["summary"]["agentReviewFile"]).exists())

    def test_bid_outline_generator_excludes_tender_attachments_and_appendices_from_toc(self) -> None:
        outline_runner = load_outline_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.docx"
            tender = root / "tender.docx"
            output = root / "toc.json"
            evidence = root / "evidence.json"

            template_doc = Document()
            template_doc.add_paragraph("第1章 技术方案", style="Heading 1")
            template_doc.save(template)

            tender_doc = Document()
            tender_doc.add_paragraph("附表A.1 投标机型总方案信息表")
            tender_doc.add_paragraph("附件一 中国华能集团有限公司陆上风电工程设备监理大纲")
            tender_doc.add_paragraph("附录A 设备制造监理内容")
            tender_doc.save(tender)

            outline_runner.run_manifest(
                {
                    "projectId": "PRJ-TEST",
                    "workDir": str(root),
                    "templateFile": str(template),
                    "tenderFiles": [{"id": "TEN-1", "name": "tender.docx", "path": str(tender)}],
                    "outputFile": str(output),
                    "evidenceFile": str(evidence),
                },
                root / "s2_input.json",
            )

            toc = json_load(output)
            titles = [item["title"] for item in toc["items"]]
            self.assertIn("投标机型总方案信息表", titles)
            self.assertNotIn("中国华能集团有限公司陆上风电工程设备监理大纲", titles)
            self.assertNotIn("设备制造监理内容", titles)

            evidence_data = json_load(evidence)
            reference_titles = [
                decision["title"]
                for decision in evidence_data["decisions"]
                if decision.get("action") == "reference_only"
            ]
            self.assertIn("附件一 中国华能集团有限公司陆上风电工程设备监理大纲", reference_titles)
            self.assertIn("附录A 设备制造监理内容", reference_titles)

    def test_bid_outline_generator_prefers_toc_region_over_body_headings(self) -> None:
        outline_runner = load_outline_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.docx"
            tender = root / "tender.docx"
            output = root / "toc.json"
            evidence = root / "evidence.json"

            template_doc = Document()
            template_doc.styles.add_style("toc 1", WD_STYLE_TYPE.PARAGRAPH)
            template_doc.styles.add_style("toc 2", WD_STYLE_TYPE.PARAGRAPH)
            template_doc.add_paragraph("目录")
            template_doc.add_paragraph("第1章 模板总述\t1", style="toc 1")
            template_doc.add_paragraph("1.1 基本情况\t2", style="toc 2")
            template_doc.add_paragraph("第2章 正文标题不能进入目录", style="Heading 1")
            template_doc.save(template)

            tender_doc = Document()
            tender_doc.add_paragraph("投标人应提供实施方案。")
            tender_doc.save(tender)

            outline_runner.run_manifest(
                {
                    "projectId": "PRJ-TEST",
                    "workDir": str(root),
                    "templateFile": str(template),
                    "tenderFiles": [{"id": "TEN-1", "name": "tender.docx", "path": str(tender)}],
                    "outputFile": str(output),
                    "evidenceFile": str(evidence),
                },
                root / "s2_input.json",
            )

            toc = json_load(output)
            template_titles = [item["title"] for item in toc["items"] if item["source"] == "template"]
            self.assertEqual(template_titles, ["模板总述", "基本情况"])
            self.assertFalse(any("不能进入目录" in item["title"] for item in toc["items"]))

    def test_bid_outline_generator_ignores_body_numbered_lists_after_toc_region(self) -> None:
        outline_runner = load_outline_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.docx"
            tender = root / "tender.docx"
            output = root / "toc.json"
            evidence = root / "evidence.json"

            template_doc = Document()
            template_doc.styles.add_style("toc 1", WD_STYLE_TYPE.PARAGRAPH)
            template_doc.styles.add_style("toc 2", WD_STYLE_TYPE.PARAGRAPH)
            template_doc.add_paragraph("目录")
            template_doc.add_paragraph("第1章 模板总述\t1", style="toc 1")
            template_doc.add_paragraph("1.1 基本情况\t2", style="toc 2")
            template_doc.add_paragraph("正文开始")
            template_doc.add_paragraph("（4） 风储一体化构网型风机")
            template_doc.add_paragraph("(1) 叶根部驱动转矩")
            template_doc.add_paragraph("(2) 变桨电机转矩")
            template_doc.save(template)

            tender_doc = Document()
            tender_doc.add_paragraph("投标人应提供实施方案。")
            tender_doc.save(tender)

            outline_runner.run_manifest(
                {
                    "projectId": "PRJ-TEST",
                    "workDir": str(root),
                    "templateFile": str(template),
                    "tenderFiles": [{"id": "TEN-1", "name": "tender.docx", "path": str(tender)}],
                    "outputFile": str(output),
                    "evidenceFile": str(evidence),
                },
                root / "s2_input.json",
            )

            toc = json_load(output)
            titles = [item["title"] for item in toc["items"]]
            self.assertEqual(titles, ["模板总述", "基本情况"])
            self.assertNotIn("风储一体化构网型风机", titles)
            self.assertNotIn("叶根部驱动转矩", titles)
            self.assertNotIn("变桨电机转矩", titles)

    def test_bid_assembler_parse_toc_accepts_current_s2_json(self) -> None:
        parse_toc = load_assembler_script("parse_toc")

        with tempfile.TemporaryDirectory() as tmp:
            toc_path = Path(tmp) / "投标文件-总目录.json"
            toc_path.write_text(
                """{
  "schema_version": "bid-toc-json-v1",
  "document_title": "测试项目投标文件总目录",
  "items": [
    {"order": 1, "level": 1, "number": "1", "title": "项目概况", "annotation": "保留"},
    {"order": 2, "level": 2, "number": "1.1", "title": "项目背景", "annotation": "适配"},
    {"order": 3, "level": 1, "number": "附表", "title": "", "annotation": "保留"}
  ]
}""",
                encoding="utf-8",
            )

            entries = parse_toc.parse_toc_json(toc_path)

        self.assertEqual(entries[0]["chapter_no_flat"], "1")
        self.assertEqual(entries[0]["title"], "项目概况")
        self.assertEqual(entries[1]["tag"], "适配")
        self.assertEqual(entries[2]["title"], "附表")

    def test_bid_table_filler_preserves_generic_appendix_and_highlights_manual_cells(self) -> None:
        table_filler = load_table_filler_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            blank = tmp_path / "附表A.1 投标机型总方案信息表.docx"
            doc = Document()
            table = doc.add_table(rows=1, cols=4)
            table.style = "Table Grid"
            for index, text in enumerate(["序号", "项目", "投标响应", "备注"]):
                table.cell(0, index).text = text
            for row in (
                ["1", "投标机型", "", ""],
                ["2", "叶轮直径", "", "m"],
                ["3", "项目业主", "", ""],
                ["4", "场址空气密度", "", ""],
            ):
                cells = table.add_row().cells
                for index, text in enumerate(row):
                    cells[index].text = text
            doc.save(blank)

            manifest_path = tmp_path / "manifest.json"
            output = tmp_path / "filled.docx"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "bid-tech-table-fill-v1",
                        "appendixTask": {
                            "id": "APPX-A1",
                            "title": "附表A.1 投标机型总方案信息表",
                            "docxPath": str(blank),
                        },
                        "projectTurbineModel": {
                            "model": "EW10.0-220上置",
                            "ratedPowerKw": 10000,
                            "rotorDiameterM": 220,
                        },
                        "parseFields": [{"id": "OWNER", "label": "项目业主", "value": "测试业主"}],
                        "outputFile": str(output),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = table_filler.run_from_manifest(manifest_path)

            self.assertEqual(result["schema_version"], "bid-tech-table-fill-v1")
            self.assertTrue(output.exists())
            self.assertEqual(result["fillReport"]["filledFieldCount"], 3)
            self.assertEqual(result["fillReport"]["unfilledFieldCount"], 1)
            filled_doc = Document(str(output))
            rows = filled_doc.tables[0].rows
            self.assertEqual(rows[1].cells[2].text, "EW10.0-220上置")
            self.assertEqual(rows[2].cells[2].text, "220")
            self.assertEqual(rows[3].cells[2].text, "测试业主")
            self.assertEqual(rows[4].cells[2].text, "[待人工补充：场址空气密度]")
            shd = rows[4].cells[2]._tc.tcPr.find(qn("w:shd"))
            self.assertIsNotNone(shd)
            self.assertEqual(shd.get(qn("w:fill")), "FFF2CC")

    def test_bid_word_placeholder_filler_replaces_parse_and_project_placeholders(self) -> None:
        word_filler = load_word_filler_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            template = tmp_path / "待填写-投标说明函.docx"
            doc = Document()
            doc.add_paragraph("投标机型：[投标机型，待填写]")
            doc.add_paragraph("项目要求：[招标要求，待填写]")
            table = doc.add_table(rows=1, cols=2)
            table.style = "Table Grid"
            table.cell(0, 0).text = "项目名称"
            table.cell(0, 1).text = "[项目名称，待填写]"
            doc.save(template)

            manifest_path = tmp_path / "manifest.json"
            output = tmp_path / "filled.docx"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "bid-tech-word-placeholder-fill-v1",
                        "projectName": "测试风电项目",
                        "projectTurbineModel": {"model": "EW10.0-220上置"},
                        "blankSource": {
                            "id": "RAW-TEMPLATE",
                            "title": "待填写-投标说明函.docx",
                            "docxPath": str(template),
                            "placeholderCount": 3,
                        },
                        "parseFields": [
                            {
                                "id": "REQ-001",
                                "label": "招标要求",
                                "value": "满足招标文件所有技术要求",
                                "sourceFile": "招标文件.docx",
                            }
                        ],
                        "outputFile": str(output),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = word_filler.run_from_manifest(manifest_path)

            self.assertEqual(result["schema_version"], "bid-tech-word-placeholder-fill-v1")
            self.assertEqual(result["fillReport"]["placeholderCount"], 3)
            self.assertEqual(result["fillReport"]["filledPlaceholderCount"], 3)
            self.assertEqual(result["unfilledFields"], [])
            filled_doc = Document(str(output))
            self.assertEqual(filled_doc.paragraphs[0].text, "投标机型：EW10.0-220上置")
            self.assertEqual(filled_doc.paragraphs[1].text, "项目要求：满足招标文件所有技术要求")
            self.assertEqual(filled_doc.tables[0].cell(0, 1).text, "测试风电项目")

    def test_bid_word_placeholder_filler_uses_project_identity_for_owner_placeholders(self) -> None:
        word_filler = load_word_filler_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            template = tmp_path / "固定-风电机组自主可控推广应用的承诺.docx"
            doc = Document()
            doc.add_paragraph("招标方：[招标方，待填写]")
            doc.add_paragraph("日期：[日期，待填写]")
            doc.save(template)

            manifest_path = tmp_path / "manifest.json"
            output = tmp_path / "filled.docx"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "bid-tech-word-placeholder-fill-v1",
                        "projectName": "测试风电项目",
                        "projectIdentity": {
                            "owner": "华能集团",
                            "customerName": "华能集团",
                        },
                        "blankSource": {
                            "id": "RAW-0452",
                            "title": "固定-风电机组自主可控推广应用的承诺.docx",
                            "docxPath": str(template),
                            "placeholderCount": 2,
                        },
                        "outputFile": str(output),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = word_filler.run_from_manifest(manifest_path)

            self.assertEqual(result["fillReport"]["placeholderCount"], 2)
            self.assertEqual(result["fillReport"]["filledPlaceholderCount"], 2)
            self.assertEqual(result["unfilledFields"], [])
            filled_text = "\n".join(paragraph.text for paragraph in Document(str(output)).paragraphs)
            self.assertIn("招标方：华能集团", filled_text)
            self.assertNotIn("待填写", filled_text)

    def test_bid_word_placeholder_filler_uses_manufacturing_base_intro_from_materials(self) -> None:
        word_filler = load_word_filler_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            template = tmp_path / "待填写-供货保障能力.docx"
            doc = Document()
            doc.add_paragraph("本项目主机供货制造基地-[基地名称，待填写]")
            doc.add_paragraph("[基地介绍，待填写]生产基地情况详见5.11.1 本项目主机供货制造基地")
            doc.add_paragraph("本项目叶片供货制造基地-[基地名称，待填写]")
            doc.add_paragraph("[基地介绍，待填写]生产基地情况详见5.11.2 本项目叶片供货制造基地")
            doc.save(template)

            material = tmp_path / "固定-上海电气生产能力介绍.docx"
            source_doc = Document()
            source_doc.add_paragraph("上海电气生产能力介绍")
            source_doc.add_paragraph(
                "上海电气风电(张掖)叶片科技有限公司作为上海电气风电集团股份有限公司子公司成立于2021年12月24日，"
                "公司位于高台县南华镇工业园区。公司主要生产5XMW及以上风力发电机组和叶片，配套年产能500台机组、500套叶片。"
            )
            source_doc.add_paragraph(
                "上海电气高台生产基地于2023年6月投入生产运营，产品订单覆盖西北五省，目前已经累计生产5MW及上风力发电机组100台套。"
            )
            source_doc.save(material)

            manifest_path = tmp_path / "manifest.json"
            output = tmp_path / "filled.docx"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "bid-tech-word-placeholder-fill-v1",
                        "blankSource": {
                            "id": "RAW-SUPPLY",
                            "title": template.name,
                            "docxPath": str(template),
                            "placeholderCount": 4,
                        },
                        "referenceMaterials": [
                            {"id": "RAW-PROD", "name": material.name, "path": str(material), "materialTier": "standard"}
                        ],
                        "outputFile": str(output),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = word_filler.run_from_manifest(manifest_path)

            self.assertEqual(result["unfilledFields"], [])
            filled_text = "\n".join(paragraph.text for paragraph in Document(str(output)).paragraphs)
            self.assertIn("本项目主机供货制造基地-上海电气高台生产基地", filled_text)
            self.assertIn("上海电气高台生产基地于2023年6月投入生产运营", filled_text)
            self.assertIn("本项目叶片供货制造基地-上海电气风电（张掖）叶片科技有限公司", filled_text)
            self.assertIn("配套年产能500台机组、500套叶片", filled_text)
            self.assertNotIn("待人工补充", filled_text)

    def test_bid_word_placeholder_filler_summarizes_wind_resource_report_from_project_facts(self) -> None:
        word_filler = load_word_filler_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            template = tmp_path / "风资源评估与机位排布方案.docx"
            doc = Document()
            doc.add_paragraph("风资源概况：[风资源报告，待填写]")
            doc.save(template)

            manifest_path = tmp_path / "manifest.json"
            output = tmp_path / "filled.docx"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "bid-tech-word-placeholder-fill-v1",
                        "blankSource": {
                            "id": "RAW-WIND",
                            "title": "风资源评估与机位排布方案.docx",
                            "docxPath": str(template),
                            "placeholderCount": 1,
                        },
                        "projectFactTable": {
                            "status": "confirmed",
                            "fields": [
                                {"label": "轮毂高度", "value": "125", "unit": "m"},
                                {"label": "年平均风速", "value": "7.22", "unit": "m/s"},
                                {"label": "空气密度", "value": "1.16", "unit": "kg/m3"},
                                {"label": "湍流强度", "value": "0.1"},
                                {"label": "风剪切", "value": "0.1"},
                                {"label": "极端风速", "value": "53.51", "unit": "m/s"},
                                {"label": "安全等级", "value": "IEC S"},
                            ],
                        },
                        "outputFile": str(output),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = word_filler.run_from_manifest(manifest_path)

            self.assertEqual(result["fillReport"]["filledPlaceholderCount"], 1)
            self.assertEqual(result["unfilledFields"], [])
            filled_text = "\n".join(paragraph.text for paragraph in Document(str(output)).paragraphs)
            self.assertIn("7.22", filled_text)
            self.assertIn("1.16", filled_text)
            self.assertIn("IEC S", filled_text)
            self.assertNotIn("待填写", filled_text)

    def test_bid_word_placeholder_filler_uses_table_row_label_before_model_column_header(self) -> None:
        word_filler = load_word_filler_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            template = tmp_path / "待填写-投标关键数据一览表.docx"
            doc = Document()
            table = doc.add_table(rows=1, cols=3)
            table.style = "Table Grid"
            for index, text in enumerate(["项目名称", "[项目名称，待填写]", "[项目名称，待填写]"]):
                table.cell(0, index).text = text
            for row in (
                ["承诺方式", "[投标方案，待填写]", "[投标方案，待填写]"],
                ["方案", "[投标方案，待填写]", "[投标方案，待填写]"],
                ["机型", "[投标方案，待填写]", "[投标方案，待填写]"],
                ["轮毂高度（m）", "[投标方案，待填写]", "[投标方案，待填写]"],
                ["台数", "[投标方案，待填写]", "[投标方案，待填写]"],
                ["容量（MW）", "[投标方案，待填写]", "[投标方案，待填写]"],
                ["净发电量（MWh/y）", "[投标方案，待填写]", "[投标方案，待填写]"],
                ["有效小时数（h）", "[投标方案，待填写]", "[投标方案，待填写]"],
            ):
                cells = table.add_row().cells
                for index, text in enumerate(row):
                    cells[index].text = text
            guarantee = doc.add_table(rows=1, cols=2)
            guarantee.style = "Table Grid"
            guarantee.cell(0, 0).text = "保证项"
            guarantee.cell(0, 1).text = "保证率"
            for row in (
                ["单台机组功率曲线保证率（%）", "[投标方案，待填写]"],
                ["单台机组时间可利用率保证值（%）", "[投标方案，待填写]"],
                ["全场机组时间可利用率保证值）（%）", "[投标方案，待填写]"],
            ):
                cells = guarantee.add_row().cells
                cells[0].text, cells[1].text = row
            doc.save(template)

            manifest_path = tmp_path / "manifest.json"
            output = tmp_path / "filled.docx"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "bid-tech-word-placeholder-fill-v1",
                        "projectName": "测试项目",
                        "blankSource": {
                            "id": "RAW-KEY-DATA",
                            "title": "待填写-投标关键数据一览表.docx",
                            "docxPath": str(template),
                            "placeholderCount": 18,
                        },
                        "projectFactTable": {
                            "status": "confirmed",
                            "fields": [
                                {"label": "项目名称", "value": "测试项目"},
                                {"label": "投标方案", "value": "EW10.0-220-125"},
                                {"label": "投标机型", "value": "EW10.0-220上置"},
                                {"label": "轮毂高度", "value": "125", "unit": "m"},
                                {"label": "机组台数", "value": "60", "unit": "台"},
                                {"label": "总装机容量", "value": "600", "unit": "MW"},
                                {"label": "保证发电量", "value": "1701601", "unit": "MWh"},
                                {"label": "保证有效小时数", "value": "2836", "unit": "h"},
                                {"label": "功率曲线保证率", "value": "97%", "unit": "%"},
                                {"label": "单台可利用率", "value": "95%", "unit": "%"},
                                {"label": "全场可利用率", "value": "98%", "unit": "%"},
                            ],
                        },
                        "outputFile": str(output),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = word_filler.run_from_manifest(manifest_path)

            self.assertEqual(result["unfilledFields"], [])
            filled_doc = Document(str(output))
            rows = filled_doc.tables[0].rows
            self.assertEqual(rows[1].cells[1].text, "承诺保证值（75%折减）")
            self.assertEqual(rows[2].cells[1].text, "EW10.0-220-125")
            self.assertEqual(rows[3].cells[1].text, "EW10.0-220-125")
            self.assertEqual(rows[4].cells[1].text, "125")
            self.assertEqual(rows[5].cells[1].text, "60")
            self.assertEqual(rows[6].cells[1].text, "600")
            self.assertEqual(rows[7].cells[1].text, "1701601")
            self.assertEqual(rows[8].cells[1].text, "2836")
            guarantee_rows = filled_doc.tables[1].rows
            self.assertEqual(guarantee_rows[1].cells[1].text, "97%")
            self.assertEqual(guarantee_rows[2].cells[1].text, "95%")
            self.assertEqual(guarantee_rows[3].cells[1].text, "98%")
            self.assertEqual(result["fillReport"]["semanticCheckCount"], 21)
            self.assertEqual(result["fillReport"]["semanticFailedCount"], 0)
            self.assertEqual(result["fillReport"]["semanticValidationRate"], 1.0)

    def test_bid_table_filler_uses_first_empty_response_column_for_multi_model_tables(self) -> None:
        table_filler = load_table_filler_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            blank = tmp_path / "附表A.1 投标机型总方案信息表.docx"
            blank_doc = Document()
            table = blank_doc.add_table(rows=1, cols=6)
            table.style = "Table Grid"
            for index, text in enumerate(["编号", "项目", "项目", "投标机型1", "投标机型2", "备注"]):
                table.cell(0, index).text = text
            for row in (
                ["1", "投标机型", "投标机型", "", "", ""],
                ["2", "机组台数", "机组台数", "", "", ""],
            ):
                cells = table.add_row().cells
                for index, text in enumerate(row):
                    cells[index].text = text
            blank_doc.save(blank)

            manifest_path = tmp_path / "manifest.json"
            output = tmp_path / "filled.docx"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "bid-tech-table-fill-v1",
                        "appendixTask": {
                            "id": "APPX-A1",
                            "title": "附表A.1 投标机型总方案信息表",
                            "docxPath": str(blank),
                        },
                        "projectTurbineModel": {"model": "EW10.0-220上置", "ratedPowerKw": 10000},
                        "parseFields": [{"id": "REQ-SCALE", "label": "标段规模", "value": "600MW"}],
                        "outputFile": str(output),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            table_filler.run_from_manifest(manifest_path)

            filled_doc = Document(str(output))
            rows = filled_doc.tables[0].rows
            self.assertEqual(rows[1].cells[3].text, "EW10.0-220上置")
            self.assertEqual(rows[1].cells[4].text, "")
            self.assertEqual(rows[2].cells[3].text, "60")

    def test_bid_table_filler_uses_bidder_response_column_and_requirement_fallback(self) -> None:
        table_filler = load_table_filler_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            blank = tmp_path / "附表E.2 风电场折减系数表.docx"
            blank_doc = Document()
            table = blank_doc.add_table(rows=1, cols=3)
            table.style = "Table Grid"
            for index, text in enumerate(["风电场折减项目", "招标人要求值", "投标人响应值"]):
                table.cell(0, index).text = text
            for row in (
                ["尾流折减", "97%", ""],
                ["空气密度折减", "根据各厂家测算结果确定", ""],
            ):
                cells = table.add_row().cells
                for index, text in enumerate(row):
                    cells[index].text = text
            blank_doc.save(blank)

            manifest_path = tmp_path / "manifest.json"
            output = tmp_path / "filled.docx"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "bid-tech-table-fill-v1",
                        "appendixTask": {
                            "id": "APPX-E2",
                            "title": "附表E.2 风电场折减系数表",
                            "docxPath": str(blank),
                        },
                        "outputFile": str(output),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = table_filler.run_from_manifest(manifest_path)

            self.assertEqual(result["fillReport"]["targetFieldCount"], 2)
            self.assertEqual(result["fillReport"]["filledFieldCount"], 1)
            self.assertEqual(result["fillReport"]["unfilledFieldCount"], 1)
            filled_doc = Document(str(output))
            rows = filled_doc.tables[0].rows
            self.assertEqual(rows[1].cells[2].text, "97%")
            self.assertEqual(rows[2].cells[2].text, "[待人工补充：空气密度折减]")
            shd = rows[2].cells[2]._tc.tcPr.find(qn("w:shd"))
            self.assertIsNotNone(shd)

    def test_bid_table_filler_counts_only_empty_or_placeholder_response_cells(self) -> None:
        table_filler = load_table_filler_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            blank = tmp_path / "附表A.1 投标机型总方案信息表.docx"
            blank_doc = Document()
            table = blank_doc.add_table(rows=1, cols=3)
            table.style = "Table Grid"
            for index, text in enumerate(["编号", "项目", "投标响应"]):
                table.cell(0, index).text = text
            for row in (
                ["1", "投标机型", "已填写机型"],
                ["2", "轮毂高度", ""],
            ):
                cells = table.add_row().cells
                for index, text in enumerate(row):
                    cells[index].text = text
            blank_doc.save(blank)

            manifest_path = tmp_path / "manifest.json"
            output = tmp_path / "filled.docx"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "bid-tech-table-fill-v1",
                        "appendixTask": {
                            "id": "APPX-A1",
                            "title": "附表A.1 投标机型总方案信息表",
                            "docxPath": str(blank),
                        },
                        "projectFactTable": {
                            "status": "confirmed",
                            "fields": [
                                {"label": "轮毂高度", "value": "125", "unit": "m"},
                                {"label": "投标机型", "value": "EW10.0-220上置"},
                            ],
                        },
                        "outputFile": str(output),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = table_filler.run_from_manifest(manifest_path)

            self.assertEqual(result["fillReport"]["targetFieldCount"], 1)
            self.assertEqual(result["fillReport"]["filledFieldCount"], 1)
            filled_doc = Document(str(output))
            rows = filled_doc.tables[0].rows
            self.assertEqual(rows[1].cells[2].text, "已填写机型")
            self.assertEqual(rows[2].cells[2].text, "125")

    def test_bid_table_filler_auto_selects_non_c_appendix_sources_from_material_index(self) -> None:
        table_filler = load_table_filler_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            blank = tmp_path / "附表B.2 供货范围响应表.docx"
            blank_doc = Document()
            table = blank_doc.add_table(rows=1, cols=4)
            table.style = "Table Grid"
            for index, text in enumerate(["序号", "项目", "投标响应", "备注"]):
                table.cell(0, index).text = text
            for row in (
                ["1", "风力发电机组", "", ""],
                ["2", "塔筒", "", ""],
                ["3", "专用工具", "", ""],
            ):
                cells = table.add_row().cells
                for index, text in enumerate(row):
                    cells[index].text = text
            blank_doc.save(blank)

            supply = tmp_path / "固定-供货范围清单.docx"
            supply_doc = Document()
            source_table = supply_doc.add_table(rows=1, cols=2)
            source_table.style = "Table Grid"
            source_table.cell(0, 0).text = "项目"
            source_table.cell(0, 1).text = "投标响应"
            for row in (
                ["风力发电机组", "提供 EW10.0-220 风力发电机组"],
                ["塔筒", "包含配套钢塔筒"],
                ["专用工具", "提供安装维护专用工具一套"],
            ):
                cells = source_table.add_row().cells
                cells[0].text = row[0]
                cells[1].text = row[1]
            supply_doc.save(supply)

            wrong = tmp_path / "固定-风资源评估报告.docx"
            wrong_doc = Document()
            wrong_doc.add_paragraph("平均风速：7.2m/s")
            wrong_doc.save(wrong)

            manifest_path = tmp_path / "manifest.json"
            output = tmp_path / "filled.docx"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "bid-tech-table-fill-v1",
                        "appendixTask": {
                            "id": "APPX-B2",
                            "title": "附表B.2 供货范围响应表",
                            "docxPath": str(blank),
                        },
                        "materialIndex": [
                            {
                                "id": "RAW-WIND",
                                "name": "固定-风资源评估报告.docx",
                                "folderPath": "技术标/项目素材/风资源评估",
                                "path": str(wrong),
                                "materialTier": "project",
                            },
                            {
                                "id": "RAW-SUPPLY",
                                "name": "固定-供货范围清单.docx",
                                "folderPath": "技术标/通用素材/供货范围",
                                "path": str(supply),
                                "materialTier": "standard",
                            },
                        ],
                        "recommendedMaterials": [
                            {
                                "id": "RAW-WIND",
                                "name": "固定-风资源评估报告.docx",
                                "path": str(wrong),
                            }
                        ],
                        "outputFile": str(output),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = table_filler.run_from_manifest(manifest_path)

            self.assertEqual(result["fillReport"]["filledFieldCount"], 3)
            selected_ids = [item["id"] for item in result["fillReport"]["sourceSelection"]["selected"]]
            self.assertIn("RAW-SUPPLY", selected_ids)
            self.assertEqual(result["fillReport"]["referenceSources"][0]["id"], "RAW-SUPPLY")
            self.assertEqual(result["fillReport"]["referenceSources"][0]["route"], "Wiki/materialIndex 自动选材")
            filled_doc = Document(str(output))
            rows = filled_doc.tables[0].rows
            self.assertEqual(rows[1].cells[2].text, "提供 EW10.0-220 风力发电机组")
            self.assertEqual(rows[2].cells[2].text, "包含配套钢塔筒")
            self.assertEqual(rows[3].cells[2].text, "提供安装维护专用工具一套")

    def test_bid_table_filler_uses_parse_fields_and_project_materials_for_project_specific_values(self) -> None:
        table_filler = load_table_filler_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            blank = tmp_path / "附表A.1 投标机型总方案信息表.docx"
            blank_doc = Document()
            table = blank_doc.add_table(rows=1, cols=4)
            table.style = "Table Grid"
            for index, text in enumerate(["序号", "项目", "投标响应", "备注"]):
                table.cell(0, index).text = text
            for row in (
                ["1", "机组台数", "", ""],
                ["2", "总容量（MW）", "", ""],
                ["3", "场址空气密度", "", ""],
                ["4", "基础混凝土（m3）", "", ""],
                ["5", "基础钢筋（t）", "", ""],
                ["6", "箱变位置", "", ""],
            ):
                cells = table.add_row().cells
                for index, text in enumerate(row):
                    cells[index].text = text
            blank_doc.save(blank)

            foundation = tmp_path / "基础弯矩表.xlsx"
            wb = Workbook()
            ws = wb.active
            ws.title = "基础工程量"
            ws.append(["基础混凝土用量（m3）", "789.482"])
            ws.append(["垫层混凝土用量（m3）", "57.353"])
            ws.append(["基础钢筋用量（kg）", "85787.635"])
            wb.save(foundation)

            manifest_path = tmp_path / "manifest.json"
            output = tmp_path / "filled.docx"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "bid-tech-table-fill-v1",
                        "appendixTask": {
                            "id": "APPX-A1",
                            "title": "附表A.1 投标机型总方案信息表",
                            "docxPath": str(blank),
                        },
                        "projectTurbineModel": {
                            "model": "EW10.0-220上置",
                            "layout": "变压器上置",
                        },
                        "parseFields": [
                            {"id": "REQ-NOISE-COUNT", "label": "项目基础信息", "value": "故障率≥10%，不足3台按3台计算"},
                            {"id": "REQ-NOISE-DENSITY", "label": "空气密度", "value": "湿度均有相应变化，相同风速蕴含的风能也会发生变化"},
                            {"id": "REQ-COUNT", "label": "项目概况", "value": "本工程计划安装60台单机容量10MW风力发电机组"},
                            {"id": "REQ-SCALE", "label": "标段规模", "value": "600MW"},
                            {"id": "REQ-DENSITY", "label": "空气密度", "value": "1.154 kg/m³"},
                        ],
                        "materialIndex": [
                            {
                                "id": "RAW-FOUNDATION",
                                "name": "基础弯矩表.xlsx",
                                "folderPath": "技术标/项目素材/基础弯矩表",
                                "path": str(foundation),
                                "materialTier": "project",
                            }
                        ],
                        "outputFile": str(output),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = table_filler.run_from_manifest(manifest_path)

            self.assertEqual(result["fillReport"]["unfilledFieldCount"], 0)
            filled_doc = Document(str(output))
            rows = filled_doc.tables[0].rows
            self.assertEqual(rows[1].cells[2].text, "60")
            self.assertEqual(rows[2].cells[2].text, "600MW")
            self.assertEqual(rows[3].cells[2].text, "1.154 kg/m³")
            self.assertEqual(rows[4].cells[2].text, "789.482")
            self.assertEqual(rows[5].cells[2].text, "85.788")
            self.assertEqual(rows[6].cells[2].text, "塔上上置机型")

    def test_bid_table_filler_copies_power_curve_matrix_from_project_excels(self) -> None:
        table_filler = load_table_filler_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            blank = tmp_path / "附表D.1 标准及风电场空气密度功率曲线.docx"
            doc = Document()
            table = doc.add_table(rows=1, cols=4)
            table.style = "Table Grid"
            for index, text in enumerate(["风速区间（m/s）", "区间平均风速（m/s）", "标准空气密度下功率（kW）", "风电场空气密度下功率（kW）"]):
                table.cell(0, index).text = text
            for row in (
                ["0.00-0.25", "0", "", ""],
                ["2.75-3.25", "3.0", "", ""],
                ["3.25-3.75", "3.5", "", ""],
            ):
                cells = table.add_row().cells
                for index, text in enumerate(row):
                    cells[index].text = text
            doc.save(blank)

            standard = tmp_path / "W10.0-220_空气密度1.225_功率曲线.xlsx"
            wb = Workbook()
            ws = wb.active
            ws.title = "功率曲线与发电量"
            ws.append(["风速(m/s)", "修正功率(kW)(Ce_max=0.45)", "Ct"])
            ws.append([3.0, 210, 0.91])
            ws.append([3.5, 350, 0.87])
            wb.save(standard)

            site = tmp_path / "W10.0-220_空气密度1.16_功率曲线.xlsx"
            wb = Workbook()
            ws = wb.active
            ws.title = "功率曲线与发电量"
            ws.append(["风速(m/s)", "修正功率(kW)(Ce_max=0.45)", "Ct"])
            ws.append([3.0, 204, 0.9])
            ws.append([3.5, 345.4, 0.86])
            wb.save(site)

            manifest_path = tmp_path / "manifest.json"
            output = tmp_path / "filled.docx"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "bid-tech-table-fill-v1",
                        "appendixTask": {
                            "id": "APPX-D1",
                            "title": "附表D.1 标准及风电场空气密度功率曲线",
                            "docxPath": str(blank),
                        },
                        "materialIndex": [
                            {"id": "STD", "name": standard.name, "path": str(standard), "materialTier": "project"},
                            {"id": "SITE", "name": site.name, "path": str(site), "materialTier": "project"},
                        ],
                        "outputFile": str(output),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = table_filler.run_from_manifest(manifest_path)

            self.assertEqual(result["fillReport"]["filledFieldCount"], 6)
            filled_doc = Document(str(output))
            rows = filled_doc.tables[0].rows
            self.assertEqual(rows[1].cells[2].text, "0")
            self.assertEqual(rows[1].cells[3].text, "0")
            self.assertEqual(rows[2].cells[2].text, "210")
            self.assertEqual(rows[2].cells[3].text, "204")
            self.assertEqual(rows[3].cells[2].text, "350")
            self.assertEqual(rows[3].cells[3].text, "345.4")

    def test_bid_table_filler_selects_curve_excels_for_blank_ct_curve_matrix(self) -> None:
        table_filler = load_table_filler_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            blank = tmp_path / "附表D.2 标准及风电场空气密度下推力系数曲线.docx"
            doc = Document()
            table = doc.add_table(rows=1, cols=3)
            table.style = "Table Grid"
            for index, text in enumerate(["风速（m/s）", "标准空气密度下推力系数 Ct", "风电场空气密度下推力系数 Ct"]):
                table.cell(0, index).text = text
            for _ in range(3):
                table.add_row()
            doc.save(blank)

            params = tmp_path / "X2平台机型投标参数_20250106.xlsx"
            wb = Workbook()
            ws = wb.active
            ws.title = "主参数"
            ws.append(["对象", "项目", "参数名称", "单位", "W10.0-220"])
            ws.append(["", "", "叶轮直径", "m", 220])
            wb.save(params)

            standard = tmp_path / "RAW-0460-W10.0-220_空气密度1.225_功率曲线.xlsx"
            wb = Workbook()
            ws = wb.active
            ws.title = "功率曲线与发电量"
            ws.append(["风速(m/s)", "修正功率(kW)", "Ct"])
            ws.append([3.0, 210, 0.91])
            ws.append([3.5, 350, 0.87])
            ws.append([4.0, 510, 0.83])
            wb.save(standard)

            site = tmp_path / "RAW-0461-W10.0-220_空气密度1.16_功率曲线.xlsx"
            wb = Workbook()
            ws = wb.active
            ws.title = "功率曲线与发电量"
            ws.append(["风速(m/s)", "修正功率(kW)", "Ct"])
            ws.append([3.0, 204, 0.9])
            ws.append([3.5, 345.4, 0.86])
            ws.append([4.0, 500.2, 0.82])
            wb.save(site)

            manifest_path = tmp_path / "manifest.json"
            output = tmp_path / "filled.docx"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "bid-tech-table-fill-v1",
                        "appendixTask": {
                            "id": "APPX-D2",
                            "title": "附表D.2 标准及风电场空气密度下推力系数曲线",
                            "docxPath": str(blank),
                        },
                        "materialIndex": [
                            {"id": "PARAM", "name": params.name, "path": str(params), "materialTier": "project"},
                            {"id": "STD", "name": standard.name, "path": str(standard), "materialTier": "project"},
                            {"id": "SITE", "name": site.name, "path": str(site), "materialTier": "project"},
                        ],
                        "outputFile": str(output),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = table_filler.run_from_manifest(manifest_path)

            selected_names = [item["name"] for item in result["fillReport"]["sourceSelection"]["selected"]]
            self.assertIn(standard.name, selected_names)
            self.assertIn(site.name, selected_names)
            self.assertEqual(result["fillReport"]["filledFieldCount"], 9)
            filled_doc = Document(str(output))
            rows = filled_doc.tables[0].rows
            self.assertEqual(rows[1].cells[0].text, "3")
            self.assertEqual(rows[1].cells[1].text, "0.91")
            self.assertEqual(rows[1].cells[2].text, "0.9")
            self.assertEqual(rows[3].cells[0].text, "4")
            self.assertEqual(rows[3].cells[1].text, "0.83")
            self.assertEqual(rows[3].cells[2].text, "0.82")

    def test_bid_table_filler_transplants_matching_structured_source_table(self) -> None:
        table_filler = load_table_filler_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            blank = tmp_path / "附表E.1 投标人风资源评估与机位排布方案.docx"
            doc = Document()
            table = doc.add_table(rows=1, cols=6)
            table.style = "Table Grid"
            for index, text in enumerate(["机位编号", "坐标", "海拔高度（m）", "韦布尔参数A", "平均风速（m/s）", "机型"]):
                table.cell(0, index).text = text
            for row in (["", "", "", "", "", ""], ["…", "", "", "", "", ""], ["平均值", "", "", "", "", ""]):
                cells = table.add_row().cells
                for index, text in enumerate(row):
                    cells[index].text = text
            doc.save(blank)

            source_docx = tmp_path / "风资源评估报告.docx"
            doc = Document()
            table = doc.add_table(rows=1, cols=6)
            table.style = "Table Grid"
            for index, text in enumerate(["风机/编号", "X/(m)", "Z/(m)", "韦布尔参数A", "平均风速(m/s)", "机型"]):
                table.cell(0, index).text = text
            for index in range(1, 12):
                cells = table.add_row().cells
                values = [f"A{index:03d}", f"40416{index}", str(700 + index), f"8.{index:02d}", f"7.{index:02d}", "EW10.0-220-125"]
                for col, value in enumerate(values):
                    cells[col].text = value
            doc.save(source_docx)

            manifest_path = tmp_path / "manifest.json"
            output = tmp_path / "filled.docx"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "bid-tech-table-fill-v1",
                        "appendixTask": {
                            "id": "APPX-E1",
                            "title": "附表E.1 投标人风资源评估与机位排布方案",
                            "docxPath": str(blank),
                        },
                        "referenceMaterials": [
                            {"id": "WIND", "name": source_docx.name, "path": str(source_docx), "materialTier": "project"}
                        ],
                        "outputFile": str(output),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = table_filler.run_from_manifest(manifest_path)

            self.assertGreater(result["fillReport"]["filledFieldCount"], 60)
            filled_doc = Document(str(output))
            rows = filled_doc.tables[0].rows
            self.assertEqual(len(rows), 12)
            self.assertEqual(rows[0].cells[0].text, "风机/编号")
            self.assertEqual(rows[1].cells[0].text, "A001")
            self.assertEqual(rows[11].cells[5].text, "EW10.0-220-125")
            self.assertEqual(result["unfilledFields"], [])

    def test_bid_table_filler_generates_load_wind_parameter_group_from_position_table(self) -> None:
        table_filler = load_table_filler_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            blank = tmp_path / "附表G.2.2 投标人对招标项目场址载荷计算选取风参数结果.docx"
            doc = Document()
            table = doc.add_table(rows=1, cols=5)
            table.style = "Table Grid"
            for col in range(5):
                table.cell(0, col).text = "载荷计算风参数分组1"
            for row in (
                ["序号", "机位编号", "机组坐标", "机组坐标", "投标机型"],
                ["序号", "机位编号", "X", "Y", "投标机型"],
                ["1", "1", "", "", ""],
                ["……", "", "", "", ""],
                ["备注：如采用全场包络，只需填写分组1。"] * 5,
            ):
                cells = table.add_row().cells
                for index, text in enumerate(row):
                    cells[index].text = text
            doc.save(blank)

            source_docx = tmp_path / "风资源评估报告.docx"
            doc = Document()
            table = doc.add_table(rows=1, cols=4)
            table.style = "Table Grid"
            for index, text in enumerate(["机位编号", "X", "Y", "机型"]):
                table.cell(0, index).text = text
            for row in (
                ["北区", "北区", "北区", "北区"],
                ["A001", "40416757.857", "4786181.802", "EW10.0-220-125"],
                ["A002", "40416633.400", "4785238.500", "EW10.0-220-125"],
                ["A044", "40431040.541", "4780184.646", "EW10.0-220-125"],
                ["A34", "40425746.863", "4776165.318", "EW10.0-220-125"],
                ["南区", "南区", "南区", "南区"],
                ["BX01", "40436771.920", "4779768.358", "备选"],
            ):
                cells = table.add_row().cells
                for index, text in enumerate(row):
                    cells[index].text = text
            doc.save(source_docx)

            manifest_path = tmp_path / "manifest.json"
            output = tmp_path / "filled.docx"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "bid-tech-table-fill-v1",
                        "appendixTask": {
                            "id": "APPX-G22",
                            "title": "附表G.2.2 投标人对招标项目场址载荷计算选取风参数结果",
                            "docxPath": str(blank),
                        },
                        "referenceMaterials": [
                            {"id": "WIND", "name": source_docx.name, "path": str(source_docx), "materialTier": "project"}
                        ],
                        "outputFile": str(output),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = table_filler.run_from_manifest(manifest_path)

            self.assertEqual(result["unfilledFields"], [])
            filled_doc = Document(str(output))
            rows = filled_doc.tables[0].rows
            self.assertEqual(len(rows), 8)
            self.assertEqual([cell.text for cell in rows[3].cells], ["1", "A001", "40416758", "4786182", "EW10.0-220-125"])
            self.assertEqual([cell.text for cell in rows[4].cells], ["2", "A002", "40416633", "4785239", "EW10.0-220-125"])
            self.assertEqual([cell.text for cell in rows[5].cells], ["3", "A34", "40425747", "4776165", "EW10.0-220-125"])
            self.assertEqual([cell.text for cell in rows[6].cells], ["4", "A044", "40431041", "4780185", "EW10.0-220-125"])
            self.assertEqual(rows[7].cells[0].text, "备注：如采用全场包络，只需填写分组1。")

    def test_bid_table_filler_generates_spare_parts_table_from_quote_xlsx(self) -> None:
        table_filler = load_table_filler_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            blank = tmp_path / "附表B.2 质量保证期备品备件、消耗品清单.docx"
            doc = Document()
            table = doc.add_table(rows=1, cols=8)
            table.style = "Table Grid"
            for index, text in enumerate(["序号", "名称", "型号和规格", "单位", "数量", "备注", "更换周期", "国内替代产品型号"]):
                table.cell(0, index).text = text
            table.add_row()
            doc.save(blank)

            quote = tmp_path / "项目报价文件.xlsx"
            wb = Workbook()
            ws = wb.active
            ws.title = "E 推荐备品备件（如果有）的分项报价"
            ws.append([""] * 10)
            ws.append(["表2 E"] + [""] * 9)
            ws.append(["单位：人民币万元"] + [""] * 9)
            ws.append(["序号", "名称", "规格型号", "单位", "数量", "价格", "总价", "产地", "生产厂家", "备注"])
            ws.append(["一、备品备件部分"] + [""] * 9)
            ws.append([1, "变桨限位开关_FD 2031_S1", "EW10.0-220-125", "EA", 12, "", "", "中国", "上海电气合供", ""])
            ws.append([2, "避雷器DXH06_FCS/3+1R40", "EW10.0-220-125", "EA", 12, "", "", "中国", "上海电气合供", ""])
            ws.append([None, "合计(单台机组)（万元）"] + [""] * 8)
            wb.save(quote)

            manifest_path = tmp_path / "manifest.json"
            output = tmp_path / "filled.docx"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "bid-tech-table-fill-v1",
                        "appendixTask": {
                            "id": "APPX-B2",
                            "title": "附表B.2 质量保证期备品备件、消耗品清单",
                            "docxPath": str(blank),
                        },
                        "referenceMaterials": [
                            {"id": "QUOTE", "name": quote.name, "path": str(quote), "materialTier": "project"}
                        ],
                        "outputFile": str(output),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = table_filler.run_from_manifest(manifest_path)

            filled_doc = Document(str(output))
            rows = filled_doc.tables[0].rows
            self.assertEqual(len(rows), 4)
            self.assertEqual([cell.text for cell in rows[1].cells], ["一、备品备件部分"] * 8)
            self.assertEqual([cell.text for cell in rows[2].cells], ["1", "变桨限位开关_FD 2031_S1", "EW10.0-220-125", "EA", "12", "\\", "\\", "\\"])
            self.assertEqual(result["unfilledFields"], [])

    def test_bid_table_filler_batch_output_names_include_appendix_id_to_avoid_collisions(self) -> None:
        table_filler = load_table_filler_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            blanks = []
            for index, appendix_id in enumerate(("APPX-0014", "APPX-0080", "APPX-0014"), start=1):
                blank = tmp_path / f"{index}-{appendix_id}.docx"
                doc = Document()
                table = doc.add_table(rows=1, cols=3)
                table.style = "Table Grid"
                for index, text in enumerate(["序号", "项目", "投标响应"]):
                    table.cell(0, index).text = text
                cells = table.add_row().cells
                cells[0].text = "1"
                cells[1].text = "投标机型"
                cells[2].text = ""
                doc.save(blank)
                blanks.append((appendix_id, blank))

            manifest_path = tmp_path / "manifest.json"
            output_dir = tmp_path / "outputs"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "bid-tech-table-fill-v1",
                        "projectTurbineModel": {"model": "EW10.0-220上置"},
                        "outputDir": str(output_dir),
                        "targets": [
                            {
                                "id": appendix_id,
                                "title": "附表B.8 出质保后备品备件服务 无",
                                "docxPath": str(blank),
                            }
                            for appendix_id, blank in blanks
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = table_filler.run_from_manifest(manifest_path)

            output_files = [Path(item) for item in result["outputFiles"]]
            self.assertEqual(len(output_files), 3)
            self.assertEqual(len({item.name for item in output_files}), 3)
            self.assertTrue(any("APPX-0014" in item.name for item in output_files))
            self.assertTrue(any("APPX-0080" in item.name for item in output_files))

    def test_bid_table_filler_copies_no_table_appendix_without_failing_batch(self) -> None:
        table_filler = load_table_filler_script("run_from_manifest")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            no_table = tmp_path / "附表B.8 出质保后备品备件服务 无.docx"
            no_table_doc = Document()
            no_table_doc.add_paragraph("附表B.8 出质保后备品备件服务 无")
            no_table_doc.save(no_table)

            normal = tmp_path / "附表A.1 投标机型总方案信息表.docx"
            normal_doc = Document()
            table = normal_doc.add_table(rows=1, cols=3)
            table.style = "Table Grid"
            for index, text in enumerate(["序号", "项目", "投标响应"]):
                table.cell(0, index).text = text
            cells = table.add_row().cells
            cells[0].text = "1"
            cells[1].text = "投标机型"
            cells[2].text = ""
            normal_doc.save(normal)

            manifest_path = tmp_path / "manifest.json"
            output_dir = tmp_path / "outputs"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "bid-tech-table-fill-v1",
                        "projectTurbineModel": {"model": "EW10.0-220上置"},
                        "outputDir": str(output_dir),
                        "targets": [
                            {
                                "id": "APPX-B8",
                                "title": "附表B.8 出质保后备品备件服务 无",
                                "docxPath": str(no_table),
                            },
                            {
                                "id": "APPX-A1",
                                "title": "附表A.1 投标机型总方案信息表",
                                "docxPath": str(normal),
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = table_filler.run_from_manifest(manifest_path)

            self.assertEqual(result["fillReport"]["targetCount"], 2)
            self.assertEqual(result["fillReport"]["failedTargetCount"], 0)
            self.assertEqual(result["fillReport"]["successfulTargetCount"], 2)
            self.assertEqual(len(result["outputFiles"]), 2)
            no_table_result = result["targetResults"][0]
            self.assertEqual(no_table_result["fillReport"]["targetFieldCount"], 0)
            self.assertTrue(Path(no_table_result["outputFile"]).exists())
            copied_doc = Document(no_table_result["outputFile"])
            self.assertEqual(copied_doc.paragraphs[0].text, "附表B.8 出质保后备品备件服务 无")

    def test_bid_assembler_inject_prefix_collapses_heading_level_gaps(self) -> None:
        numbering_fixer = load_assembler_script("numbering_fixer")

        doc = Document()
        doc.add_paragraph("上海电气优势简介", style="Heading 2")
        doc.add_paragraph("基本情况", style="Heading 3")
        doc.add_paragraph("集团概况", style="Heading 4")
        doc.add_paragraph("载荷仿真分析能力", style="Heading 1")
        doc.add_paragraph("测试验证技术", style="Heading 6")

        stats = numbering_fixer.inject_prefix_to_headings(
            doc,
            "1.9",
            toc_title="上海电气优势简介",
            skip_first_if_match=True,
        )
        headings = [para.text.strip().replace("  ", " ") for para in doc.paragraphs if para.text.strip()]

        self.assertTrue(stats["skipped_first"])
        self.assertEqual(
            headings,
            [
                "1.9.1 基本情况",
                "1.9.1.1 集团概况",
                "1.9.2 载荷仿真分析能力",
                "1.9.2.1 测试验证技术",
            ],
        )
        self.assertFalse(any(".0." in item or item.endswith(".0") for item in headings))

    def test_bid_assembler_inject_prefix_clears_stale_direct_outline(self) -> None:
        numbering_fixer = load_assembler_script("numbering_fixer")

        doc = Document()
        doc.add_paragraph("上海电气优势简介", style="Heading 2")
        stale = doc.add_paragraph("载荷仿真分析能力", style="Heading 1")
        p_pr = stale._p.get_or_add_pPr()
        outline = OxmlElement("w:outlineLvl")
        outline.set(qn("w:val"), "0")
        p_pr.append(outline)

        numbering_fixer.inject_prefix_to_headings(
            doc,
            "1.9",
            toc_title="上海电气优势简介",
            skip_first_if_match=True,
        )

        remaining = [para for para in doc.paragraphs if "载荷仿真分析能力" in para.text][0]
        self.assertEqual(remaining.style.name, "Heading 3")
        p_pr = remaining._p.find(qn("w:pPr"))
        self.assertIsNotNone(p_pr)
        self.assertIsNone(p_pr.find(qn("w:outlineLvl")))

    def test_bid_assembler_demotes_material_headings_to_body(self) -> None:
        numbering_fixer = load_assembler_script("numbering_fixer")

        doc = Document()
        doc.add_paragraph("上海电气优势简介", style="Heading 2")
        doc.add_paragraph("基本情况", style="Heading 3")
        stale = doc.add_paragraph("载荷仿真分析能力", style="Heading 1")
        p_pr = stale._p.get_or_add_pPr()
        outline = OxmlElement("w:outlineLvl")
        outline.set(qn("w:val"), "0")
        p_pr.append(outline)

        stats = numbering_fixer.demote_headings_to_body(
            doc,
            toc_title="上海电气优势简介",
            remove_first_if_match=True,
        )

        self.assertEqual(stats["removed"], 1)
        self.assertEqual(stats["demoted"], 2)
        self.assertEqual([para.text for para in doc.paragraphs], ["基本情况", "载荷仿真分析能力"])
        self.assertFalse(any((para.style.name or "").startswith("Heading") for para in doc.paragraphs))
        self.assertTrue(all(para._p.find(qn("w:pPr")).find(qn("w:outlineLvl")) is None for para in doc.paragraphs))

    def test_bid_assembler_demotes_direct_outline_without_body_style(self) -> None:
        numbering_fixer = load_assembler_script("numbering_fixer")

        doc = Document()
        styled = doc.add_paragraph("发电小时数承诺函", style="Heading 2")
        direct_only = doc.add_paragraph("发电量保证矩阵表")
        direct_p_pr = direct_only._p.get_or_add_pPr()
        outline = OxmlElement("w:outlineLvl")
        outline.set(qn("w:val"), "0")
        direct_p_pr.append(outline)

        styles_el = doc.styles._element
        for style in list(styles_el.findall(qn("w:style"))):
            if style.get(qn("w:styleId")) == "Normal":
                styles_el.remove(style)

        stats = numbering_fixer.demote_headings_to_body(doc)

        self.assertEqual(stats["demoted"], 2)
        for para in (styled, direct_only):
            p_pr = para._p.find(qn("w:pPr"))
            self.assertIsNotNone(p_pr)
            self.assertIsNone(p_pr.find(qn("w:pStyle")))
            self.assertIsNone(p_pr.find(qn("w:outlineLvl")))

    def test_bid_assembler_keeps_s2_child_headings_from_material(self) -> None:
        numbering_fixer = load_assembler_script("numbering_fixer")

        doc = Document()
        doc.add_paragraph("项目技术承诺函", style="Heading 1")
        child = doc.add_paragraph("发电小时数承诺函", style="Heading 2")
        extra = doc.add_paragraph("发电量保证矩阵表")
        p_pr = extra._p.get_or_add_pPr()
        outline = OxmlElement("w:outlineLvl")
        outline.set(qn("w:val"), "0")
        p_pr.append(outline)

        stats = numbering_fixer.demote_headings_to_body(
            doc,
            toc_title="项目技术承诺函",
            remove_first_if_match=True,
            keep_heading_map={
                "发电小时数承诺函": {
                    "chapter_no": "4.1",
                    "title": "发电小时数承诺函",
                    "level": 2,
                }
            },
        )

        self.assertEqual(stats["removed"], 1)
        self.assertEqual(stats["kept"], 1)
        self.assertEqual(stats["demoted"], 1)
        self.assertEqual(child.text.strip().replace("  ", " "), "4.1 发电小时数承诺函")
        self.assertEqual(child.style.name, "Heading 2")
        extra_p_pr = extra._p.find(qn("w:pPr"))
        self.assertIsNone(extra_p_pr.find(qn("w:pStyle")))
        self.assertIsNone(extra_p_pr.find(qn("w:outlineLvl")))

    def test_bid_assembler_strips_heading_style_numbering(self) -> None:
        numbering_fixer = load_assembler_script("numbering_fixer")

        with tempfile.TemporaryDirectory() as tmp:
            docx_path = Path(tmp) / "numbered-heading.docx"
            doc = Document()
            heading_style = doc.styles["Heading 2"]
            p_pr = heading_style.element.get_or_add_pPr()
            num_pr = OxmlElement("w:numPr")
            ilvl = OxmlElement("w:ilvl")
            ilvl.set(qn("w:val"), "1")
            num_id = OxmlElement("w:numId")
            num_id.set(qn("w:val"), "1")
            num_pr.append(ilvl)
            num_pr.append(num_id)
            p_pr.append(num_pr)
            doc.add_paragraph("1.7 投标方案优势说明", style="Heading 2")

            self.assertEqual(numbering_fixer.strip_numPr_from_heading_styles(doc), 1)
            doc.save(docx_path)

            with zipfile.ZipFile(docx_path) as zf:
                styles_xml = zf.read("word/styles.xml").decode("utf-8")

        match = re.search(r'(<w:style[^>]+w:styleId="Heading2"[^>]*>.*?</w:style>)', styles_xml)
        self.assertIsNotNone(match)
        self.assertNotIn("<w:numPr>", match.group(1))

    def test_bid_assembler_merges_oversize_material_instead_of_placeholder(self) -> None:
        merger = load_assembler_script("merger")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.docx"
            source = root / "lib" / "投标机型业绩情况.docx"
            out = root / "out.docx"
            prep = root / "prep"

            master = Document()
            master.add_paragraph("")
            master.save(template)

            source.parent.mkdir(parents=True)
            doc = Document()
            doc.add_paragraph("投标机型业绩情况", style="Heading 1")
            doc.add_paragraph("这里是业绩正文")
            doc.save(source)

            plan = [
                {
                    "status": "MATCHED",
                    "level": 2,
                    "title": "投标机型业绩情况",
                    "chapter_no": "1.8",
                    "chapter_no_flat": "1.8",
                    "paths": [source.name],
                }
            ]
            original_stat = Path.stat

            class FakeStat:
                def __init__(self, wrapped):
                    self._wrapped = wrapped
                    self.st_size = 234 * 1024 * 1024

                def __getattr__(self, name):
                    return getattr(self._wrapped, name)

            def fake_stat(path, *args, **kwargs):
                value = original_stat(path, *args, **kwargs)
                if Path(path).resolve() == source.resolve():
                    return FakeStat(value)
                return value

            with patch.object(Path, "stat", fake_stat):
                stats = merger.merge(template, plan, source.parent, {}, prep, out)

            result = Document(str(out))
            text = "\n".join(para.text for para in result.paragraphs)

        self.assertEqual(stats["merged_materials"], 1)
        self.assertNotIn("大素材跳过", text)
        self.assertIn("这里是业绩正文", text)

    def test_bid_assembler_merger_keeps_only_toc_heading_in_navigation(self) -> None:
        merger = load_assembler_script("merger")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.docx"
            source = root / "lib" / "上海电气优势简介.docx"
            out = root / "out.docx"
            prep = root / "prep"

            master = Document()
            master.add_paragraph("")
            master.save(template)

            source.parent.mkdir(parents=True)
            doc = Document()
            doc.add_paragraph("上海电气优势简介", style="Heading 2")
            doc.add_paragraph("基本情况", style="Heading 3")
            stale = doc.add_paragraph("载荷仿真分析能力", style="Heading 1")
            p_pr = stale._p.get_or_add_pPr()
            outline = OxmlElement("w:outlineLvl")
            outline.set(qn("w:val"), "0")
            p_pr.append(outline)
            doc.add_paragraph("这里是正文")
            doc.save(source)

            plan = [
                {
                    "status": "MATCHED",
                    "level": 2,
                    "title": "上海电气优势简介",
                    "chapter_no": "1.9",
                    "chapter_no_flat": "1.9",
                    "paths": [source.name],
                }
            ]
            merger.merge(template, plan, source.parent, {}, prep, out)

            result = Document(str(out))
            headings = [
                para.text.strip().replace("  ", " ")
                for para in result.paragraphs
                if (para.style.name or "").startswith("Heading") and para.text.strip()
            ]
            text = "\n".join(para.text for para in result.paragraphs)

        self.assertEqual(headings, ["1.9 上海电气优势简介"])
        self.assertIn("基本情况", text)
        self.assertIn("载荷仿真分析能力", text)

    def test_bid_assembler_merger_keeps_matching_child_heading_in_place(self) -> None:
        merger = load_assembler_script("merger")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.docx"
            source = root / "lib" / "项目技术承诺函.docx"
            out = root / "out.docx"
            prep = root / "prep"

            master = Document()
            master.add_paragraph("")
            master.save(template)

            source.parent.mkdir(parents=True)
            doc = Document()
            doc.add_paragraph("项目技术承诺函", style="Heading 1")
            doc.add_paragraph("发电小时数承诺函", style="Heading 2")
            doc.add_paragraph("这里是 4.1 正文")
            doc.save(source)

            plan = [
                {
                    "status": "MATCHED",
                    "level": 1,
                    "title": "项目技术承诺函",
                    "chapter_no": "第四章",
                    "chapter_no_flat": "4",
                    "paths": [source.name],
                },
                {
                    "status": "UNMATCHED",
                    "level": 2,
                    "title": "发电小时数承诺函",
                    "chapter_no": "4.1",
                    "chapter_no_flat": "4.1",
                    "paths": [],
                },
            ]
            merger.merge(template, plan, source.parent, {}, prep, out)

            result = Document(str(out))
            headings = [
                para.text.strip().replace("  ", " ")
                for para in result.paragraphs
                if (para.style.name or "").startswith("Heading") and para.text.strip()
            ]
            text = "\n".join(para.text for para in result.paragraphs)

        self.assertEqual(headings, ["第四章 项目技术承诺函", "4.1 发电小时数承诺函"])
        self.assertIn("这里是 4.1 正文", text)
        self.assertNotIn("[缺失：发电小时数承诺函", text)

    def test_bid_assembler_verify_uses_direct_outline_level_priority(self) -> None:
        verify = load_assembler_script("verify")

        with tempfile.TemporaryDirectory() as tmp:
            docx_path = Path(tmp) / "stale-outline.docx"
            doc = Document()
            stale = doc.add_paragraph("1.9.4  载荷仿真分析能力", style="Heading 3")
            p_pr = stale._p.get_or_add_pPr()
            outline = OxmlElement("w:outlineLvl")
            outline.set(qn("w:val"), "0")
            p_pr.append(outline)
            doc.save(docx_path)

            scan = verify.scan_docx(docx_path)

        self.assertEqual(scan["heading_counts"], {"Heading 1": 1})
        self.assertIn("1.9.4  载荷仿真分析能力", scan["invalid_h1"])

if __name__ == "__main__":
    unittest.main()
