---
name: bid-business-wiki-material-builder
description: Use when rebuilding the business-bid material Wiki from raw material inventory for gap handling, table filling, or bid assembly
allowed-tools: [Read, Glob, Grep, Bash, Write, AskUserQuestion]
---

# Business Bid Material Wiki Builder

## Overview

Build the smallest useful business-bid Wiki that lets later agents understand which business materials exist, where they can be used, which forms or facts must be filled per project, and which source document proves each claim. Treat the Wiki as an AI-facing retrieval and compliance index, not as a prose knowledge base.

## When to Use

Use for business-bid Wiki creation or rebuilds after raw materials change. Use when downstream tasks include gap handling, filling generated blank forms, selecting qualification/authorization/quotation sources, or assembling the business proposal.

Do not use for technical-bid-only materials, technical方案 writing, or inventing missing commercial facts.

## Output Contract

Output JSON only. Do not wrap it in Markdown fences. Use this schema:

```json
{
  "summary": "short result summary",
  "rootTitle": "商务标Wiki（自动生成）",
  "nodes": [
    {
      "title": "node title",
      "markdownContent": "# node title\n\ncontent",
      "tags": ["商务标"],
      "applicableTypes": ["商务标"],
      "children": []
    }
  ]
}
```

The root must contain exactly these five first-level work nodes, in this order:

1. `01-素材总表`
2. `02-章节映射表`
3. `03-素材卡片`
4. `04-待填写清单`
5. `05-使用规则`

Extra nested children are allowed only under these five nodes. Avoid old large structures such as separate skeleton/rules/synonyms/card/log root folders.

## Core Pattern

Generate from `materialInventory.items`. The backend has already read each available Word file enough to provide headings, paragraph excerpts, table previews, cleaned Word status, identity fields, and source paths.

For every real business-bid material:

- Include it once in `01-素材总表`.
- Create or reference one card under `03-素材卡片`.
- Preserve the source path and cleaned Word file name.
- Preserve AI identity fields so later agents can filter general, customer, and project materials correctly.
- Assign a recommended business chapter or mark `未明确`.

If there are no business-bid materials, output the five nodes as a待补料 framework and explicitly say no real business cards were found.

## Node Responsibilities

### 01-素材总表

Create a compact table for scanning. Include file name, source tier, identity, original path, cleaned Word status, detected headings/tables, business material type, recommended chapter, and usage hint.

### 02-章节映射表

Map business sections to candidate material cards. Cover投标函、授权委托、资质证书、业绩证明、保证金、商务偏差、合同条款响应、报价与分项表 when materials exist. Include confidence and reason.

### 03-素材卡片

Create demand-load cards grouped by `通用素材`, `客户素材`, and `项目素材`, then by business topic. A card is an index record, not the full document. Each card must include:

- source path and material id
- content summary from headings/excerpts/tables
- suitable sections and partial-use notes
- AI identity fields: `identity_scope`, `material_scope`, `bid_type`, `customer_id`, `customer_name`, `customer_aliases`, `project_id`, `project_code`
- merge fields: `path`, `cleaned_file_name`, `skeleton_section`, `attach_mode`, `shift`

### 04-待填写清单

List project-specific blanks that must be resolved during gap handling before assembly. Include报价、保证金、投标有效期、授权代表、项目名称、客户名称、合同条款响应值 and generated blank forms.

Do not fill values in this Wiki. Mark the expected source document or source card that the S3 page should ask the user or agent to choose.

### 05-使用规则

State how downstream agents should use the Wiki:

- Load `01-素材总表` first.
- Load matching rows in `02-章节映射表`.
- Load only necessary cards from `03-素材卡片`.
- Resolve all `04-待填写清单` items before assembly.
- Prefer project material over customer material over general material when identity matches.
- Keep commercial facts conservative; cite or leave待填写 rather than invent.
- Never use customer or project material when identity fields do not match.

## Quality Rules

- Do not invent报价、金额、证书编号、授权人、日期、业绩事实, or contract commitments.
- Keep the Wiki minimal; add a node only when it helps retrieval, gap handling, filling, or assembly.
- If a file has no headings, still create a card and mark the heading risk.
- If a file is too large or could not be parsed, create a card from metadata and mark `needs_review`.
