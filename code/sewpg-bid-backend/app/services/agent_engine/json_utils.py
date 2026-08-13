"""JSON 修复/解析公共能力（改造方案 §5，引擎无关，三引擎复用）。

函数体自 `app/services/opencode_client.py`（现 `opencode_engine.py`）纯移动，未改逻辑。
`_repair_json_payload` 需发起一次模型会话修复 JSON，与引擎耦合：第一个参数 `self`
即引擎实例（`OpencodeEngine` 以类属性引用本函数，保持原访问形态）。
"""
from __future__ import annotations

import json
import re
from typing import Any


def _parse_json_payload(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
        cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        last_error: json.JSONDecodeError | None = None
        candidates = _balanced_json_object_candidates(cleaned)
        if cleaned.startswith("{"):
            candidates = [candidate for start, candidate in candidates if start == 0]
        else:
            candidates = [candidate for _start, candidate in candidates]
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError as exc:
                last_error = exc
                continue
            if isinstance(parsed, dict):
                return parsed
        if "{" not in cleaned or "}" not in cleaned:
            raise RuntimeError("futurecode 返回内容里没有可解析的 JSON。")
        if last_error is not None:
            raise RuntimeError("futurecode 返回的 JSON 无法解析。") from last_error
        raise RuntimeError("futurecode 返回内容里没有完整的 JSON 对象。")


def _balanced_json_object_candidates(text: str) -> list[tuple[int, str]]:
    candidates: list[tuple[int, str]] = []
    for start, char in enumerate(text):
        if char != "{":
            continue
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            current = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    in_string = False
                continue
            if current == '"':
                in_string = True
            elif current == "{":
                depth += 1
            elif current == "}":
                depth -= 1
                if depth == 0:
                    candidates.append((start, text[start : index + 1]))
                    break
    return candidates


async def _repair_json_payload(self, raw_content: str, repair_kind: str) -> str:
    if repair_kind == "outline":
        schema_hint = (
            '{"schema_version":"bid-toc-json-v1","summary":{"total_items":1,'
            '"annotation_counts":{"保留":1,"适配":0,"新增-招标要求":0,"新增-素材库建议":0,'
            '"删除建议":0,"素材内置标题":0}},"items":[{"order":1,"number":"第一章",'
            '"title":"一级标题","level":1,"annotation":"保留","source":"template","reason":""}],'
            '"outputFile":"/data/documents/PRJ-0001/technical-workspace/s2_toc_workdir/投标文件-总目录.json"}'
        )
    elif repair_kind == "wiki":
        schema_hint = (
            '{"summary":"一句简短总结","rootTitle":"技术标Wiki（自动生成）",'
            '"nodes":[{"title":"节点标题","markdownContent":"# 节点标题\\n\\n正文",'
            '"tags":["技术标","素材库"],"applicableTypes":["技术标"],"children":[]}]}'
        )
    elif repair_kind == "assembly":
        schema_hint = (
            '{"schema_version":"bid-tech-assembly-v1","outputFile":'
            '"/data/documents/PRJ-0001/technical-workspace/s7_assembly_workdir/投标文件-正文.docx",'
            '"assemblyReport":"","needsReview":"",'
            '"planFile":"/data/documents/PRJ-0001/technical-workspace/s7_assembly_workdir/assembly_plan.json",'
            '"summary":{"total":1,"byStatus":{"MATCHED":1},"usedPathCount":1,"warningCount":0},'
            '"warnings":[]}'
        )
    elif repair_kind == "gap_plan":
        schema_hint = (
            '{"schema_version":"bid-tech-gap-plan-v1","outputFile":'
            '"/data/documents/PRJ-0001/technical-workspace/s4_gap_workdir/gap_plan.json",'
            '"summary":{"totalTocItems":1,"matchedCount":0,"missingCount":1,'
            '"resolvedCount":0,"ignoredCount":0,"structuralCount":0,'
            '"fillableTaskCount":1,"blockingCount":1},"itemCount":1}'
        )
    elif repair_kind == "tender_parse":
        schema_hint = (
            '{"schemaVersion":"bid-tender-structured-v1","outputFile":'
            '"/data/parsed/PRJ-0001/s1_structured_result.json",'
            '"items":[{"id":"REQ-0001","type":"项目基础信息","category":"project_basics",'
            '"title":"项目名称","keyEntity":"项目名称","keyValue":"示例项目",'
            '"sourceFile":"招标文件.docx","evidence":"项目名称：示例项目","evidenceLocation":"L1"}],'
            '"structured":{"projectDates":{"startDate":"2026-01-01","endDate":"2026-02-01"},'
            '"categories":[{"key":"project_basics","label":"项目基础信息","count":1,"items":[]}]}}'
        )
    elif repair_kind == "business_commitment_review":
        schema_hint = (
            '{"decisions":[{"id":"RAW-0001","action":"generate",'
            '"topicKey":"confidentiality","preferredTitle":"保密承诺书",'
            '"reason":"明确要求投标人单独提供保密承诺书。"}]}'
        )
    elif repair_kind == "business_template_review":
        schema_hint = (
            '{"decisions":[{"id":"APPX-0001","action":"accept|review|reject",'
            '"templateType":"bid_letter","quality":"complete|probably_incomplete|title_only",'
            '"reason":"一句简短原因"}]}'
        )
    elif repair_kind == "table_fill":
        schema_hint = (
            '{"schema_version":"bid-tech-table-fill-v1","outputFile":'
            '"/data/documents/PRJ-0001/technical-workspace/s4_gap_workdir/ai_fill/GAP-0001/AI填写.docx",'
            '"unfilledFields":[],"evidenceRefs":[{"type":"material","id":"RAW-0001"}]}'
        )
    elif repair_kind == "fact_curate":
        schema_hint = (
            '{"schema":"bid-tech-fact-curate-v1","suggestionsPath":'
            '"/data/documents/PRJ-0001/technical-workspace/s4_gap_workdir/fact_curate/fact_curate_suggestions.json",'
            '"counts":{"fill":1,"fix":0,"confirmAdvice":0}}'
        )
    elif repair_kind == "business_format":
        schema_hint = (
            '{"schema_version":"bid-business-format-clean-v1","inputFile":'
            '"/data/documents/PRJ-0001/business-workspace/s4_assembly_workdir/商务投标文件.docx",'
            '"outlineFile":"/data/documents/PRJ-0001/business-workspace/s4_assembly_workdir/business_format_outline.json",'
            '"outputFile":"/data/documents/PRJ-0001/business-workspace/s4_assembly_workdir/商务投标文件.formatted.docx",'
            '"reportFile":"/data/documents/PRJ-0001/business-workspace/s4_assembly_workdir/business_format_clean_report.md",'
            '"summary":{"outlineCount":1,"matchedHeadingCount":1,"unmatchedHeadingCount":0,'
            '"tocInserted":true,"tocPresent":true,"headerCleaned":true,"riskCount":0}}'
        )
    else:
        schema_hint = (
            '{"summary":"一句简短总结","sections":[{"nodeId":"OL-1","title":"章节标题",'
            '"generationMode":"generated","content":"正文","riskFlags":[]}]}'
        )
    repair_prompt = f"""
请把下面内容整理成严格 JSON。

要求：
1. 只输出 JSON，不要解释，不要 Markdown 代码块。
2. 保留原始语义，不要新增事实。
3. 输出结构必须满足这个模式：
{schema_hint}

原始内容：
{raw_content}
""".strip()
    session = await self.create_session("JSON repair")
    session_id = str(session.get("id") or "")
    try:
        response = await self.send_prompt(session_id, repair_prompt)
        text_parts = [
            str(part.get("text") or "")
            for part in response.get("parts") or []
            if part.get("type") == "text"
        ]
        content = "\n".join(part for part in text_parts if part).strip()
        if not content:
            raise RuntimeError("futurecode 返回的 JSON 无法解析。")
        return content
    finally:
        # B3：修复会话一次性使用，终态即回收（失败只告警）。
        await self.delete_session_quietly(session_id)
