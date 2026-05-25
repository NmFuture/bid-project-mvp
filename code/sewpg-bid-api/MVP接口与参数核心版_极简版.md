# 双轨 API 核心版

> 用途：当前 `Web -> FastAPI` 的简版开发口径。
> 更新日期：2026-05-24

旧 MVP 单线接口已经不是当前基线。当前业务接口按标类分成两组：

```text
技术标：/api/technical/...
商务标：/api/business/...
```

## 技术标接口族

- 项目与阶段：`/api/technical/projects...`
- 解析：`/api/technical/projects/{project_id}/parse-results...`
- 模板与目录：`/api/technical/projects/{project_id}/template-fallback`、`/api/technical/projects/{project_id}/directory-generation...`、`/api/technical/projects/{project_id}/outline...`
- 缺口处理：`/api/technical/projects/{project_id}/gaps...`
- 生成、文档、下载：`/api/technical/projects/{project_id}/fill-generation...`、`/api/technical/projects/{project_id}/document...`、`/api/technical/projects/{project_id}/final-document...`
- 后端诊断/兼容交付：`/api/technical/projects/{project_id}/coverage`、`/api/technical/projects/{project_id}/export...`；前端主流程不再保留对应页面或 API facade。
- 素材库和 Wiki：`/api/technical/materials...`
- OCR：`/api/technical/projects/{project_id}/ocr...`
- 审计：`/api/technical/audit...`

## 商务标接口族

- 项目与阶段：`/api/business/projects...`
- 解析：`/api/business/projects/{project_id}/parse-results...`
- 模板与目录：`/api/business/projects/{project_id}/template-fallback`、`/api/business/projects/{project_id}/directory-generation...`、`/api/business/projects/{project_id}/outline...`
- 商务缺口：`/api/business/projects/{project_id}/business-gaps...`
- 商务文档：`/api/business/projects/{project_id}/document...`
- 素材库和 Wiki：`/api/business/materials...`
- OCR：`/api/business/projects/{project_id}/ocr...`
- 审计：`/api/business/audit...`

## 前端 API 封装

前端只应使用 `src/api/index.js` 中的双轨封装：

- `technicalProjectsAPI` / `businessProjectsAPI`
- `technicalParseAPI` / `businessParseAPI`
- `technicalDirectoryAPI` / `businessDirectoryAPI`
- `technicalOutlineAPI` / `businessOutlineAPI`
- `technicalGapsAPI` / `businessGapsAPI`
- `technicalGenerateAPI` / `businessGenerateAPI`
- `technicalDocumentAPI` / `businessDocumentAPI`
- `technicalMaterialsAPI` / `businessMaterialsAPI`
- `technicalAuditAPI` / `businessAuditAPI`

## 当前事实来源

详细契约以代码和总计划为准：

- `/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/api/routes/technical.py`
- `/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/api/routes/business.py`
- `/Users/wlb/Agent/bid-project/doc/31-技术标与商务标双轨独立化实施计划.md`
