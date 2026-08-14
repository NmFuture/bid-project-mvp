"""parsing-01 门面守卫：app.services.parsing 必须持续 re-export 这些符号。

外部调用方与既有测试一律经门面取符号或打 patch；拆分内部模块后，
本测试保证 `app.services.parsing.<符号>` 命名空间保持可解析、可 patch。
"""

import app.services.parsing as parsing

# parsing-01 硬约束清单：facade 必须保留的 re-export/中转符号。
FACADE_SYMBOLS = (
    "_ocr_fallback_text",
    "_project_basics_project_prefill",
    "_S1_SHARD_REQUEST_SLOTS",
    "_ShardProgressAggregator",
    "_technical_total_item_count",
    "_technical_submitted_item_count",
    "IMAGE_SUFFIXES",
    "OpencodeEngine",
    "DoclingParseEngine",
    "AgentEngineFactory",
    "AgentOrchestrator",
    "system_settings_service",
    "ocr_service",
    "settings",
    "subprocess",
    "write_business_section_tree",
    "run_business_template_extractor",
)

# 外部模块与既有测试经门面访问的其余符号（按来源模块分组）。
FACADE_SYMBOLS_EXTRA = (
    # parse_common / parse_extract
    "_run_with_progress_heartbeat",
    "extract_docx_text",
    "extract_pdf_text",
    "nav_to_text",
    # parse_business_fields
    "_normalize_bid_deadline",
    "_transform_to_business_contract",
    # parse_appendix
    "_build_appendix_slice_state",
    "_extract_document_nav_appendices",
    "_extract_docx_appendices",
    "_extract_markdown_appendices",
    "_extract_text_appendices",
    "_extract_text_business_appendices",
    "_prepare_appendix_outputs",
    "_prepare_commitment_letter_outputs",
    "_slice_appendix_from_source",
    "_write_appendix_docx",
    "materialize_appendix_docx",
    "materialize_business_commitment_letter_docx",
    "materialize_parse_appendix_docx_assets",
    "materialize_parse_business_commitment_letter_docx_assets",
    # parse_s1_skill
    "_build_tender_parse_prompt",
    "_finalize_business_s1_result",
    "_needs_business_s1_finalize_guard",
    "_project_basics_bid_deadline",
    "_run_parse_skill",
    "_run_s1parse_cli",
    "_run_technical_sharded_parse_skill",
    # 门面自有
    "parse_tender_documents",
    "BUSINESS_PARSE_PROFILE",
    "TECHNICAL_PARSE_PROFILE",
    "ParseCancelledError",
    "TEXT_PREVIEW_LIMIT",
)


def test_facade_hard_constraint_symbols_resolvable() -> None:
    missing = [name for name in FACADE_SYMBOLS if not hasattr(parsing, name)]
    assert not missing, f"parsing 门面缺少硬约束 re-export 符号：{missing}"


def test_facade_extra_symbols_resolvable() -> None:
    missing = [name for name in FACADE_SYMBOLS_EXTRA if not hasattr(parsing, name)]
    assert not missing, f"parsing 门面缺少外部调用方/测试经门面访问的符号：{missing}"
