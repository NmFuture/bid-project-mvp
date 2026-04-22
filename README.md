# Bid Project MVP

这是一个已经收口到 **Docker Compose 可部署形态** 的标书智能体 MVP 仓库。

当前仓库的目标不是“所有业务都做成正式版”，而是：

- 主链路可以真实走通
- 外围阶段可以完整演示
- 别人拿到仓库后，按 README 就能在一台机器上把整套系统跑起来

当前已验证的主链路是：

`S1 解析 -> S2 目录生成 -> S3 目录确认 -> S4/S5/S6 承接 -> S7 初稿生成 -> S9 OnlyOffice 共创 -> S10 下载`

其中：

- 真实执行阶段：`S0 / S1 / S2 / S3 / S7 / S9 / S10`
- 承接 / mock-backed 阶段：`S4 / S5 / S6 / S8`

当前仓库已经按 `docker compose` 做过一轮真实主链路验收：

- `S1` 上传并解析成功
- `S2` 目录生成成功
- `S6` 文档预览可用
- `S7` 初稿生成成功
- `S9` OnlyOffice 不再白屏
- `S10` 最终文档下载接口返回 `200`

## 目录说明

- `code/`
  - 真正的可运行代码和 `docker-compose.yml`
- `doc/`
  - 规格、部署说明、接口说明
- `服务器部署方案/`
  - 早期部署资料，可作为补充参考

## 部署架构

当前 compose 默认启动 4 个服务：

- `web`
  - 前端静态页面 + `/api` / `/ds` 反向代理
- `fastapi`
  - 唯一业务后端
- `opencode`
  - 目录生成 / 初稿生成
- `onlyoffice`
  - 在线文档预览和编辑

当前 compose 还会保留这些数据卷：

- `sqlite_data`
  - 项目状态和流程状态
- `uploads`
  - 用户上传的招标文件
- `documents`
  - 生成后的 `.docx`
- `parsed`
  - `S1` 解析产物，例如 `combined.txt`

`parsed` 很重要。
如果它不持久化，`fastapi` 容器重建后，`S2 / S7` 会因为找不到 `S1` 的解析结果而断链。

## 快速启动

### 0. 前置条件

- 已安装 Docker
- 已安装 Docker Compose Plugin

### 1. 克隆并准备配置

```bash
git clone https://github.com/NmFuture/bid-project-mvp.git
cd bid-project-mvp/code
cp .env.example .env
```

然后按你的环境修改当前目录下的 `.env`。

### 2. 启动

```bash
docker compose up -d --build
```

### 3. 查看状态

```bash
docker compose ps
docker compose logs -f fastapi
docker compose logs -f opencode
docker compose logs -f onlyoffice
```

### 4. 打开系统

浏览器访问：

- `http://localhost`

如果你修改了 `WEB_PORT`，就访问对应端口，例如 `http://localhost:8080`。

## 健康检查

启动后建议先检查这几个地址：

- `http://localhost/api/healthz`
- `http://localhost/ds/healthcheck`
- `http://localhost:4096/global/health`

如果你修改了 `WEB_PORT` 或 `OPENCODE_HOST_PORT`，请把地址里的端口一起替换。

## 怎么切换大模型 URL / key / modelId

这是当前部署里最重要的配置点。

### 场景 A：继续使用 compose 里自带的 `opencode`

这种情况下，`fastapi` 继续调用 compose 内部的 `opencode`：

```env
OPENCODE_BASE_URL=http://opencode:4096
```

你需要改的是：

```env
OPENCODE_PROVIDER_ID=<你的 providerID>
OPENCODE_MODEL_ID=<你的 modelID>

OPENAI_API_KEY=<如果你走 OpenAI / OpenAI-compatible>
ANTHROPIC_API_KEY=<如果你走 Anthropic>
GOOGLE_API_KEY=<如果你走 Google>
```

要点：

- `OPENCODE_PROVIDER_ID`
  - 告诉 FastAPI 调 opencode 时使用哪个 provider
- `OPENCODE_MODEL_ID`
  - 告诉 FastAPI 用哪个模型
- `OPENAI_API_KEY / ANTHROPIC_API_KEY / GOOGLE_API_KEY`
  - 由 `opencode` 容器读取，用于真正访问外部模型

### 场景 B：改成外部独立的 `opencode` 网关

如果你们已经有单独部署好的 `opencode`，只改：

```env
OPENCODE_BASE_URL=http://your-opencode-host:4096
```

同时继续设置：

```env
OPENCODE_PROVIDER_ID=<你的 providerID>
OPENCODE_MODEL_ID=<你的 modelID>
```

这时：

- `fastapi` 会去调外部 `opencode`
- compose 里的本地 `opencode` 可以继续保留但不被使用
- 如果你不想浪费资源，也可以手动停掉 compose 里的 `opencode` 服务

### 场景 C：使用 `auth.json`

如果你不是直接用环境变量 key，而是让 `opencode` 读宿主机认证文件，可以这样：

```env
OPENCODE_AUTH_HOST_DIR=./opencode-auth
```

把认证文件放到：

- `code/opencode-auth/auth.json`

compose 会把这个目录挂进 `opencode` 容器。

## 当前最重要的环境变量

`code/.env.example` 里已经列了最小配置项，重点如下：

| 变量 | 作用 |
|---|---|
| `WEB_PORT` | 浏览器入口端口 |
| `OPENCODE_HOST_PORT` | 本机暴露给调试使用的 opencode 端口 |
| `OPENCODE_BASE_URL` | FastAPI 调用的 opencode 地址 |
| `OPENCODE_PROVIDER_ID` | 调用 opencode 时的 provider |
| `OPENCODE_MODEL_ID` | 调用 opencode 时的模型 ID |
| `OPENCODE_TIMEOUT_SEC` | FastAPI 调用 opencode 的超时，默认建议 `60` 秒，超时会触发回退目录 |
| `OPENAI_API_KEY` | OpenAI / OpenAI-compatible 模型 key |
| `ANTHROPIC_API_KEY` | Anthropic key |
| `GOOGLE_API_KEY` | Google key |
| `OPENCODE_AUTH_HOST_DIR` | 宿主机 `auth.json` 挂载目录 |
| `ONLYOFFICE_INTERNAL_URL` | FastAPI 访问 OnlyOffice 的内部地址 |
| `ONLYOFFICE_BACKEND_BASE_URL` | 浏览器与 OnlyOffice 容器都能访问的共享 Web 地址，用于文档下载和回调 |
| `ONLYOFFICE_ALLOW_PRIVATE_IP_ADDRESS` | 允许 OnlyOffice 访问内网地址 |

## 推荐验收步骤

部署后建议按这条线验：

1. 登录系统
2. 新建项目
3. `S1` 上传一个小的 `docx/pdf`
4. `S2` 点击“生成目录”
5. `S3` 确认目录
6. `S4/S5/S6` 继续走承接流程
7. `S7` 点击“触发填充”，观察进度、任务、事件和 opencode 输出
8. `S9` 确认 OnlyOffice 编辑器正常显示
9. `S10` 下载最终版 Word

补充说明：

- `S2` 默认先真实调用 `opencode`
- 如果 `opencode` 在 `OPENCODE_TIMEOUT_SEC` 内没有返回可用 JSON，系统会自动生成一版“可继续审核的回退目录”
- `S7` 仍然优先走真实 `opencode` 初稿生成

## OnlyOffice 地址说明

`ONLYOFFICE_BACKEND_BASE_URL` 不是简单的“FastAPI 内部地址”。

它必须同时满足两件事：

- 浏览器能访问
- `onlyoffice` 容器也能访问

推荐口径：

- 单机本地 compose：可以留空，FastAPI 会优先自动探测当前机器的局域网 IP
- 多机 / 服务器部署：显式填写可访问域名或服务器 IP，例如 `https://bid-mvp.example.com` 或 `http://192.168.31.148`

不推荐直接写：

- `http://fastapi:8000`
  - 这个地址通常只对 Docker 内部容器可达，浏览器不可达
- `http://127.0.0.1`
  - 这个地址通常只对宿主机浏览器可达，`onlyoffice` 容器不可达

## 已知边界

- `S4 / S5 / S6 / S8` 仍然是承接态，不是正式业务实现
- 当前默认数据库是 SQLite，不是 PostgreSQL
- 当前默认没有接入 SSO、OCR、Redis、MinIO
- `opencode` 能否真实生成，取决于你配置的 provider / model / key 是否可用

## 相关文档

- [MVP 主链路说明](./doc/05-MVP主链路说明.md)
- [FastAPI 承接与前端改造](./doc/07-FastAPI承接与前端改造.md)
- [MVP 部署说明](./doc/08-MVP部署说明.md)
- [内网离线部署说明](./doc/11-内网离线部署说明.md)
