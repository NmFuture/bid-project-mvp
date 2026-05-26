# SEWPG Bid Frontend

> 当前口径：前端已经进入技术标/商务标双轨独立化阶段。
> 更新日期：2026-05-26

## 项目简介

本工程是上海电气风电投标智能体前端：

- 前端：`React + Vite`
- 后端：`../sewpg-bid-backend/app/main.py`
- API 客户端：`src/api/index.js`
- 技术标页面：`src/workspaces/technical`
- 商务标页面：`src/workspaces/business`

当前不是旧单线 MVP 页面结构。开发时先判断需求属于技术标还是商务标，再进入对应 workspace。

## 当前入口

```text
/parse/technical
/parse/business
/workspace/tech/projects
/workspace/tech/projects/:id/template-directory
/workspace/tech/projects/:id/outline
/workspace/tech/projects/:id/gaps
/workspace/tech/projects/:id/editor
/workspace/business/projects
/workspace/business/projects/:id/template-directory
/workspace/business/projects/:id/outline
/workspace/business/projects/:id/gaps
/workspace/business/projects/:id/editor
```

技术标和商务标都不再保留独立 `/generate`、`/coverage`、`/export` 项目页面。素材匹配页内的素材预览使用弹出层，正文生成在 `/gaps` 内触发，共创、格式和 Word/PDF 下载在 `/editor` 内完成。

## API 规则

```text
技术标页面 -> technical*API -> FastAPI technical routes
商务标页面 -> business*API -> FastAPI business routes
```

共享 API 只保留：

- `authAPI`
- `settingsAPI`
- `dashboardAPI`

业务页面不要重新引入旧通用项目、解析、素材、审计等 API 封装。

## 本地启动

安装依赖：

```bash
npm install
```

启动后端：

```bash
cd ../sewpg-bid-backend
./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app
```

启动前端：

```bash
npm run dev
```

常用地址：

- 前端开发：`http://localhost:5173`
- FastAPI：`http://localhost:8000`
- API 基址：`/api`

## 质量门禁

```bash
npm run lint
npm run build
npm run check
```

当前推荐最小门禁：`npm run check`。

## 文档入口

- `/Users/wlb/Agent/bid-project/doc/31-技术标与商务标双轨独立化实施计划.md`
- `/Users/wlb/Agent/bid-project/code/sewpg-bid-frontend/docs/10-API接口总览与契约说明.md`
- `/Users/wlb/Agent/bid-project/code/sewpg-bid-frontend/docs/11-API字段级契约明细.md`
