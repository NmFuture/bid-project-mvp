# 前端 API 字段依赖索引

> 更新时间：2026-05-24
> 适用范围：前端页面字段依赖梳理。

## 全局约定

- 前端调用基址：`/api`
- 开发代理目标：`VITE_API_PROXY_TARGET`
- 技术标项目使用 `technicalProjectsAPI`。
- 商务标项目使用 `businessProjectsAPI`。
- 技术标素材使用 `technicalMaterialsAPI`。
- 商务标素材使用 `businessMaterialsAPI`。

## Project

| 字段 | 说明 |
|---|---|
| `id` | 项目 ID |
| `name` | 项目名称 |
| `customerName` | 客户名称 |
| `manager` | 负责人 |
| `bidType` | `技术标` 或 `商务标`，由对应 workspace API 固定 |
| `projectCode` | 业务项目编号 |
| `materialCustomerId / materialCustomerName` | 客户素材身份 |
| `materialProjectMode` | `library` 表示已有素材项目，`ordinary` 表示普通项目 |
| `materialProjectId / materialProjectCode / materialProjectName` | 项目素材身份和展示名称 |
| `turbineModel` | 技术标投标机型结构化字段 |
| `turbineModelLabel` | 投标机型展示名 |
| `currentStage` | 项目内阶段 |
| `stageLabel` | 当前阶段名称 |
| `files` | 招标文件展示摘要 |
| `templateFiles` | 项目真实上传模板展示摘要 |

## Stage

技术标和商务标阶段组件已经拆分：

- `TechnicalProjectStageProgress`
- `BusinessProjectStageProgress`

页面只读取本 workspace 的阶段配置，不共享主流程阶段表。

## Materials

素材范围由对应 workspace 项目接口返回：

```text
技术标项目 -> technicalProjectsAPI.materialsPath(projectId)
商务标项目 -> businessProjectsAPI.materialsPath(projectId)
```

素材列表、Wiki、附件、清洗稿预览和下载也都走对应 workspace materials API。

## DocumentWorkspace

| 字段 | 说明 |
|---|---|
| `documentId` | 文档 ID |
| `fileName` | 当前 Word 文件名 |
| `fileUrl` | 浏览器可访问下载地址 |
| `version` | 文档版本 |
| `onlyoffice` | OnlyOffice 挂载配置 |
| `fallback` | OnlyOffice 不可用时的文本兜底内容 |

## 当前事实来源

字段以双轨 API 返回为准：

- `/Users/wlb/Agent/bid-project/code/sewpg-bid-frontend/src/api/index.js`
- `/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/api/routes/technical.py`
- `/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/api/routes/business.py`
