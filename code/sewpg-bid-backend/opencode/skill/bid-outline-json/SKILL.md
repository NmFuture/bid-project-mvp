---
name: bid-outline-json
description: Generate editable S2 outline JSON from tender content and bid template hints for the bidding MVP.
---

# Bid Outline JSON

Use this skill when the task is to generate the directory JSON for `S2`.

## Goal

Turn:
- 招标文本线索
- 投标模板章节线索

into:
- 前端 `S3` 可直接编辑的目录 JSON

## Output Rules

1. Return JSON only.
2. Do not use Markdown code fences.
3. The JSON shape must be:

```json
{
  "summary": "一句简短总结",
  "nodes": [
    {
      "id": "OL-1",
      "title": "一级标题",
      "children": [
        {
          "id": "OL-1-1",
          "title": "二级标题",
          "children": []
        }
      ]
    }
  ]
}
```

## Content Rules

1. First use the bid template directory as the base skeleton.
2. Then compare against the tender requirements and rename, delete, or add sections as needed.
3. Do not omit tender-mandated sections.
4. Keep titles concise and suitable for Chinese technical bidding documents.
5. Use at most 3 levels.
6. Do not invent factual content such as company cases, parameter values, certificates, dates, or amounts.
7. At least 3 top-level nodes.
