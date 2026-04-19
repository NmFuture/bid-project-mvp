# MVP 部署与运行方式说明

> 用途：记录当前已经确认的部署口径，作为后续开发、联调、给客户部署时的统一说明。

## 1. 交付形态

当前 MVP 面向客户单位使用时，推荐采用：

> **一台内网服务器 + Docker Compose + 浏览器访问内网 Web**

也就是说：

- 前端、FastAPI、`opencode`、OnlyOffice 都部署在客户内网服务器上
- 客户单位员工不需要装本地客户端
- 用户直接通过浏览器访问内网地址即可使用

典型访问方式：

```text
客户员工浏览器 -> 内网 Web 地址 -> 系统
```

## 2. 部署方式

当前 MVP 推荐用 `Docker Compose` 部署。

不是把所有东西塞进一个容器，而是：

> **多个服务容器 + 若干持久化数据卷**

这是当前最稳、最容易运维、也最适合 MVP 的方式。

## 3. 当前 MVP 的 Compose 组成

当前建议的核心组成是：

### 3.1 4 个服务容器

1. `web`
- 负责对外提供 Web 入口
- 承载前端静态页面
- 通常也顺便做反向代理
- 建议用 `nginx`

2. `fastapi`
- 业务后端
- 负责项目、阶段、文件、解析、目录生成、初稿生成、OnlyOffice 对接、下载

3. `opencode`
- 运行 `opencode serve`
- 供 FastAPI 调用目录生成和初稿生成能力

4. `onlyoffice`
- 运行 OnlyOffice Document Server
- 提供在线文档编辑能力

### 3.2 持久化数据

当前 MVP 不需要单独起数据库容器，先用：

- `SQLite`
- 本地文件目录 / Docker volume

最少建议保留这些持久化卷：

- `sqlite_data`
  - 存项目、阶段、目录、文档记录
- `uploads`
  - 存用户上传的招标文件
- `documents`
  - 存生成的 docx、OnlyOffice 保存回来的最新版文档
- `parsed`
  - 存 `S1` 解析后的中间产物，例如 `combined.txt`

一句话：

> **当前 MVP 是 4 个服务容器 + 4 个关键数据卷，不是“4 个容器 + 1 个数据容器”。**

## 4. 用户怎么使用

对客户单位员工来说，使用方式应当尽量简单：

1. 在内网打开系统网址
2. 进入项目列表
3. 新建项目并上传招标文件
4. 按页面流程操作
5. 在浏览器里打开 OnlyOffice 编辑文档
6. 下载最终 Word

也就是说，用户看到的是一个完整 Web 系统，而不是多个独立服务。

## 5. 当前 MVP 的运行口径

前端展示流程仍保留：

```text
S0 -> S1 -> S2 -> S3 -> S4 -> S5 -> S6 -> S7 -> S8 -> S9 -> S10
```

但当前真正做成真实能力的主链路是：

- `S0`：项目列表 / 新建项目
- `S1`：解析招标文件
- `S2`：调用 `opencode` 生成目录
- `S3`：审核目录
- `S7`：调用 `opencode` 生成初稿
- `S9`：OnlyOffice 共创编辑
- `S10`：下载最新版 Word

当前先由 FastAPI mock 的阶段：

- `S4`
- `S5`
- `S6`
- `S8`

这意味着：

> **客户看到的流程是完整的，但当前 MVP 只把关键链路做成真实执行。**

## 6. 服务之间的关系

当前建议的关系如下：

```text
浏览器
  -> web
  -> fastapi
     -> sqlite / uploads / documents
     -> opencode serve
     -> onlyoffice
```

说明：

- 前端不直接调用 `opencode`
- 前端不直接处理 OnlyOffice 回调
- FastAPI 是唯一业务后端

## 7. 当前需要记住的边界

- 正式版产品语义不变：`S5` 补料，`S7` 拼接
- 当前 MVP 为了最小改动，先借现有 `S7` 页面做初稿生成
- 当前 MVP 不上 PostgreSQL、MinIO、Redis
- 当前 MVP 不做 OCR、完整审核流、覆盖热力图、SSO

## 8. 一个前提提醒

如果 `opencode` 背后要访问外部模型 API，那么部署服务器需要满足以下条件之一：

- 可以访问外部模型服务
- 可以访问客户内部的模型网关
- 或后续切到客户可用的私有化模型

这个不是前端问题，而是部署前必须确认的环境前提。

## 9. 当前离“可部署 MVP”还差的几件事

从“本机联调可用”到“可交付部署”，当前还差的重点不是外围业务真逻辑，而是部署收口：

1. 完整跑通一次最终 `docker compose`
- 不是只验证单服务能起，而是验证 `web + fastapi + opencode + onlyoffice` 一起起来后，主链路能从浏览器走通

2. 把运行配置统一成部署口径
- 至少要把 `.env.example`、Compose、启动说明统一
- 避免出现“代码支持环境变量，但部署文档没写”的情况

3. 支持部署使用者自行配置 `opencode`
- `baseUrl` 需要可自行配置
- 外部模型 `apiKey` 需要可自行配置
- 最终应让部署方不改代码，只改环境变量或配置文件即可切换

一句话：

> **当前离可部署 MVP 主要还差“最终 Compose 验收 + 配置口径收口”，而不是再补外围真业务。**

补充：

- 2026-04-20 已经在本机用 compose 重新验过一次：
  - `PRJ-0010` 从 `S1` 跑到 `S10`
  - `S9` OnlyOffice 不再空白
  - `S7` 已改成异步进度展示，并能真实完成初稿生成
  - `S10` 最终文档下载返回 `200`

## 10. 实际怎么部署

可以按下面顺序理解和操作。

### 10.1 为什么是 4 个容器

不是为了“复杂”，而是为了把职责拆开：

- `web`
  - 只负责浏览器入口、静态前端、反向代理
- `fastapi`
  - 只负责业务接口和主链路状态
- `opencode`
  - 只负责目录生成、初稿生成
- `onlyoffice`
  - 只负责在线文档编辑

这样每个服务都能单独替换、排障、重启，但部署时仍然通过一个 `docker compose` 统一拉起。

### 10.2 部署前准备

服务器至少需要准备：

- Docker
- Docker Compose
- 项目代码目录
- 一个 `.env` 文件

建议做法：

1. 复制 `code/.env.example` 为 `code/.env`
2. 按部署环境填写配置
3. 再执行 `docker compose up -d --build`

### 10.3 重点配置哪些环境变量

当前至少要关注这些变量：

- `WEB_PORT`
  - 浏览器访问入口端口
- `OPENCODE_BASE_URL`
  - FastAPI 调用的 `opencode` 地址
  - 默认是 Compose 内部地址：`http://opencode:4096`
  - 如果后续切外部独立 `opencode`，就改这里
- `OPENCODE_PROVIDER_ID`
- `OPENCODE_MODEL_ID`
- `OPENCODE_TIMEOUT_SEC`
- `OPENAI_API_KEY / ANTHROPIC_API_KEY / GOOGLE_API_KEY`
  - `opencode` 背后调用外部模型时使用
- `OPENCODE_AUTH_HOST_DIR`
  - 如果要挂载宿主机上的 `auth.json`，就改这里
- `ONLYOFFICE_INTERNAL_URL`
- `ONLYOFFICE_BACKEND_BASE_URL`

这里最重要的一点是：

> **部署使用者需要能自己改 `opencode` 的 `baseUrl / apiKey`，而不是去改代码。**

再补一句部署经验：

- 如果保留 compose 自带的 `opencode`，`OPENCODE_BASE_URL` 保持 `http://opencode:4096`
- 如果切到外部 `opencode` 网关，只需要改 `OPENCODE_BASE_URL`
- `OPENCODE_PROVIDER_ID / OPENCODE_MODEL_ID` 负责决定 FastAPI 调用哪个 provider/model
- `OPENCODE_TIMEOUT_SEC` 默认建议先用 `60` 秒，超时后系统会回退到可继续审核的目录，避免页面长时间卡死
- `OPENAI_API_KEY / ANTHROPIC_API_KEY / GOOGLE_API_KEY` 负责让 `opencode` 真正访问外部模型

补充：

- `S2` 默认先真实调用 `opencode`
- 如果 `opencode` 在超时内没有返回可解析 JSON，系统会自动生成一版回退目录，保证后续 `S3-S10` 可继续联调
- `S7` 仍以真实 `opencode` 初稿生成为主

### 10.4 启动方式

在 `code/` 目录执行：

```bash
docker compose up -d --build
```

查看状态：

```bash
docker compose ps
docker compose logs -f fastapi
docker compose logs -f opencode
```

### 10.5 启动后先检查什么

建议先看这几层：

1. `web` 是否可访问
2. `fastapi /healthz` 是否正常
3. `opencode /global/health` 是否正常
4. OnlyOffice 页面资源和 `/healthcheck` 是否正常
5. 浏览器里是否能走通：
   - 登录
   - 新建项目
   - S1 解析
   - S2 目录生成
   - S7 初稿生成
   - S9 打开编辑器
   - S10 下载

## 11. 一句话总结

> **当前 MVP 推荐部署方式就是：一台客户内网服务器，使用 Docker Compose 跑 `web + fastapi + opencode + onlyoffice` 四个服务，再配合 SQLite 和文件卷；客户员工直接通过内网浏览器访问即可。**
