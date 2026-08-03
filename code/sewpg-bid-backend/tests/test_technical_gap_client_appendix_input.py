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
_SPEC = importlib.util.spec_from_file_location("tech_gap_planner_client_appendix_under_test", _SRC)
planner = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(planner)

_INPUT_FOLDER = "技术标/项目定制/华能/技术附表输入文件"


def _client_material(material_id: str, name: str) -> dict:
    return {
        "id": material_id,
        "name": name,
        "folderPath": _INPUT_FOLDER,
        "materialTier": "project",
        "cleanedFileName": name,
    }


class ClientAppendixFileKeyTests(unittest.TestCase):
    def test_exact_code_file(self) -> None:
        self.assertEqual(
            planner.client_appendix_file_keys(_client_material("RAW-1", "附表B.5 培训内容和计划表.docx")),
            ("B.5", ""),
        )

    def test_group_file_without_table_char(self) -> None:
        # 「技术附H」无「表」字：整组替换，覆盖 H.1/H.2/…
        self.assertEqual(
            planner.client_appendix_file_keys(_client_material("RAW-2", "技术附H 包装、标志、运输、保管和交付的特殊要求.docx")),
            ("", "H"),
        )

    def test_group_file_with_table_char(self) -> None:
        self.assertEqual(
            planner.client_appendix_file_keys(_client_material("RAW-3", "技术附表I 技术条款偏差表.docx")),
            ("", "I"),
        )

    def test_unrelated_file_has_no_key(self) -> None:
        self.assertEqual(
            planner.client_appendix_file_keys(_client_material("RAW-4", "业绩情况.docx")),
            ("", ""),
        )


class ClientAppendixInputIndexTests(unittest.TestCase):
    def test_scoped_by_convention_folder(self) -> None:
        outside = {
            "id": "RAW-9",
            "name": "附表B.5 培训内容和计划表.docx",
            "folderPath": "技术标/项目定制/华能/附表",
            "materialTier": "project",
        }
        index = planner.client_appendix_input_index([outside, _client_material("RAW-1", "附表B.5 培训内容和计划表.docx")])
        self.assertEqual(set(index["exact"].keys()), {"B.5"})
        self.assertEqual(index["exact"]["B.5"]["id"], "RAW-1")

    def test_ambiguous_same_code_not_auto_attached(self) -> None:
        index = planner.client_appendix_input_index([
            _client_material("RAW-1", "附表B.5 培训内容和计划表.docx"),
            _client_material("RAW-2", "附表B.5 培训内容和计划表-副本.docx"),
        ])
        self.assertIn("B.5", index["ambiguous"])
        material, key = planner.client_appendix_input_match({"title": "附表B.5 培训内容和计划表"}, index)
        self.assertIsNone(material)
        self.assertEqual(key, "")


class ClientAppendixInputMatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = planner.client_appendix_input_index([
            _client_material("RAW-1", "附表B.5 培训内容和计划表.docx"),
            _client_material("RAW-2", "技术附H 包装、标志、运输、保管和交付的特殊要求.docx"),
            _client_material("RAW-5", "附表G.3 钢塔筒招标项目场址设计安全性.docx"),
        ])

    def test_exact_code_hit(self) -> None:
        material, key = planner.client_appendix_input_match({"title": "附表B.5 培训内容和计划表"}, self.index)
        self.assertEqual(material["id"], "RAW-1")
        self.assertEqual(key, "B.5")

    def test_group_file_covers_sub_tables(self) -> None:
        for title in ("附表H.1 包装要求", "附表H.2 标志要求", "附表H.3 运输要求"):
            material, key = planner.client_appendix_input_match({"title": title}, self.index)
            self.assertEqual(material["id"], "RAW-2", title)
            self.assertEqual(key, "H")

    def test_subgroup_file_covers_deeper_sub_tables(self) -> None:
        # 「附表G.3」文件覆盖 G.3.1/G.3.2/…，与「技术附H」的整组语义一致
        for title in ("附表G.3.1 关键设计方法", "附表G.3.4 塔筒疲劳强度安全余量"):
            material, key = planner.client_appendix_input_match({"title": title}, self.index)
            self.assertEqual(material["id"], "RAW-5", title)
            self.assertEqual(key, "G.3")

    def test_exact_code_wins_over_subgroup_prefix(self) -> None:
        index = planner.client_appendix_input_index([
            _client_material("RAW-5", "附表G.3 钢塔筒招标项目场址设计安全性.docx"),
            _client_material("RAW-6", "附表G.3.1 关键设计方法.docx"),
        ])
        material, key = planner.client_appendix_input_match({"title": "附表G.3.1 关键设计方法"}, index)
        self.assertEqual(material["id"], "RAW-6")
        self.assertEqual(key, "G.3.1")
        material, key = planner.client_appendix_input_match({"title": "附表G.3.2 塔筒极限强度设计安全余量"}, index)
        self.assertEqual(material["id"], "RAW-5")
        self.assertEqual(key, "G.3")

    def test_miss_returns_none(self) -> None:
        material, key = planner.client_appendix_input_match({"title": "附表C.8 升降机"}, self.index)
        self.assertIsNone(material)
        self.assertEqual(key, "")


class ClientAppendixPlanIntegrationTests(unittest.TestCase):
    def _build_plan(self) -> dict:
        toc = {
            "items": [
                {"id": "t1", "number": "1", "title": "投标方案", "level": 1},
                {"id": "t2", "number": "附表H.1", "title": "附表H.1 包装要求", "level": 1},
                {"id": "t3", "number": "附表H.2", "title": "附表H.2 标志要求", "level": 1},
                {"id": "t4", "number": "附表C.8", "title": "附表C.8 升降机", "level": 1},
                {"id": "t5", "number": "附表B.5", "title": "附表B.5 培训内容和计划表", "level": 1},
            ]
        }
        parse_result = {
            "structured": {
                "appendices": [
                    {"id": "APPX-1", "title": "附表H.1 包装要求", "docxPath": "/tmp/a1.docx"},
                    {"id": "APPX-2", "title": "附表H.2 标志要求", "docxPath": "/tmp/a2.docx"},
                    {"id": "APPX-3", "title": "附表C.8 升降机", "docxPath": "/tmp/a3.docx"},
                    {"id": "APPX-4", "title": "附表B.5 培训内容和计划表", "docxPath": "/tmp/a4.docx"},
                ]
            }
        }
        manifest = {
            "projectId": "PRJ-TEST",
            "tocJsonPath": "",
            "parseResultPath": "",
            "materialIndex": [
                _client_material("RAW-2", "技术附H 包装、标志、运输、保管和交付的特殊要求.docx"),
                _client_material("RAW-3", "附表C.8 升降机.docx"),
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            toc_path = Path(tmp) / "toc.json"
            parse_path = Path(tmp) / "parse.json"
            toc_path.write_text(json.dumps(toc, ensure_ascii=False), encoding="utf-8")
            parse_path.write_text(json.dumps(parse_result, ensure_ascii=False), encoding="utf-8")
            manifest["tocJsonPath"] = str(toc_path)
            manifest["parseResultPath"] = str(parse_path)
            return planner.build_gap_plan(manifest)

    def test_client_provided_items_ready_and_resolved(self) -> None:
        plan = self._build_plan()
        by_number = {str(item.get("number") or ""): item for item in plan["items"]}

        for number in ("附表H.1", "附表H.2", "附表C.8"):
            item = by_number[number]
            self.assertEqual(item["decision"], "ready", number)
            self.assertEqual(item["status"], "resolved", number)
            self.assertEqual(item["fillTasks"], [], number)
            self.assertEqual(item["nextActions"], [], number)
            self.assertEqual(len(item["resolvedArtifacts"]), 1, number)
            artifact = item["resolvedArtifacts"][0]
            self.assertEqual(artifact["source"], "client_appendix_input")
            self.assertTrue(artifact["s7Ready"])
            self.assertTrue(artifact["materialId"])
            routing = item["appendixTasks"][0]["sourceRouting"]
            self.assertEqual(routing["status"], "client_provided", number)

        # 整组替换：H.1/H.2 都指向同一份「技术附H」文件
        self.assertEqual(
            by_number["附表H.1"]["resolvedArtifacts"][0]["materialId"],
            by_number["附表H.2"]["resolvedArtifacts"][0]["materialId"],
        )
        # 未命中的附表保持待填写
        pending = by_number["附表B.5"]
        self.assertEqual(pending["decision"], "fill_required")
        self.assertEqual(len(pending["fillTasks"]), 1)
        self.assertEqual(pending["resolvedArtifacts"], [])

    def test_client_input_files_excluded_from_chapter_pool(self) -> None:
        plan = self._build_plan()
        for item in plan["items"]:
            for material in (item.get("matchedMaterials") or []) + (item.get("candidateMaterials") or []):
                self.assertNotIn(
                    planner.CLIENT_APPENDIX_INPUT_FOLDER,
                    str(material.get("folderPath") or ""),
                    f"{item.get('number')} 候选池混入甲方附表输入文件",
                )


if __name__ == "__main__":
    unittest.main()
