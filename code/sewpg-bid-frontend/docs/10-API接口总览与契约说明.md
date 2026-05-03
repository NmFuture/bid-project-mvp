# 前端 API 接口总览

> 更新时间：2026-05-03
> 适用范围：`sewpg-bid-frontend` 通过 `/api` 调用正式 FastAPI。

本文件只保留前端侧阅读入口，详细接口契约以仓库根目录的正式文档为准：

- `/Users/wlb/Agent/bid-project/doc/06-MVP接口文档.md`
- `/Users/wlb/Agent/bid-project/code/sewpg-bid-api/MVP接口与参数核心版_极简版.md`

## 当前阶段口径

当前技术标流程统一为：

```text
S0 解析
  -> S1 模板与目录
  -> S2 审核目录
  -> S3 缺口处理
  -> S4 生成标书
  -> S5 共创
  -> S6 导出
```

- `S0` 是全局解析/审核模块，不出现在项目阶段条中。
- 项目阶段条只展示 `S1-S6`。
- `fill-generation`、`coverage`、`review-items` 等接口名保留历史兼容，但用户阶段和页面语义按 `S0-S6` 理解。
- 旧 `S7/S8/S9/S10` 只允许出现在历史内部目录名、兼容接口名或归档资料里。

## 前端调用约定

- 前端统一通过 `src/api/index.js` 调用 `/api`。
- 前端不直接调用 `opencode`。
- 前端不直接处理 OnlyOffice callback。
- FastAPI 是唯一正式业务后端。

## 当前重点接口域

| 域 | 前端封装 | 正式说明 |
|---|---|---|
| 认证 | `authAPI` | 登录、会话恢复、退出 |
| 项目与阶段 | `projectsAPI`、`stagesAPI` | 项目列表、详情、`S1-S6` 阶段条 |
| S0 解析 | `parseAPI` | 多招标文件上传、解析、投标决策 |
| S1/S2 目录 | `directoryAPI`、`outlineAPI` | 模板读取、目录生成、目录审核 |
| S3 缺口处理 | `gapsAPI`、`reviewItemsAPI` | 缺口计划、补料、选择素材、AI 填写、确认 |
| S4 生成标书 | `fillGenerationAPI`、`coverageAPI` | 正文拼装与覆盖诊断 |
| S5/S6 文档 | `documentAPI`、`exportAPI` | OnlyOffice 共创、最终下载、导出前检查 |
| 素材库 | `materialsAPI` | 技术标原始素材、技术标 Wiki、商务标空状态 |
| 设置/审计 | `settingsAPI`、`auditAPI` | 用户、模板、模型配置、审计日志 |

## 素材库口径

素材库是一级准备模块，和 `解析 / 技术标 / 商务标 / 审计 / 设置` 同级。

当前页面口径：

- 顶层：`技术标 / 商务标`
- 技术标：`原始素材 / Wiki`
- 技术标原始素材：`通用素材 / 客户素材 / 项目素材`
- 技术标 Wiki：`01-素材总表 / 02-章节映射表 / 03-素材卡片 / 04-待填写清单 / 05-使用规则`
- 商务标：原始素材和 Wiki 先保留为空

后续如果本文件和根目录正式接口文档冲突，以 `/Users/wlb/Agent/bid-project/doc/06-MVP接口文档.md` 为准。
