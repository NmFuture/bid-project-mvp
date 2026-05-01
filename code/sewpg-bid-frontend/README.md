# SEWPG Bid Frontend（上海电气风电投标前端）

## 1. 项目简介
本项目是“上海电气风电投标智能体”的前端工程，采用 **前后端分离** 架构，当前开发模式为：

- 前端：`React + Vite`
- 后端（唯一正式入口）：`../sewpg-bid-backend/app/main.py`（FastAPI）
- 数据交互：统一通过 `src/api/index.js` 发起 HTTP API 调用
- 文档编辑：S6/S9 阶段支持 `OnlyOffice` 在线挂载（预览/编辑）
- 旧 `fastapi-mock / mock-server / smoke` 资产已移除，当前只保留正式 FastAPI 联调路径

当前仓库已进入“**主链路真实 + 外围模块正式承接**”阶段：

- 主链路真实阶段：`S0 / S1 / S2 / S3 / S7 / S8 / S9 / S10`
- 过渡 mock / 承接阶段：`S4 / S5 / S6`
- 外围模块已由正式 FastAPI 承接：原始材料库、结构化素材库、Wiki 素材库、审计日志、系统设置、导出校验
- `S8` 当前是 S7 拼装计划与素材库覆盖关系校验，还不是完整评分点覆盖审计

一句话：

> **前端现在默认对接正式 FastAPI，而不是历史 mock 网关。**

## 2. 当前阶段能力
### 2.1 主链路（S1-S10）
- S1：上传招标文件并自动解析（招标文件必选、模板文件可选）
- S2：目录生成（触发后端生成目录 docx）
- S3：目录审核（增删改、排序、确认）
- S4：素材缺口识别（触发识别、展示缺失项）
- S5：备料补交（上传、冲突处理、补料回执）
- S6：审核备料（已补录/未补录及原因）
- S7：填充（触发填充、展示输出文件）
- S8：覆盖校验（目录响应树、问题清单）
- S9：人机共创（OnlyOffice 编辑 + 回写）
- S10：导出（下载最终 Word）

### 2.2 配套模块
- 项目管理（创建、删除、阶段跳转）
- 原始素材库（树形目录、上传、移动、重命名、删除、下载）
- 结构化素材导入链路（模板下载、预检、确认入库）
- Wiki 素材库（节点编辑、拖拽移动、附件）
- 审计日志（筛选、详情、CSV 导出）
- 设置中心（网关、模板、备份恢复、健康检查）
- 认证（登录、会话、退出）

说明：

- 上述外围模块当前已经由正式 FastAPI 提供可用承接
- 其中部分数据仍属于 `fixture/mock-backed` 形态，用于支撑当前前端页面和联调，不代表正式版最终业务模型

## 3. 前后端分离架构
## 3.1 前端职责
- 路由与页面编排
- 状态渲染（`loading / empty / error / permission-denied`）
- 统一 API 客户端能力（超时、取消、重试、traceId）
- 业务交互（按钮/表单/流程控制）

## 3.2 后端职责（当前为 FastAPI 入口）
- 提供统一 FastAPI 联调入口（默认 `http://localhost:8000`）
- 提供业务 API 契约
- 维护项目流程状态与阶段门禁
- 维护素材库、审计、设置、认证会话
- 提供 OnlyOffice 文档会话与保存回调入口
- 为 MVP 非主链路与外围模块提供正式承接层（部分为轻量 mock/fixture 语义）

## 3.3 本轮分离一致性修复
以下点已改为 API 驱动：
- 登录：由前端假登录改为 `POST /api/auth/login`
- 会话探测：新增 `GET /api/auth/me`
- 顶部用户信息：改为显示后端返回用户
- 退出登录：接入 `POST /api/auth/logout`
- 项目列表分页：移除硬编码总页数，使用 API `total/page/pageSize`
- 项目驾驶舱任务：移除硬编码任务，改为 `GET /api/projects/:id/cockpit`
- 素材选择弹窗：改为 API 异常可见、无 mock 注释逻辑

## 4. 目录结构
```text
sewpg-bid-frontend/
├── src/
│   ├── api/                 # API 客户端封装
│   ├── components/          # 布局、共享组件、弹窗
│   ├── config/              # 环境变量与 OnlyOffice 配置
│   ├── pages/               # 页面（S1-S10 + 素材/审计/设置）
│   └── utils/               # 阶段流转等工具
├── docs/
│   ├── 10-API接口总览与契约说明.md
│   └── 11-API字段级契约明细.md
```

## 5. 本地启动
## 5.1 安装依赖
```bash
npm install
```

## 5.2 安装正式后端依赖（首次）
```bash
cd ../sewpg-bid-backend
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

## 5.3 启动后端（默认 FastAPI 8000）
方式 A：直接使用当前前端封装好的正式后端脚本
```bash
npm run api:fastapi
```

说明：
- 该命令默认使用 `uvicorn --reload --reload-dir app`
- 修改 `sewpg-bid-backend/app` 下代码后会自动重载，无需手动重启 8000 端口服务

方式 B：手动启动正式后端
```bash
cd ../sewpg-bid-backend
ONLYOFFICE_BACKEND_BASE_URL=http://<backend-reachable-host>:8000 ./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app
```

说明：
- `ONLYOFFICE_BACKEND_BASE_URL` 必须是 OnlyOffice 容器能访问到的后端地址
- macOS / Windows 常见写法是 `http://host.docker.internal:8000`
- Linux 常见写法是宿主机内网 IP 或可解析域名

## 5.4 启动前端（默认 5173）
```bash
npm run dev
```

常用地址：
- 前端开发：`http://localhost:5173/projects`
- 前端预览：`http://localhost:4173/projects`（`npm run preview`）
- FastAPI 入口：`http://localhost:8000`
- API 基址（前端侧）：`/api`

## 6. 质量门禁命令
```bash
npm run lint
npm run build
npm run check
```

- 当前推荐最小门禁：`npm run check`
- 后端回归验证统一使用 `../sewpg-bid-backend/tests`

## 7. 环境变量
| 变量 | 说明 | 示例 |
|---|---|---|
| `VITE_APP_ENV` | 环境标识 | `development` |
| `VITE_DEV_PORT` | 前端端口 | `5173` |
| `VITE_API_BASE_URL` | API 基路径/域名 | `/api` |
| `VITE_API_PROXY_TARGET` | 本地代理目标 | `http://localhost:8000` |
| `VITE_API_TIMEOUT_MS` | 单次请求超时 | `12000` |
| `VITE_API_RETRY_COUNT` | GET 重试次数 | `1` |
| `VITE_API_ENABLE_TRACE` | 是否透传 traceId | `true` |
| `VITE_ONLYOFFICE_DOCUMENT_SERVER_URL` | OnlyOffice 服务地址 | `http://localhost:8080` |
| `VITE_ONLYOFFICE_HEALTHCHECK_PATH` | OnlyOffice 健康检查路径 | `/healthcheck` |

## 8. OnlyOffice 嵌入与挂载（S6/S9）
## 8.1 前置条件
- 后端可访问 `OnlyOffice Document Server`
- 前端可加载脚本：
  - `${VITE_ONLYOFFICE_DOCUMENT_SERVER_URL}/web-apps/apps/api/documents/api.js`
- 项目已进入 S6 或 S9（阶段门禁）

## 8.2 前端挂载流程（已实现）
1. S6 审核备料文档预览：
   - 打开 S6 页面后调用 `GET /api/projects/:id/review-items/document`
   - 回写接口：`PUT /api/projects/:id/review-items/document/save`
   - 强制保存：`POST /api/projects/:id/review-items/document/force-save`
   - 回调入口：`POST /api/projects/:id/review-items/document/callback`
2. S9 人机共创编辑：
   - 打开 S9 页面后调用 `GET /api/projects/:id/document`
   - 回写接口：`PUT /api/projects/:id/document/save`
   - 强制保存：`POST /api/projects/:id/document/force-save`
   - 回调入口：`POST /api/projects/:id/document/callback`
3. 后端返回文档会话信息：
   - `documentKey`
   - `title`
   - `fileUrl`
   - `callbackUrl`
   - `user`
4. 前端动态加载 OnlyOffice API 脚本
5. 前端用 `new DocsAPI.DocEditor(containerId, config)` 挂载编辑器
6. S10 下载最终文件：`GET /api/projects/:id/final-document`

## 8.3 回写链路说明
- S6 回调入口：`POST /api/projects/:id/review-items/document/callback`
- S9 回调入口：`POST /api/projects/:id/document/callback`
- 当前正式 FastAPI 中，当 `status` 为 `2/6/7` 时会更新文档版本与保存时间
- 回调成功返回：`{ "error": 0 }`

## 8.4 网络与部署注意事项
- 若 OnlyOffice 跑在 Docker 内，`callbackUrl` 必须是 **Document Server 能访问到的后端地址**。
- `localhost` 在容器内通常指容器自身；必要时使用企业内网域名或网关地址。
- 前后端跨域时，需确保网关/CORS 策略允许 Document Server 回调。

## 8.5 兜底策略
- 前端会先做健康检查；若 OnlyOffice 不可达，S6/S9 自动切换文本编辑兜底模式。
- 兜底模式回写接口：
  - S6：`PUT /api/projects/:id/review-items/document/save`
  - S9：`PUT /api/projects/:id/document/save`

## 9. API 客户端能力说明
`src/api/index.js` 已内建：
- 超时控制（`AbortController`）
- 外部中断取消（`signal`）
- 错误归一化（`ApiError`）
- GET 自动重试（网络错误/超时/5xx）
- `traceId` 自动透传（`x-trace-id`）

## 10. 场景化联调（FastAPI 入口）
当前联调链路：前端 -> 正式 FastAPI（8000）。

说明：
- 主链路阶段已按真实集成联调为主
- 外围模块由正式 FastAPI 提供承接
- 旧 mock 网关与场景注入脚本已从当前仓库运行路径中移除

当前推荐验证方式：
- 前端：`npm run check`
- 后端：`./.venv/bin/python -m unittest`

## 11. 部署建议（企业）
- 前端：构建为静态资源（`dist/`）并由 Nginx/CDN 托管
- 后端：独立服务部署（真实 API）
- 网关：统一 `/api` 转发；OnlyOffice callback 走可达内网域名
- CI：固定 `lint -> unit -> build` 后才能合入
- 观测：建议接入前端异常上报、关键链路埋点、Web Vitals

## 12. 已知约定
- 当前仓库保持 JavaScript，不做全量 TypeScript 迁移。
- 当前已默认切到正式 FastAPI 联调入口。
- 外围模块当前已由正式 FastAPI 承接，但其中部分数据仍是 fixture/mock 语义。
- API 文档总览：`docs/10-API接口总览与契约说明.md`
- API 字段级明细：`docs/11-API字段级契约明细.md`
