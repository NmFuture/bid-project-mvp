# Bid Project MVP

这是一个已经收口到 **Docker Compose 可部署形态** 的标书智能体 MVP 仓库。当前目标不是把所有远期业务一次性做完，而是让主链路真实走通、外围能力有清晰边界，别人拿到仓库后可以按 README 在一台机器上启动整套系统。

## 当前主流程

素材库现在是和 `解析 / 技术标 / 商务标 / 审计 / 设置` 同级的一级准备模块。素材库顶层先分 `技术标 / 商务标`；当前只启用技术标，技术标下再分 `通用素材 / 客户素材 / 项目素材` 三档，商务标先保留为空。进入解析和项目流程前，先维护技术标素材和技术标 Wiki；确认参与投标并补全项目时，系统会绑定本项目可读取的客户素材与项目素材范围。

参与项目后的“完善项目信息”页面当前采用业务口径：`客户来源` 显示为 `重要客户 / 普通客户`，`项目来源` 显示为 `已有项目 / 普通项目`。技术标项目必须选择 `投标机型`；候选机型由素材库中的投标机型参数表动态解析，页面以下拉菜单展示，选中后显示机型参数，并把该机型作为项目结构化字段延续到 `S3 缺口处理` 和 `S4 生成标书`。

当前技术标流程统一为 `S0-S6`：

```text
S0 解析（审核模块上传招标文件、结构化解析、投标决策）
  -> S1 模板与目录
  -> S2 审核目录
  -> S3 缺口处理
  -> S4 生成标书
  -> S5 共创
  -> S6 导出
```

其中 `S0` 是进入项目模块前的解析和投标决策步骤；项目模块只展示 `S1-S6` 六个节点。旧的 `S7/S8/S9/S10` 公共阶段号不再作为当前基线使用，后端只保留对旧阶段请求的兼容映射。

当前已验证的能力：

- `S0` 支持多招标文件解析、PDF/图片型文件无感识别、投标决策和项目信息补全
- `S1` 使用项目上传模板，或在项目未上传模板时使用设置侧启用的系统默认模板；同页触发目录生成
- `S2` 审核并确认目录，右侧可预览招标文件
- `S3` 读取真实目录、Wiki、素材库、补料和 AI 填写产物，形成缺口处理计划
- `S4` 调用 `bid-tech-assembler` 拼装技术标正文，并保留覆盖诊断能力
- `S5` 通过 OnlyOffice 共创编辑项目正文
- `S6` 下载最终 Word；格式检查、PDF 导出和评分点级覆盖审计仍是后续专项

## 当前开发推进口径

下一阶段开发以这两份文档为准：

- [甲方新增需求待办](./doc/14-甲方新增需求待办.md)
  - 当前统一待办池，按实施难度升序排列，并带有“完成情况”列
- [技术标与商务标需求整理](./doc/15-技术标与商务标需求整理.md)
  - 技术标、商务标需求来源和讨论依据

推进规则：

- 每完成一项待办，在 `doc/14-甲方新增需求待办.md` 的“完成情况”列勾选
- 每完成或推进一项，同步记录到 [code/progress.md](./code/progress.md)
- 后续做待办时，默认每个待办开一个新会话；新会话先读 `doc/14`、`code/progress.md` 和 `code/AGENT.md`

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
2. 进入左侧 `素材库`，确认 `技术标` 原始素材可展开、已生成技术标 Wiki，`商务标` 当前为空状态
3. 进入左侧 `解析` 模块，点击“新建审核项目”
4. 上传一个或多个 `docx/pdf/图片` 招标文件并点击“上传并解析”
5. 在解析/审核模块做投标决策，选择“参与该项目并进入工作区”
6. 补全项目基本信息：确认业务项目编号、负责人、重要客户/普通客户、已有项目/普通项目，并为技术标选择投标机型
7. 可选择上传项目模板；不上传时确认系统默认模板可用
8. 在 `S1` 点击“生成目录”，观察 Skill 进度和目录产物
9. 进入 `S2 审核目录`，校核目录，并确认右侧 OnlyOffice 招标文件预览可用
10. 进入 `S3 缺口处理`，识别缺口、补料、AI 填写并确认缺口计划
11. 进入 `S4 生成标书`，触发正文拼装并查看覆盖诊断
12. 进入 `S5 共创`，确认 OnlyOffice 编辑器正常显示
13. 进入 `S6 导出`，下载最终版 Word

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

- 当前已接入 PostgreSQL、MinIO、Redis、真实登录鉴权、持久化审计、系统设置、默认模板管理和 PDF/图片型文件无感解析；SSO 尚未接入
- 覆盖诊断当前校验的是正文拼装计划与素材库的覆盖关系，不是完整评分点覆盖审计
- `S6` 当前主要支持最终 Word 下载；导出前格式刷新、PDF 导出和一致性检查仍在后续待办中
- 设置侧系统默认模板是项目未上传模板时的生成输入，不会混入项目上传模板列表
- 原始素材库页面采用 `技术标 / 商务标` 顶层切换；当前技术标内按通用素材、客户素材、项目素材三档展示，左侧支持 Finder 列表式展开到文件，点击已清洗文件后在右侧 OnlyOffice 区域预览清洗稿；商务标先保留为空

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
