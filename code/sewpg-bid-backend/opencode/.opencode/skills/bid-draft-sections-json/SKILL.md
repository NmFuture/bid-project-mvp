---
name: bid-draft-sections-json
description: Generate editable S7 draft section JSON from confirmed outline and tender content for the bidding MVP.
---

# Bid Draft Sections JSON

Use this skill when the task is to generate the section JSON for `S7`.

## Goal

Turn:
- 已确认目录
- 招标文本摘要
- 投标模板章节线索

into:
- 前端 `S7` 和 `S9` 可继续使用的初稿章节 JSON

## Output Rules

1. Return JSON only.
2. Do not use Markdown code fences.
3. The JSON shape must be:

```json
{
  "summary": "一句简短总结",
  "sections": [
    {
      "nodeId": "OL-1",
      "title": "章节标题",
      "generationMode": "generated",
      "content": "章节正文，允许使用 Markdown 标题和段落",
      "riskFlags": []
    }
  ]
}
```

## Content Rules

1. Keep the confirmed outline unchanged. One top-level outline node maps to one section.
2. Use the bid template as writing style reference, but do not change the outline structure.
3. Generate general narrative content directly when it is safe.
4. For verifiable facts such as company cases, parameter values, certificates, dates, amounts, or staffing counts, do not invent data.
5. When facts are missing, use explicit placeholders like `【待补充：关键参数实测值】`.
6. `generationMode` must be one of:
   - `generated`
   - `placeholder`
   - `generated_with_placeholder`
7. If placeholders remain, include `FACT_REQUIRED` in `riskFlags`.
