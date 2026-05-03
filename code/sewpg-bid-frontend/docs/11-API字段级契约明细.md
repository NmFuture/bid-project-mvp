# 前端 API 字段依赖索引

> 更新时间：2026-05-03
> 适用范围：前端页面字段依赖梳理。

详细字段契约以正式接口文档为准：

- `/Users/wlb/Agent/bid-project/doc/06-MVP接口文档.md`
- `/Users/wlb/Agent/bid-project/code/sewpg-bid-api/MVP接口与参数核心版_极简版.md`

本文件只记录前端最容易依赖错的关键字段，避免继续沿用旧 `S1-S10` 字段口径。

## 全局约定

- 前端调用基址：`/api`
- 开发代理目标：`VITE_API_PROXY_TARGET`
- 当前项目阶段：`1-6`
- `S0` 不进入项目阶段条
- `S5` 是 OnlyOffice 共创
- `S6` 是最终导出

## Project

| 字段 | 说明 |
|---|---|
| `id` | 项目 ID |
| `name` | 项目名称 |
| `customerName` | 客户名称 |
| `manager` | 负责人 |
| `bidType` | 当前标类，当前主要使用 `技术标` |
| `currentStage` | 项目内阶段，范围 `1-6` |
| `stageLabel` | 当前阶段名称 |
| `files` | 招标文件展示摘要 |
| `templateFiles` | 项目真实上传模板展示摘要 |

## Stage

| 字段 | 说明 |
|---|---|
| `id` | 阶段 ID，范围 `1-6` |
| `name` | 阶段名称：模板与目录、审核目录、缺口处理、生成标书、共创、导出 |
| `status` | `completed / active / pending` |
| `isHuman` | 是否人工阶段 |
| `routeStageId` | 前端路由阶段 ID，兼容旧数据时优先使用 |

## GapPlan

| 字段 | 说明 |
|---|---|
| `tocItemId` | 对应目录项 |
| `status` | `matched / missing / needs_input / filling / resolved / ignored` |
| `matchedMaterials` | 已匹配素材、Wiki 卡片、匹配理由 |
| `requiredInputs` | 需要补齐的项目字段、空表或人工资料 |
| `fillTasks` | AI 填写任务 |
| `resolvedArtifacts` | 人工上传、选择素材或 AI 填写后的项目级产物 |

## DocumentWorkspace

| 字段 | 说明 |
|---|---|
| `documentId` | 文档 ID |
| `fileName` | 当前 Word 文件名 |
| `fileUrl` | 浏览器可访问下载地址 |
| `version` | 文档版本 |
| `onlyoffice` | OnlyOffice 挂载配置 |
| `fallback` | OnlyOffice 不可用时的文本兜底内容 |

## Materials

项目内素材搜索范围来自：

```http
GET /api/projects/{project_id}/materials-path
```

默认读取：

```text
技术标/通用素材
技术标/客户素材/{客户}
技术标/项目素材/{素材项目ID}
```

技术标 Wiki 由后端生成，一级结构固定为：

```text
01-素材总表
02-章节映射表
03-素材卡片
04-待填写清单
05-使用规则
```

商务标素材和 Wiki 当前先保留为空。
