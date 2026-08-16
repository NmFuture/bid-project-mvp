"""部件认证的品牌选取单测：品牌清单 + 候选清单 → AI 选一份 → 备料按它取素材。

AI 只做「从给定候选里选 0 或 1 份 + 给理由」这一件事，自由度必须框死：编出来的文件名
要挡回去、选不出来要明说、调不通要标黄而不是静默跳过。
fixture 为脱敏合成数据（厂家名与文件名皆为构造值）。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from app.services import technical_brand_pick as brand_pick
from app.services import technical_gap_ai_fill as ai_fill

GEARBOX_DIR = "技术标/标准文件/EW10.0-220上置/认证证书/部件认证/齿轮箱"
BEARING_DIR = "技术标/标准文件/EW10.0-220上置/认证证书/部件认证/主轴承"

GEARBOX_A = "EW10.0-220上置-CGC2024（甲厂）HB9000H齿轮箱型式认证A.pdf"
GEARBOX_B = "EW10.0-220上置-CGC2025（乙厂）SMG434齿轮箱型式认证A.pdf"


def _material(name: str, folder: str, material_id: str = "RAW-1") -> dict[str, Any]:
    return {"id": material_id, "name": name, "folderPath": folder, "materialTier": "standard"}


class BrandListLookupTests(unittest.TestCase):
    def test_picks_the_component_brand_xlsx_out_of_the_shortlist_folder(self) -> None:
        """短名单目录下还有一份内部采购短名单，靠文件名里的「大部件品牌」区分。"""
        candidates = [
            _material("采购部短名单(常规版）20260108.xlsx", "技术标/项目定制/某项目/短名单", "RAW-1"),
            _material("华能集团2025年第5批集采投标项目大部件品牌.xlsx", "技术标/项目定制/某项目/短名单", "RAW-2"),
            _material("大部件品牌参考.docx", "技术标/项目定制/某项目/短名单", "RAW-3"),
        ]

        found = brand_pick.find_brand_list_material(candidates)

        self.assertIsNotNone(found)
        self.assertEqual(found["id"], "RAW-2")

    def test_brand_xlsx_outside_shortlist_folder_is_not_used(self) -> None:
        candidates = [_material("某项目大部件品牌.xlsx", "技术标/项目定制/某项目/其他", "RAW-9")]

        self.assertIsNone(brand_pick.find_brand_list_material(candidates))

    def test_absent_brand_list_is_not_an_error(self) -> None:
        self.assertIsNone(brand_pick.find_brand_list_material([]))


class PromptTests(unittest.TestCase):
    def test_prompt_carries_model_brand_table_and_only_the_given_candidates(self) -> None:
        prompt = brand_pick.build_prompt(
            "EW10.0-220上置",
            "齿轮箱 | 甲厂、乙厂 | 10-220: 乙厂",
            {"齿轮箱": [GEARBOX_A, GEARBOX_B]},
        )

        self.assertIn("EW10.0-220上置", prompt)
        self.assertIn("10-220: 乙厂", prompt)
        self.assertIn(GEARBOX_A, prompt)
        self.assertIn(GEARBOX_B, prompt)
        # 边界必须写进 prompt：只能选给定候选、选不出要明说、理由要能核对
        self.assertIn("只能从上面给出的候选里原样照抄文件名", prompt)
        self.assertIn(brand_pick.PICK_STATUS_NOT_AVAILABLE, prompt)


class RequestBrandPicksTests(unittest.TestCase):
    def _client(self, reply: str) -> Any:
        class _Client:
            def __init__(self) -> None:
                self.tools: dict[str, bool] | None = None

            def send_text_prompt(self, _title: str, _prompt: str, *, tools=None):
                self.tools = tools
                return {"reply": reply}

        return _Client()

    def test_disables_every_tool_so_the_model_cannot_search_the_library(self) -> None:
        client = self._client(
            '{"picks": [{"component": "齿轮箱", "brand": "乙厂", '
            f'"materialName": "{GEARBOX_B}", "reason": "文件名含乙厂", "status": "ok"}}]}}'
        )

        brand_pick.request_brand_picks("EW10.0-220上置", "表", {"齿轮箱": [GEARBOX_A, GEARBOX_B]}, client=client)

        self.assertTrue(client.tools)
        self.assertFalse(any(client.tools.values()))

    def test_parses_pick_wrapped_in_code_fence(self) -> None:
        client = self._client(
            "```json\n"
            '{"picks": [{"component": "齿轮箱", "brand": "乙厂", '
            f'"materialName": "{GEARBOX_B}", "reason": "文件名含乙厂", "status": "ok"}}]}}'
            "\n```"
        )

        picks = brand_pick.request_brand_picks(
            "EW10.0-220上置", "表", {"齿轮箱": [GEARBOX_A, GEARBOX_B]}, client=client
        )

        self.assertEqual(len(picks), 1)
        self.assertEqual(picks[0]["materialNames"], [GEARBOX_B])
        self.assertEqual(picks[0]["status"], brand_pick.PICK_STATUS_OK)
        self.assertEqual(picks[0]["source"], "ai")

    def test_fabricated_file_name_is_rejected_not_inserted(self) -> None:
        """模型偶尔会补全省略号或拼接两份候选，放过去等于往标书里插一份不存在的证书。"""
        client = self._client(
            '{"picks": [{"component": "齿轮箱", "brand": "乙厂", '
            '"materialName": "EW10.0-220上置-（乙厂）齿轮箱型式认证.pdf", "reason": "…", "status": "ok"}]}'
        )

        picks = brand_pick.request_brand_picks(
            "EW10.0-220上置", "表", {"齿轮箱": [GEARBOX_A, GEARBOX_B]}, client=client
        )

        self.assertEqual(picks[0]["status"], brand_pick.PICK_STATUS_NOT_AVAILABLE)
        self.assertEqual(picks[0]["materialNames"], [])

    def test_two_brands_two_certificates(self) -> None:
        """业务规则：投一个放一个、投多个放多个。品牌清单一格两个品牌就该选两份。"""
        client = self._client(
            '{"picks": [{"component": "齿轮箱", "brand": "甲厂、乙厂", '
            f'"materialNames": ["{GEARBOX_B}", "{GEARBOX_A}"], "reason": "两个品牌都在清单里", "status": "ok"}}]}}'
        )

        picks = brand_pick.request_brand_picks(
            "EW10.0-220上置", "表", {"齿轮箱": [GEARBOX_A, GEARBOX_B]}, client=client
        )

        # 顺序按 AI 给的（＝品牌清单里的先后），不重排
        self.assertEqual(picks[0]["materialNames"], [GEARBOX_B, GEARBOX_A])
        self.assertEqual(picks[0]["status"], brand_pick.PICK_STATUS_OK)

    def test_partial_match_keeps_the_available_ones(self) -> None:
        """两个品牌只有一个有证书：有的照选，另一个由 reason 说明缺什么。"""
        client = self._client(
            '{"picks": [{"component": "齿轮箱", "brand": "乙厂、丙厂", '
            f'"materialNames": ["{GEARBOX_B}", "丙厂齿轮箱认证.pdf"], "reason": "丙厂的候选里没有", "status": "ok"}}]}}'
        )

        picks = brand_pick.request_brand_picks(
            "EW10.0-220上置", "表", {"齿轮箱": [GEARBOX_A, GEARBOX_B]}, client=client
        )

        # 编造/缺失的那份被挡掉，真实存在的保留
        self.assertEqual(picks[0]["materialNames"], [GEARBOX_B])

    def test_legacy_single_value_reply_is_still_accepted(self) -> None:
        """prompt 改成数组后模型偶尔仍回单值，收成数组而不是当成没选。"""
        client = self._client(
            '{"picks": [{"component": "齿轮箱", "brand": "乙厂", '
            f'"materialName": "{GEARBOX_B}", "reason": "文件名含乙厂", "status": "ok"}}]}}'
        )

        picks = brand_pick.request_brand_picks(
            "EW10.0-220上置", "表", {"齿轮箱": [GEARBOX_A, GEARBOX_B]}, client=client
        )

        self.assertEqual(picks[0]["materialNames"], [GEARBOX_B])

    def test_not_available_is_kept_with_its_reason(self) -> None:
        client = self._client(
            '{"picks": [{"component": "齿轮箱", "brand": "丙厂", "materialName": "", '
            '"reason": "品牌清单投丙厂，候选里只有甲厂和乙厂", "status": "not_available"}]}'
        )

        picks = brand_pick.request_brand_picks(
            "EW10.0-220上置", "表", {"齿轮箱": [GEARBOX_A, GEARBOX_B]}, client=client
        )

        self.assertEqual(picks[0]["status"], brand_pick.PICK_STATUS_NOT_AVAILABLE)
        self.assertIn("只有甲厂和乙厂", picks[0]["reason"])

    def test_unparseable_reply_raises_instead_of_returning_nothing(self) -> None:
        client = self._client("我觉得应该选乙厂那份。")

        with self.assertRaises(brand_pick.BrandPickError):
            brand_pick.request_brand_picks(
                "EW10.0-220上置", "表", {"齿轮箱": [GEARBOX_A, GEARBOX_B]}, client=client
            )

    def test_no_component_means_no_call_at_all(self) -> None:
        client = self._client("{}")

        self.assertEqual(brand_pick.request_brand_picks("EW10.0-220上置", "表", {}, client=client), [])
        self.assertIsNone(client.tools)


class PicksByComponentTests(unittest.TestCase):
    def test_manual_pick_wins_over_ai_pick_for_the_same_component(self) -> None:
        index = brand_pick.picks_by_component(
            [
                {"component": "齿轮箱", "materialNames": [GEARBOX_A], "source": "manual"},
                {"component": "齿轮箱", "materialNames": [GEARBOX_B], "source": "ai"},
            ]
        )

        self.assertEqual(index[brand_pick._norm("齿轮箱")]["materialNames"], [GEARBOX_A])


class EmbedUsesBrandPickTests(unittest.TestCase):
    """备料按品牌选取结果取素材：选中了就走正常嵌入，没选出来标黄不静默。"""

    def setUp(self) -> None:
        self.project = {"id": "PRJ-0001", "name": "示例项目", "bidType": "技术标"}
        self.materials = [
            _material(GEARBOX_A, GEARBOX_DIR, "RAW-1"),
            _material(GEARBOX_B, GEARBOX_DIR, "RAW-2"),
        ]
        self.rules = [
            {
                "seq": 1,
                "folder": "客户定制-华能",
                "targetFile": "待填写-方案",
                "placeholder": "[齿轮箱型式认证-完整插入，待插入]",
                "material": "齿轮箱",
                "headingStart": "",
                "headingEnd": "",
            }
        ]

    def _run(self, brand_picks: dict[str, Any], extra: tuple = ()) -> list[dict]:
        from contextlib import ExitStack
        from docx import Document

        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            blank = tmp / "待填写-方案.docx"
            document = Document()
            document.add_paragraph("[齿轮箱型式认证-完整插入，待插入]")
            document.save(str(blank))
            project = {**self.project, "gap_state": {"brandPicks": brand_picks}}
            with ExitStack() as stack:
                for context in (
                    patch.object(ai_fill, "load_embed_rules", return_value=self.rules),
                    patch.object(ai_fill, "build_project_material_scope", return_value={"readableScopes": []}),
                    patch.object(ai_fill, "project_turbine_model", return_value={"model": "EW10.0-220上置"}),
                    patch.object(ai_fill, "_allowed_technical_material_index", return_value=self.materials),
                    patch.object(ai_fill, "mutate_technical_gap_project"),
                    *extra,
                ):
                    stack.enter_context(context)
                return ai_fill._embed_sources_for_fill(project, blank, tmp)

    def test_picked_certificate_goes_through_normal_embedding(self) -> None:
        payload = {"bucket": "materials", "key": f"raw/{GEARBOX_B}", "fileName": GEARBOX_B, "mimeType": "application/pdf"}

        def _run_async_stub(awaitable: object):
            if hasattr(awaitable, "close"):
                awaitable.close()
            return payload

        sources = self._run(
            {
                "picks": [
                    {
                        "component": "齿轮箱",
                        "brand": "乙厂",
                        "materialNames": [GEARBOX_B],
                        "reason": "文件名含乙厂",
                        "status": "ok",
                        "source": "ai",
                    }
                ],
                "error": "",
            },
            extra=(
                patch.object(ai_fill, "_run_async", side_effect=_run_async_stub),
                patch.object(ai_fill.minio_client, "download_file", side_effect=RuntimeError("stop before convert")),
            ),
        )

        # 走到了转换环节说明品牌选取已把 RAW-2 定下来了，不再是 need_brand
        self.assertNotEqual(sources[0]["status"], "need_brand")
        self.assertEqual(sources[0]["name"], GEARBOX_B)

    def test_two_certificates_become_two_ordered_embed_sources(self) -> None:
        """投两个品牌就插两份：一个占位符产出两条 embedSource，顺序即插入顺序。"""
        payload = {"bucket": "materials", "key": "raw/x.pdf", "fileName": "x.pdf", "mimeType": "application/pdf"}

        def _run_async_stub(awaitable: object):
            if hasattr(awaitable, "close"):
                awaitable.close()
            return payload

        sources = self._run(
            {
                "picks": [
                    {
                        "component": "齿轮箱",
                        "brand": "乙厂、甲厂",
                        "materialNames": [GEARBOX_B, GEARBOX_A],
                        "reason": "两个品牌都在清单里",
                        "status": "ok",
                        "source": "ai",
                    }
                ],
                "error": "",
            },
            extra=(
                patch.object(ai_fill, "_run_async", side_effect=_run_async_stub),
                patch.object(ai_fill.minio_client, "download_file", side_effect=RuntimeError("stop before convert")),
            ),
        )

        self.assertEqual(len(sources), 2)
        self.assertEqual([s["name"] for s in sources], [GEARBOX_B, GEARBOX_A])
        # filler 按 embedOrder 依次嵌入，之间隔一个空段
        self.assertEqual([s["embedOrder"] for s in sources], [0, 1])
        self.assertEqual({s["embedTotal"] for s in sources}, {2})
        # 同一个占位符，filler 才知道这两份要插在同一处
        self.assertEqual({s["placeholder"] for s in sources}, {"齿轮箱型式认证-完整插入"})

    def test_single_certificate_carries_no_order_fields(self) -> None:
        """只插一份时不带 embedOrder/embedTotal，manifest 不长出没用的字段。"""
        sources = self._run(
            {
                "picks": [
                    {
                        "component": "齿轮箱",
                        "brand": "乙厂",
                        "materialNames": [GEARBOX_B],
                        "reason": "文件名含乙厂",
                        "status": "ok",
                        "source": "ai",
                    }
                ],
                "error": "",
            },
            extra=(patch.object(ai_fill, "_run_async", side_effect=RuntimeError("stop here")),),
        )

        self.assertEqual(len(sources), 1)
        self.assertNotIn("embedOrder", sources[0])

    def test_not_available_pick_is_held_with_the_ai_reason(self) -> None:
        sources = self._run(
            {
                "picks": [
                    {
                        "component": "齿轮箱",
                        "brand": "丙厂",
                        "materialNames": [],
                        "reason": "品牌清单投丙厂，候选里只有甲厂和乙厂",
                        "status": "not_available",
                        "source": "ai",
                    }
                ],
                "error": "",
            }
        )

        self.assertEqual(sources[0]["status"], "need_brand")
        self.assertEqual(sources[0]["brand"], "丙厂")
        self.assertIn("只有甲厂和乙厂", sources[0]["statusMessage"])

    def test_brand_list_failure_is_surfaced_not_swallowed(self) -> None:
        sources = self._run({"picks": [], "error": "项目素材范围内没有找到大部件品牌清单。"})

        self.assertEqual(sources[0]["status"], "need_brand")
        self.assertIn("没有找到大部件品牌清单", sources[0]["statusMessage"])

    def test_pick_naming_a_certificate_outside_the_candidates_is_held(self) -> None:
        """人工改错了名字、或候选换了而选取结果没重跑，都不能拿别的文件顶上。"""
        sources = self._run(
            {
                "picks": [
                    {
                        "component": "齿轮箱",
                        "brand": "乙厂",
                        "materialNames": ["别的项目的齿轮箱认证.pdf"],
                        "reason": "手工指定",
                        "status": "ok",
                        "source": "manual",
                    }
                ],
                "error": "",
            }
        )

        self.assertEqual(sources[0]["status"], "need_brand")
        self.assertIn("不在本项目候选里", sources[0]["statusMessage"])


class ComponentGroupingTests(unittest.TestCase):
    def test_groups_candidates_by_component_folder_name(self) -> None:
        groups = ai_fill._all_component_cert_groups(
            [
                _material(GEARBOX_A, GEARBOX_DIR, "RAW-1"),
                _material(GEARBOX_B, GEARBOX_DIR, "RAW-2"),
                _material("（丙厂）主轴承型式认证.pdf", BEARING_DIR, "RAW-3"),
                _material("基础弯矩表.xlsx", "技术标/标准文件/EW10.0-220上置/专题", "RAW-4"),
            ]
        )

        self.assertEqual(sorted(groups), ["主轴承", "齿轮箱"])
        self.assertEqual(len(groups["齿轮箱"]), 2)

    def test_same_file_under_two_model_folders_is_deduped(self) -> None:
        groups = ai_fill._all_component_cert_groups(
            [
                _material(GEARBOX_A, GEARBOX_DIR, "RAW-1"),
                _material(GEARBOX_A, "技术标/标准文件/EW10.0-220下置/认证证书/部件认证/齿轮箱", "RAW-2"),
            ]
        )

        self.assertEqual(len(groups["齿轮箱"]), 1)
