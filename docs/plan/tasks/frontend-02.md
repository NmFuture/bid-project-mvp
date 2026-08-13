---
id: frontend-02
scope: 前后端 / 项目信息表单
status: pending
depends-on: []
---

# frontend-02：项目信息选项接真实数据源

## objective

把「完善项目信息」表单的选项来源从硬编码静态占位改为真实数据源。

> **前置决策（未拍板不动工）**：真实数据源是什么？候选：素材库客户目录、手工维护的选项表、或从历史项目聚合。见总 plan §5 决策点。

## context

- `docs/anbc_doc/架构总览/modules/fe_shared_project_info.md`（「当前静态回源」记录处）
- 总 plan：`docs/plan/analysis/20260812-系统性重构.md`

## path

- `code/sewpg-bid-backend/app/services/project_info_options.py`（:7-81 硬编码 `CUSTOMER_OPTIONS`/`TURBINE_MODEL_OPTIONS`、:88 `source: "{source}-static-placeholder"`）
- `code/sewpg-bid-backend/app/api/routes/project_info.py`（:18-20）
- `code/sewpg-bid-frontend/src/api/index.js`（:463-469 双轨 options 封装）与 `workspaces/shared` 的表单逻辑

## 现状（2026-08-12 复核证据）

- 选项是硬编码列表，返回值带 `*-static-placeholder` 标记，未接任何真实数据源；前端双轨照常消费。

## 改造方案

1. 拍板数据源后：后端选项服务改为从真实来源读取（加缓存或随请求查），`source` 标记改为真实来源名。
2. 保留静态列表作为来源不可用时的兜底（标注 fallback），不静默失败。
3. 前端无需改接口形状（保持 options 响应契约），只在来源为空时给空态展示。

## verification

- 后端测试覆盖 options 端点的真实来源与兜底两条路径；前端表单选项随数据源变化。
