---
id: frontend-01
scope: 前端 / 技术标缺口页
status: done
depends-on: []
---

# frontend-01：缺口页逐条质量警示接线

## objective

把 AI 填写质量信号（qualityReport / qualityStatus）接到缺口页逐条 UI 上，堵「点了白点还不知道」的体验黑洞；同时处置死代码 `resultSummaryForItem`（复用或删除）。

## context

- `docs/archive/20260715-old-docs/20260708-技术标附表AI填写全链路梳理.md` §四.3、§七.2（问题原始记录与「前端接回质量警示」建议）
- `docs/anbc_doc/架构总览/modules/fe_page_gap_recognition.md`（2026-08-12 复核结论）
- 总 plan：`docs/plan/analysis/20260812-系统性重构.md` §5 决策点（展示形态可实施时微调）

## path

- `code/sewpg-bid-frontend/src/workspaces/technical/pages/TechnicalGapRecognition.jsx`（3565 行）
- `code/sewpg-bid-frontend/src/workspaces/technical/pages/technicalGapRecognitionHelpers.js`（:721 `resultSummaryForItem`、:313 qualityStatus 分类）
- 后端质量字段来源：`technical_gap_ai_fill.py` 等产出的 qualityReport

## 现状（2026-08-12 复核证据）

- `resultSummaryForItem`（helpers.js:721）仍零引用，是死代码。
- 已部分改善：`:2243-2247` 用 `qualityReport.unfilledPlaceholderCount`/`reviewNotes` 统计黄标，批量复核按钮 title 展示「其中 N 条仍有未填字段」（:2929-2930）；`qualityStatus === 'human_confirmed'` 驱动标签分类（helpers.js:313）。
- 仍缺：缺口列表/详情区无逐条质量警示；`needs_review` 文案映射只在 `TechnicalTenderReview.jsx:178`，缺口页无感知；0 字段空转（targetFieldCount=0 仍标 resolved）在后端侧的记录见复盘 §七.2，若仍存在应一并修。

## 改造方案

1. 逐条警示：列表项/详情区对有 `unfilledPlaceholderCount>0` 或 `qualityStatus=needs_review` 的缺口加徽标/警示条，文案复用复盘口径（验收通过/待复核）。
2. `resultSummaryForItem`：若展示逻辑能复用则接线，否则删除——不允许继续躺尸。
3. 顺手核对后端「0 字段空转仍标 resolved」是否已修；未修则在本任务一并加门禁（targetFieldCount=0 不标 resolved）。

## verification

- `npm run build` 通过；造一条含未填字段的 AI 填写产物，缺口页逐条警示可见；批量复核提示与逐条徽标口径一致。
