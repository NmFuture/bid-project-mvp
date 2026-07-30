"""跨机型复用标签匹配测试（R06-B06-02）。

带「通用」标签的素材可被任意具体机型标签命中；精确机型标签行为不变。
"""

from __future__ import annotations

from app.services.technical_material_store import TechnicalMaterialStore


class TestGenericModelTagHit:
    def test_generic_tag_hit_by_specific_model(self) -> None:
        item = {"tags": ["通用", "认证证书"]}
        assert TechnicalMaterialStore._item_matches_tags(item, ["EW6.7-202"]) is True

    def test_generic_tag_hit_by_multiple_models(self) -> None:
        item = {"tags": ["通用", "认证证书"]}
        for model in ("EW6.7-202", "EW10.0-220", "SE5.0-182"):
            assert TechnicalMaterialStore._item_matches_tags(item, [model]) is True

    def test_generic_tag_combined_with_category_tag(self) -> None:
        item = {"tags": ["通用", "认证证书"]}
        assert TechnicalMaterialStore._item_matches_tags(item, ["EW6.7-202", "认证证书"]) is True
        assert TechnicalMaterialStore._item_matches_tags(item, ["EW6.7-202", "部件"]) is False


class TestExactModelTagUnchanged:
    def test_exact_model_tag_still_hits(self) -> None:
        item = {"tags": ["EW6.7-202", "部件"]}
        assert TechnicalMaterialStore._item_matches_tags(item, ["EW6.7-202"]) is True

    def test_other_model_tag_still_misses(self) -> None:
        item = {"tags": ["EW6.7-202", "部件"]}
        assert TechnicalMaterialStore._item_matches_tags(item, ["EW10.0-220"]) is False

    def test_non_model_requested_tag_not_affected(self) -> None:
        # 非机型标签不走通用命中：只带「通用」的素材不应命中「部件」筛选
        item = {"tags": ["通用"]}
        assert TechnicalMaterialStore._item_matches_tags(item, ["部件"]) is False

    def test_generic_requested_tag_matches_by_substring(self) -> None:
        item = {"tags": ["通用", "认证证书"]}
        assert TechnicalMaterialStore._item_matches_tags(item, ["通用"]) is True
