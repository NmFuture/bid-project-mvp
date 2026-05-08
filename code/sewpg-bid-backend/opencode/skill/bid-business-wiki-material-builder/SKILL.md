---
name: bid-business-wiki-material-builder
description: Use when rebuilding the business-bid material Wiki from raw material inventory for gap handling, table filling, evidence selection, or bid assembly
allowed-tools: [Read, Glob, Grep, Bash, Write, AskUserQuestion]
---

# Business Bid Material Wiki Builder

## Overview

Build the smallest useful business-bid Wiki that lets later agents understand:

- which business materials exist
- which template modules they can support
- whether a material should be attached whole, used as image evidence, or only used to fill fields/tables
- which variables still need human confirmation
- which evidence has validity or version risk

Treat the Wiki as an AI-facing retrieval and compliance index, not as a prose knowledge base.

## When to Use

Use for business-bid Wiki creation or rebuild after raw materials change.

Typical downstream scenarios:

- S3 gap handling
- choosing evidence for qualification and performance attachments
- filling quotation/specification/deviation tables
- assembling the business proposal package

Do not use for technical-bid-only materials, technical scheme writing, or inventing missing commercial facts.

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
2. `02-模板模块映射表`
3. `03-证据卡片`
4. `04-待填写与待确认清单`
5. `05-使用规则`

Extra nested children are allowed only under these five nodes.

## Core Pattern

Generate from `materialInventory.items`.

For every real business material:

- include it once in `01-素材总表`
- create or reference one evidence card under `03-证据卡片`
- preserve source path and cleaned file name if it exists
- preserve AI identity fields so later agents can correctly filter general, customer, and project materials
- give it a recommended business category and module usage mode

If there are no business materials, still output the same five nodes as a待补料 framework.

## Node Responsibilities

### 01-素材总表

Create a compact table for scanning.

Must include:

- file name
- source tier
- identity scope
- business category
- recommended module
- cleaning strategy
- evidence type
- original path

### 02-模板模块映射表

This node answers:

- for a given business template module, which path ranges should be searched first
- which evidence cards are the current best candidates
- whether the material is for whole attachment, field extraction, image extraction, table filling, or reference only

Use the confirmed business modules, such as:

- 投标函与授权
- 投标价格表
- 货物规格一览表
- 商务偏差表
- 投标保证金
- 履约保证承诺
- 附件7资格证明
- 附件7I业绩情况表
- 开标价格表
- 附件9其他说明与承诺
- 否决项与符合性响应

Each row should carry fields equivalent to:

- `module_name`
- `module_code`
- `source_path_prefix`
- `business_category`
- `candidate_card_ids`
- `usage_mode`
- `mapping_source`
- `confidence`
- `needs_human_confirm`
- `mapping_reason`
- `fallback_scope`
- `missing_hint`

### 03-证据卡片

Create demand-load evidence cards grouped to mirror the raw library as much as possible:

- `通用素材`
- `客户素材/{客户名称}`
- `项目素材/{项目代号}`

Then group by the second-level business folder.

A card is an index record, not the full document.

Each card should cover these field groups:

- basic identity and path fields
- AI identity fields
- module decision fields
- content summary and keywords
- validity fields such as issue date and expiry date when detectable
- risk fields such as OCR uncertainty, version uncertainty, and human confirmation need

Image certificates or scanned evidence should remain original-first. Do not force them into cleaned Word usage semantics.

### 04-待填写与待确认清单

List project-time blanks or decisions that must be resolved before final assembly.

Include high-frequency business items such as:

- project name / project code / customer name
- authorized representative
- bid price
- opening price
- bid security amount
- validity period
- evidence package selection
- certificate validity check
- deviation/compliance confirmation
- attachment page index check

Do not fill values inside the Wiki. Only point to candidate sources and mark blocking level.

### 05-使用规则

State how downstream agents should use the business Wiki:

- filter by identity first
- read the module mapping table before full search
- use project material over customer material over general material
- for `fill_table` modules, extract fields instead of attaching the whole source
- for images/scans, keep originals and require human verification when needed
- if mapping misses existing materials, fall back to scoped search inside the current readable identity range
- never invent prices, dates, commitments, certificate numbers, or performance facts

## Quality Rules

- Do not invent报价、金额、证书编号、授权人、日期、业绩事实, or contract commitments.
- Keep the Wiki minimal and retrieval-oriented.
- If a file has no headings, still create a card and mark the risk.
- If a certificate or screenshot has unclear validity information, mark it `pending_verify`.
- If the mapping table is incomplete, rely on `fallback_scope` plus scoped full search, not on fabrication.
