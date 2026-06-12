---
name: bid-tech-wiki-material-builder
description: Use when rebuilding the technical-bid material Wiki from raw material inventory for gap handling, table filling, or bid assembly
allowed-tools: [Read, Glob, Grep, Bash, Write, AskUserQuestion]
---

# Technical Bid Material Wiki Builder

## Overview

Build the smallest useful technical-bid Wiki that lets later agents understand what the material library contains, where each material can be used, what must be filled per project, and which source document proves the content. Treat the Wiki as an AI-facing retrieval and assembly index, not as a prose knowledge base or a duplicate file browser.

## When to Use

Use for technical-bid Wiki creation or rebuilds after raw materials change. Use when downstream tasks include S3 gap handling, selecting sources for generated blank tables, or assembling the technical proposal.

Do not use for business-bid-only materials, general document summarization, or inventing missing project facts.

## Output Contract

Output JSON only. Do not wrap it in Markdown fences. Use this schema:

```json
{
  "summary": "short result summary",
  "rootTitle": "技术标Wiki（自动生成）",
  "nodes": [
    {
      "title": "node title",
      "markdownContent": "# node title\n\ncontent",
      "tags": ["技术标"],
      "applicableTypes": ["技术标"],
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

For every real technical-bid material:

- Include it once in `01-素材总表`.
- Create or reference one card under `03-素材卡片`.
- Preserve the source path and cleaned Word file name.
- Preserve AI identity fields so later agents can filter general, customer, and project materials correctly.
- Assign a recommended chapter or mark `未明确`.

## Node Responsibilities

### 01-素材总表

Create a compact table for scanning. Include file name, source tier, identity, original path, cleaned Word status, detected headings/tables, recommended chapter, and usage hint.

### 02-章节映射表

Map tender/proposal chapter needs to candidate material cards. Use chapter names rather than a rigid universal template when the inventory is messy. Include confidence and reason. If a material may be used only as a paragraph or table source, say so explicitly.

### 03-素材卡片

Create demand-load cards grouped by `通用素材`, `客户素材`, and `项目素材`, then by topic. A card is an index record, not the full document. Each card must include:

- source path and material id
- content summary from headings/excerpts/tables
- suitable chapters and partial-use notes
- AI identity fields: `identity_scope`, `material_scope`, `bid_type`, `customer_id`, `customer_name`, `customer_aliases`, `project_id`, `project_code`
- merge fields: `path`, `cleaned_file_name`, `skeleton_section`, `attach_mode`, `shift`

### 04-待填写清单

List project-specific blanks that must be resolved during S3 gap handling before assembly. Include generated blank tables, parameter tables, guarantee values, project name/client/site/model/capacity placeholders, and any material card whose content is only a source for filling a smaller section.

Do not fill values in this Wiki. Mark the expected source document or source card that the S3 page should ask the user or agent to choose.

### 05-使用规则

State how downstream agents should use the Wiki:

- Load `01-素材总表` first.
- Load matching rows in `02-章节映射表`.
- Load only necessary cards from `03-素材卡片`.
- Resolve all `04-待填写清单` items before assembly.
- Prefer project material over customer material over general material when identity matches.
- Use `override`, `append`, `reference`, and `exclude` conservatively.
- Never use customer or project material when identity fields do not match.

## Quality Rules

- Do not invent facts, file names, project parameters, certificate numbers, dates, or performance values.
- Keep the Wiki minimal; add a node only when it helps retrieval, gap handling, filling, or assembly.
- If a file has no headings, still create a card and mark the heading risk.
- If a file is too large or could not be parsed, create a card from metadata and mark `needs_review`.
