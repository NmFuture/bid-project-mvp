# Bid Project MVP

这是一个已经收口到 **Docker Compose 可部署形态** 的标书智能体 MVP 仓库。当前目标不是把所有远期业务一次性做完，而是让主链路真实走通、外围能力有清晰边界，别人拿到仓库后可以按 README 在一台机器上启动整套系统。

## 当前主流程

当前项目已经从旧单线 MVP 进入 **技术标 / 商务标双轨独立化** 阶段。前端仍共用一个工程，但业务入口、页面、API、service、Skill、素材/Wiki 和文档产物都按标类分开：

```text
技术标入口 -> 技术标页面 -> 技术标 API -> 技术标 service -> 技术标 Skill -> 技术标素材/Wiki -> 技术标文档/共创/下载

商务标入口 -> 商务标页面 -> 商务标 API -> 商务标 service -> 商务标 Skill -> 商务标素材/Wiki -> 商务标文档/共创/下载
```

素材库是和 `解析 / 技术标 / 商务标 / 审计 / 设置` 同级的一级准备模块。素材库顶层分 `技术标 / 商务标`，两边都通过各自的 `/api/technical/materials...` 和 `/api/business/materials...` 入口访问；底层共享持久化底座仍在继续收瘦，但不再把旧通用素材接口作为当前业务契约。

技术标项目仍按 `S0-S6` 描述：

```text
S0 解析（审核模块上传招标文件、结构化解析、投标决策）
  -> S1 模板与目录
  -> S2 审核目录
  -> S3 缺口处理
  -> S4 生成标书
  -> S5 共创
  -> S6 导出
```

商务标和技术标当前都按独立工作区推进：解析、目录、素材匹配、共创编辑和审计分别走各自 API；两边主流程都不再把 `/generate`、`/coverage`、`/export` 作为独立前端页面，后半段统一在 `/gaps` 内生成正文、在 `/editor` 内共创和下载。

当前已验证的能力：

- 技术标和商务标都有独立前端入口、workspace 页面和 business/technical API facade
- 旧 `/api/projects...`、`/api/materials...`、`/api/audit...` 不再作为真实业务入口注册
- 技术标 S3 缺口、review、覆盖率、文档格式状态已迁到技术标专属模块
- 商务标 S3 缺口、事实表、AI 草稿、表格填充、素材选择和 repository 边界已迁到商务标专属模块
- 项目、解析、目录、生成、文档、OCR、素材库、Wiki 和审计已有第一层双轨 service 边界
- `store.py` 与 `material_store.py` 继续作为底层持久化底座被收瘦，非持久化工具和双轨业务规则持续迁出

### 权限边界口径

当前内置三类演示角色：安博为 `T` 技术标人员，马哥为 `B` 商务标人员，肖哥为 `TB` 项目经理/标书统筹。前端通过 `permissions.js` 和 `WorkspaceAccess` 实现工作区可见性：`T` 只能进入技术标，`B` 只能进入商务标，`TB` 可在技术标和商务标之间切换，并在工作台看到双流程并列项目。

这不等于生产级权限已经闭环。后端当前有真实登录 token，但 business/technical/settings 路由还没有统一完成 `角色 × workspace × 项目 bidType` 强授权；`/api/settings/...` 目前也只是要求登录，还未限制为 `TB`。生产上线前必须按 [双轨开发协作规范与权限加固计划](./doc/27-双轨开发协作规范与权限加固计划.md) 补齐后端依赖、项目级 scope 和设置页 TB 权限。

## 当前开发推进口径

当前架构和执行计划以这三份文件为准：

- [技术标与商务标双轨独立化实施计划](./doc/31-技术标与商务标双轨独立化实施计划.md)
  - 当前最重要的架构边界和拆分计划
- [doc 目录说明](./doc/README.md)
  - 当前文档入口和历史资料去留口径
- [开发进度](./code/progress.md)
  - 当前已完成拆分、验证命令和下一步

业务需求依据仍保留在 `doc/14`、`doc/15`、`doc/16`，但后续开发不要绕过 `doc/31` 直接按旧待办或旧接口路径实现。每完成或推进一项，同步记录到 [code/progress.md](./code/progress.md)；涉及附表填写、待填写 Word、85% 人工基准验收时，再补读 `doc/16`。

## 目录说明

- `code/`
  - 真正的可运行代码和 `docker-compose.yml`
- `doc/`
  - 规格、部署说明、接口说明、当前待办和归档资料

## 部署架构

当前 compose 默认启动 8 个服务：

- `web`：前端静态页面 + `/api` / `/ds` 反向代理
- `fastapi`：唯一业务后端
- `worker`：Redis 队列消费者，负责目录生成、正文拼装、素材清洗等后台任务
- `opencode`：目录生成、缺口处理和 AI 填写等 Skill 能力的运行入口，同时保留本地 skill 资产
- `onlyoffice`：在线文档预览和编辑
- `postgres`：项目状态、素材库元数据、Wiki 正文、设置和审计日志
- `redis`：后台任务队列、任务锁和结果缓存
- `minio`：上传文件、素材文件、清洗后 Word、Wiki 附件、默认模板和生成文档对象

持久化卷：

- `postgres_data`：项目状态、流程状态、素材库元数据、Wiki、设置和审计
- `redis_data`：后台任务队列持久化
- `minio_data`：素材原文件、清洗后 Word、默认模板、附件和生成文档对象
- `uploads`：用户上传的招标文件和项目模板
- `documents`：生成后的 `.docx`、OnlyOffice 回写文档和项目长期工作区
- `parsed`：`S0` 解析运行期临时缓存

路径口径：

- `parsed/{project_id}/` 只保存 `S0` 运行期临时解析缓存
- `documents/{project_id}/technical-workspace/parse/` 保存进入技术标流程后的解析产物
- `documents/{project_id}/business-workspace/parse/` 保存进入商务标流程后的解析产物
- `documents/{project_id}/technical-workspace/s2_toc_workdir/` 是历史内部目录名，对应当前 `S1 模板与目录` 的目录生成产物
- `documents/{project_id}/technical-workspace/s4_gap_workdir/` 是历史内部目录名，对应当前 `S3 缺口处理` 的缺口计划和补料产物
- `documents/{project_id}/technical-workspace/s7_assembly_workdir/` 是历史内部目录名，对应当前 `S4 生成标书` 的拼装 manifest、计划和报告
- `documents/{project_id}.docx` 是 `S5/S6` 共创和导出的当前项目文档

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

已有本机容器时，如果要确保当前代码重新进入镜像和容器，使用：

```bash
docker compose build --no-cache
docker compose up -d --force-recreate
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

如果修改了 `WEB_PORT`，访问对应端口，例如 `http://localhost:8080`。

## 健康检查

启动后建议先检查：

- `http://localhost/api/healthz`
- `http://localhost/ds/healthcheck`
- `http://localhost:4096/global/health`

如果修改了 `WEB_PORT` 或 `OPENCODE_HOST_PORT`，请同步替换端口。

## 怎么切换模型 URL / key / modelId

### 场景 A：使用 compose 自带 `opencode`

```env
OPENCODE_BASE_URL=http://opencode:4096
OPENCODE_PROVIDER_ID=<你的 providerID>
OPENCODE_MODEL_ID=<你的 modelID>

OPENAI_API_KEY=<如果走 OpenAI / OpenAI-compatible>
ANTHROPIC_API_KEY=<如果走 Anthropic>
GOOGLE_API_KEY=<如果走 Google>
```

### 场景 B：改成外部独立 `opencode` 网关

```env
OPENCODE_BASE_URL=http://your-opencode-host:4096
OPENCODE_PROVIDER_ID=<你的 providerID>
OPENCODE_MODEL_ID=<你的 modelID>
```

这时 FastAPI 会调用外部 `opencode`，compose 里的本地 `opencode` 可以继续保留或手动停掉。

### 场景 C：使用 `auth.json`

```env
OPENCODE_AUTH_HOST_DIR=./opencode-auth
```

认证文件放在 `code/opencode-auth/auth.json`，compose 会挂载进 `opencode` 容器。

## 当前最重要的环境变量

| 变量 | 作用 |
|---|---|
| `WEB_PORT` | 浏览器入口端口 |
| `APP_STORE_BACKEND` | 项目主链路状态存储，部署默认 `postgres` |
| `DATABASE_URL` | FastAPI / worker 访问 PostgreSQL 的连接串 |
| `MINIO_ENDPOINT` | FastAPI / worker 访问 MinIO 的地址 |
| `MINIO_BUCKET_MATERIALS` | 素材库对象 bucket |
| `REDIS_URL` | FastAPI / worker 使用的 Redis 队列地址 |
| `OPENCODE_HOST_PORT` | 本机暴露给调试使用的 opencode 端口 |
| `OPENCODE_BASE_URL` | FastAPI 调用的 opencode 地址 |
| `OPENCODE_PROVIDER_ID` | 调用 opencode 时的 provider |
| `OPENCODE_MODEL_ID` | 调用 opencode 时的模型 ID |
| `OPENCODE_TIMEOUT_SEC` | FastAPI 调用 opencode 的超时，compose 默认 `1800` 秒 |
| `AUTH_ADMIN_EMAIL / AUTH_ADMIN_PASSWORD / AUTH_ADMIN_NAME` | 首次启动时初始化系统管理员 |
| `DEFAULT_LLM_BASE_URL / DEFAULT_LLM_API_KEY / DEFAULT_LLM_MODEL` | 设置页 LLM 模型配置的启动默认值 |
| `DEFAULT_OCR_BASE_URL / DEFAULT_OCR_API_KEY / DEFAULT_OCR_MODEL` | 设置页 PDF/图片识别模型配置的启动默认值 |
| `OPENAI_API_KEY` | OpenAI / OpenAI-compatible 模型 key |
| `ANTHROPIC_API_KEY` | Anthropic key |
| `GOOGLE_API_KEY` | Google key |
| `OPENCODE_AUTH_HOST_DIR` | 宿主机 `auth.json` 挂载目录 |
| `ONLYOFFICE_INTERNAL_URL` | FastAPI 访问 OnlyOffice 的内部地址 |
| `ONLYOFFICE_BACKEND_BASE_URL` | 浏览器与 OnlyOffice 容器都能访问的共享 Web 地址 |
| `ONLYOFFICE_ALLOW_PRIVATE_IP_ADDRESS` | 允许 OnlyOffice 访问内网地址 |

## 推荐验收步骤

部署后建议按这条线验：

1. 登录系统
2. 进入左侧 `素材库`，分别确认 `技术标` 和 `商务标` 原始素材、Wiki、清洗稿预览都走各自工作区入口
3. 进入左侧 `解析` 模块，点击“新建审核项目”
4. 上传一个或多个 `docx/pdf/图片` 招标文件并点击“上传并解析”
5. 在解析/审核模块做投标决策，选择“参与该项目并进入工作区”
6. 补全项目基本信息：确认业务项目编号、负责人、重要客户/普通客户、已有项目/普通项目；技术标项目还要选择投标机型
7. 可选择上传项目模板；不上传时确认系统默认模板可用
8. 在 `S1` 点击“生成目录”，观察 Skill 进度和目录产物
9. 进入 `S2 审核目录`，校核目录，并确认右侧 OnlyOffice 招标文件预览可用
10. 进入 `S3 缺口处理`，先验收缺口识别结果：目录项数量应覆盖 S2 已确认目录，整章 Word 应只挂在父章，待填写素材应进入填写类缺口，缺素材项应保留上传或选择素材入口
11. 在 `S3/S4 素材匹配` 页触发正文拼装，查看生成进度和覆盖诊断提示；素材预览应以弹出层打开
12. 进入 `S5/S6 共创导出` 页，确认 OnlyOffice 或文本兜底正常显示，并可保存、格式设置、下载最终版 Word/PDF

补充说明：

- 审核模块若选择“不参与该项目”，项目会在流程中终止，并从项目总览移除
- `S1` 目录生成优先经 futurecode/opencode 执行 `s2toc` 命令，本地 Skill 脚本作为调用失败时的降级路径
- `S1` 每次目录生成先写入 `s2_toc_workdir.new/`；成功后发布为 `s2_toc_workdir/`，旧成功目录归档到 `s2_toc_workdir.runs/`
- 项目确认后，缺口处理和生成标书默认读取 `技术标/通用素材`、`技术标/客户素材/{客户}`、`技术标/项目素材/{素材项目ID}`，不会把其他客户或其他项目的资料混入搜索范围；技术标还会带上项目已确认的投标机型，用于筛选明显冲突的机型素材和传递给 AI 填写/正文拼装
- 素材 Wiki 重建由 FastAPI 直接执行技术标专用 Skill runner `bid-tech-wiki-material-builder/scripts/run_from_manifest.py`；完整 Wiki 蓝图写入共享 `parsed/_wiki_build/*/wiki_blueprint.json`，stdout 只返回小摘要，后端再读取完整文件导入
- 当前 Wiki 最小结构固定为 `01-素材总表 / 02-章节映射表 / 03-素材卡片 / 04-待填写清单 / 05-使用规则`；素材卡片按通用素材、客户素材、项目素材分层，供 S3 缺口处理、空表填写来源选择和 S4 拼装按需加载
- `S4` 生成标书使用 `bid-tech-assembler`，读取目录 JSON、Wiki 卡片、素材库清洗后 Word、缺口处理计划和补料/AI 填写产物

## OnlyOffice 地址说明

`ONLYOFFICE_BACKEND_BASE_URL` 必须同时满足：

- 浏览器能访问
- `onlyoffice` 容器也能访问

推荐口径：

- 单机本地 compose：可以留空，FastAPI 会优先自动探测当前机器的局域网 IP
- 多机 / 服务器部署：显式填写可访问域名或服务器 IP，例如 `https://bid-mvp.example.com` 或 `http://192.168.31.148`

不推荐直接写：

- `http://fastapi:8000`：通常只对 Docker 内部容器可达，浏览器不可达
- `http://127.0.0.1`：通常只对宿主机浏览器可达，`onlyoffice` 容器不可达

## 已知边界

- 当前已接入 PostgreSQL、MinIO、Redis、真实登录鉴权、持久化审计、系统设置、默认模板管理和 PDF/图片型文件无感解析；SSO 尚未接入，后端生产级角色授权仍是待加固项
- 覆盖诊断当前校验的是正文拼装计划与素材库的覆盖关系，不是完整评分点覆盖审计
- `S5/S6` 的 Word/PDF 下载入口已经收进 `/editor`；评分点级覆盖审计、证据链一致性和完整格式验收仍是后续专项
- 设置侧系统默认模板是项目未上传模板时的生成输入，不会混入项目上传模板列表
- 原始素材库页面采用 `技术标 / 商务标` 顶层切换；技术标与商务标都按各自 workspace API 访问原始素材、Wiki、附件、清洗稿预览和下载

## GitHub 协作提交

不要直接在 `main` 分支开发或直接 push 到 `main`。推荐流程：

```bash
git switch main
git pull --ff-only origin main
git switch -c feat/your-change
cd code/sewpg-bid-frontend
npm run build
git add .
git commit -m "feat: describe your change"
git push -u origin feat/your-change
```

到 GitHub 页面发起 Pull Request，Base 选 `main` 或团队指定集成分支。
