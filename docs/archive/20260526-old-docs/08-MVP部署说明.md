# MVP 部署与运行方式说明

> 用途：记录当前已经确认的部署口径，作为后续开发、联调、给客户部署时的统一说明。
> 更新日期：2026-05-26

## 1. 交付形态

当前 MVP 面向客户单位使用时，推荐采用：

> **一台内网服务器 + Docker Compose + 浏览器访问内网 Web**

也就是说：

- 前端、FastAPI、`opencode`、OnlyOffice 都部署在客户内网服务器上
- 客户单位员工不需要安装本地客户端
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

## 3. 当前 Compose 组成

### 3.1 8 个服务容器

1. `web`
- 负责对外提供 Web 入口
- 承载前端静态页面
- 通常也顺便做反向代理

2. `fastapi`
- 业务后端
- 负责项目、阶段、文件、解析、目录生成、缺口处理、正文拼装、素材覆盖诊断、OnlyOffice 对接和下载

3. `worker`
- Redis 队列消费者
- 负责目录生成、正文拼装、素材清洗等后台任务

4. `opencode`
- 运行 `opencode serve`
- 供 FastAPI 调用目录生成、缺口处理、AI 填写等 Skill 能力
- 镜像内保留正文拼装所需本地 skill 资产与 Python 依赖

5. `onlyoffice`
- 运行 OnlyOffice Document Server
- 提供在线文档预览和编辑能力

6. `postgres`
- 项目主链路状态数据库
- 素材库、Wiki、结构化素材、设置和审计日志数据库

7. `redis`
- 后台任务队列、任务锁和结果缓存

8. `minio`
- 上传文件、素材文件、清洗后 Word、默认模板、Wiki 附件和生成文档对象存储

### 3.2 持久化数据

最少建议保留这些持久化卷：

- `postgres_data`
  - 存项目、阶段、目录、文档记录、素材库元数据、Wiki、设置和审计
- `redis_data`
  - 存 Redis AOF 队列数据
- `minio_data`
  - 存素材原文件、清洗后 Word、Wiki 附件、默认模板和生成文档对象
- `uploads`
  - 存用户上传的招标文件和项目模板
- `documents`
  - 存生成的 docx、OnlyOffice 保存回来的最新版文档和项目工作区
- `parsed`
  - 存 `S0` 解析运行期临时产物，例如 `combined.txt`

一句话：

> **当前 MVP 是多服务容器 + 明确的数据卷：PostgreSQL 管状态和元数据，MinIO 管对象，Redis 管后台任务。**

## 4. 用户怎么使用

用户看到的主流程是：

```text
S0 解析 -> S1 模板与目录 -> S2 审核目录 -> S3 缺口处理 -> S4 生成标书 -> S5 共创 -> S6 导出
```

对客户单位员工来说：

1. 在内网打开系统网址
2. 进入 `解析` 模块上传招标文件并做投标决策
3. 决定参与后进入项目工作区
4. 按 `S1-S6` 页面流程操作
5. 在浏览器里打开 OnlyOffice 编辑文档
6. 下载最终 Word

## 5. 当前运行口径

当前主链路真实能力：

- `S0`：多招标文件解析、PDF/图片型文件无感识别、投标决策和项目信息补全
- `S1`：模板上传或设置侧系统默认模板读取；调用 futurecode/opencode 执行 `s2toc` 生成目录，本地 Skill 脚本作为降级路径
- `S2`：审核目录
- `S3`：技术标和商务标都已拆入各自缺口 service，缺口识别、补料、AI 填写、素材预览、完整性复查和审核入口按双轨边界实现
- `S4`：调用 `bid-tech-assembler`，按目录 JSON、缺口计划、Wiki 和素材库拼装正文
- `S5`：OnlyOffice 共创编辑
- `S6`：在 `/editor` 内下载最新版 Word/PDF

注意：

- 旧的 `S7/S8/S9/S10` 不再作为部署验收阶段。
- `coverage` 仍保留为生成后/导出前的诊断能力，不是独立主流程节点。
- Word/PDF 下载入口已经接入 `/editor`；评分点级覆盖审计、证据链一致性和完整格式验收是后续专项。

## 6. 服务之间的关系

```text
浏览器
  -> web
  -> fastapi
     -> PostgreSQL / uploads / parsed / documents
     -> Redis worker
     -> MinIO
     -> opencode serve
     -> onlyoffice
```

说明：

- 前端不直接调用 `opencode`
- 前端不直接处理 OnlyOffice 回调
- FastAPI 是唯一业务后端

## 7. 当前需要记住的边界

- 当前 MVP 已接入 PostgreSQL、MinIO、Redis。
- 当前 MVP 已接入真实登录鉴权、持久化审计、设置页 LLM 与 PDF/图片识别模型配置、技术标/商务标系统默认模板和 PDF/图片型文件无感解析。
- 设置页系统默认模板是项目未上传模板时的生成输入，不作为项目上传文件展示。
- 当前暂不做 SSO、评分点级覆盖审计、证据链一致性和完整导出前格式验收。

## 8. 模型访问前提

如果 `opencode` 背后要访问外部模型 API，部署服务器需要满足以下条件之一：

- 可以访问外部模型服务
- 可以访问客户内部的模型网关
- 或后续切到客户可用的私有化模型

这不是前端问题，而是部署前必须确认的环境前提。

## 9. 实际怎么部署

### 9.1 部署前准备

服务器至少需要准备：

- Docker
- Docker Compose
- 项目代码目录
- 一个 `.env` 文件

建议：

```bash
cd code
cp .env.example .env
```

按部署环境填写配置后执行：

```bash
docker compose up -d --build
```

已有本机容器时，如果要确保当前代码重新进入镜像和容器，使用：

```bash
docker compose build --no-cache
docker compose up -d --force-recreate
```

### 9.2 重点配置哪些环境变量

- `WEB_PORT`
  - 浏览器访问入口端口
- `OPENCODE_BASE_URL`
  - FastAPI 调用的 `opencode` 地址，默认是 `http://opencode:4096`
- `OPENCODE_PROVIDER_ID`
- `OPENCODE_MODEL_ID`
- `OPENCODE_TIMEOUT_SEC`
- `OPENAI_API_KEY / ANTHROPIC_API_KEY / GOOGLE_API_KEY`
- `OPENCODE_AUTH_HOST_DIR`
- `AUTH_ADMIN_EMAIL / AUTH_ADMIN_PASSWORD / AUTH_ADMIN_NAME`
- `DEFAULT_LLM_BASE_URL / DEFAULT_LLM_API_KEY / DEFAULT_LLM_MODEL`
- `DEFAULT_OCR_BASE_URL / DEFAULT_OCR_API_KEY / DEFAULT_OCR_MODEL`
- `ONLYOFFICE_INTERNAL_URL`
- `ONLYOFFICE_BACKEND_BASE_URL`

这里要特别注意：

> `ONLYOFFICE_BACKEND_BASE_URL` 必须是“浏览器 + OnlyOffice 容器”都能访问到的共享地址。

推荐口径：

- 单机本地 compose：可以留空，由 FastAPI 自动优先探测当前机器局域网 IP
- 多机 / 服务器部署：显式填写服务器域名或 IP，例如 `https://bid-mvp.example.com`

不推荐：

- `http://fastapi:8000`
  - 浏览器通常访问不到
- `http://127.0.0.1`
  - OnlyOffice 容器通常访问不到

部署经验：

- 如果保留 compose 自带的 `opencode`，`OPENCODE_BASE_URL` 保持 `http://opencode:4096`
- 如果切到外部 `opencode` 网关，只改 `OPENCODE_BASE_URL`
- `OPENCODE_PROVIDER_ID / OPENCODE_MODEL_ID` 决定 FastAPI 调用哪个 provider/model
- `OPENCODE_TIMEOUT_SEC` compose 默认 `1800` 秒；目录生成、缺口处理、正文拼装等长任务都按这个长超时口径部署

### 9.3 当前工作区路径

历史内部目录名仍保留以兼容代码和已有数据：

- `parsed/{project_id}/`：`S0` 运行期临时解析缓存
- `documents/{project_id}/technical-workspace/parse/`：进入项目后的解析产物
- `documents/{project_id}/technical-workspace/s2_toc_workdir/`：当前 `S1` 目录生成产物
- `documents/{project_id}/technical-workspace/s4_gap_workdir/`：当前 `S3` 缺口处理产物
- `documents/{project_id}/technical-workspace/s7_assembly_workdir/`：当前 `S4` 正文拼装产物
- `documents/{project_id}.docx`：当前 `S5/S6` 共创和导出文档

### 9.4 启动方式

```bash
cd code
docker compose up -d --build
```

重建当前代码镜像并替换已有容器：

```bash
docker compose build --no-cache
docker compose up -d --force-recreate
```

查看状态：

```bash
docker compose ps
docker compose logs -f fastapi
docker compose logs -f opencode
```

### 9.5 启动后先检查什么

建议先看这几层：

1. `web` 是否可访问
2. `fastapi /healthz` 是否正常
3. `opencode /global/health` 是否正常
4. OnlyOffice 页面资源和 `/healthcheck` 是否正常
5. 浏览器里是否能走通：
   - 登录
   - `S0` 新建审核项目并解析
   - `S1` 模板与目录
   - `S2` 审核目录
   - `S3` 缺口处理
   - `S3/S4` 在素材匹配页触发正文生成，素材预览以弹出层打开
   - `S5/S6` 打开共创导出页并下载 Word/PDF
6. 设置页能查看用户、默认模板、LLM、PDF/图片识别模型配置、备份和健康状态
7. 审计页能看到登录、设置变更、模型测试、默认模板启用等真实操作记录
8. OCR/视觉模型未配置时，图片或扫描件解析给出明确警告；配置后图片或图片型 PDF 自动进入原有解析链路

## 10. 一句话总结

> **当前 MVP 推荐部署方式就是：一台客户内网服务器，使用 Docker Compose 跑 `web + fastapi + worker + opencode + onlyoffice + postgres + redis + minio`，客户员工直接通过内网浏览器访问 S0-S6 流程。**
