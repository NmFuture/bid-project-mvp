---
id: deadcode-03
scope: 前端 / API 封装层
status: ready
depends-on: []
---

# deadcode-03：删除前端零调用 API 封装

## objective

删除 `src/api/index.js` 中确认零调用的封装函数，消除「封装在、按钮不在」的假接缝。

## context

- `docs/anbc_doc/架构总览/04-技术标操作串讲.md` §7（2026-08-12 复核结论）
- 总 plan：`docs/plan/analysis/20260812-系统性重构.md`

## path

- `code/sewpg-bid-frontend/src/api/index.js`
- 同步更新 `04-技术标操作串讲.md` §7

## 现状（2026-08-12 复核证据，行号为复核时值，动手前重新定位）

零调用封装（全 `src/` 无 import/调用点）：

- `submitReview`（index.js:556）、`recheck`（index.js:575）
- `tagImportPreview` / `tagImportCommit`（index.js:702-705）
- `wiki.create/update/delete`（index.js:736-741）——Wiki 页只读，只调 list/bootstrap
- `technicalDocumentAPI.forceSave`（index.js:615）

注意：`resultSummaryForItem` 不在本任务范围（归 frontend-01 处置）；`certificateTime` 系列（index.js:742-744）调用情况未核实，动手时先 grep 再定。

## 改造方案

1. 对上面每个符号逐个 `grep -r` 全 `src/`（含商务轨同名封装），确认零调用才删。
2. 只删封装函数本体，不动后端端点（后端侧归 deadcode-04）。
3. 更新 `04-技术标操作串讲.md` §7：从「未接线」清单移除已删项，避免文档继续误导。

## verification

- `npm run build` 通过。
- grep 已删符号零命中。
