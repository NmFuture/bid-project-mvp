# 项目执行说明

> 这份文件给后续参与这个项目的开发同学和智能体使用。
> 当前目标：**在已跑通 Docker Compose MVP 的基础上，按甲方新增需求待办逐项推进。**

## 0. 当前推进规则

从 2026-05-01 起，下一阶段工作以这两份文档为准：

- `/Users/wlb/Agent/bid-project/doc/14-甲方新增需求待办.md`
  - 当前统一待办池
  - 按实施难度升序排列
  - 每条待办都有“完成情况”
- `/Users/wlb/Agent/bid-project/doc/15-技术标与商务标需求整理.md`
  - 技术标、商务标需求来源和讨论依据

执行规则：

- 按 `doc/14-甲方新增需求待办.md` 的待办清单推进。
- 完成一项后，把对应行的“完成情况”从 `[ ]` 改为 `[x]`。
- 每完成或推进一项，同步在 `/Users/wlb/Agent/bid-project/code/progress.md` 写进度记录。
- 每完成一项待办后，必须重新部署相关服务给用户检查；涉及前端展示的改动至少执行 `docker compose build web && docker compose up -d web`，不要只启动 Vite 开发服务替代正式入口部署。
- 每完成一项待办后，同步创建一次 git commit，提交前确认工作树只包含本项相关改动。
- 用户准备开始做待办清单上的事情，并且每次会尽量开新会话；新会话默认只处理一个待办。
- 新会话开工时先读 `doc/14-甲方新增需求待办.md`、`code/progress.md` 和本文件，再看具体代码。
- 用户明确说“先更新待办文档，不需要直接做”时，只改文档，不实现功能。

当前重要口径：

- `http://127.0.0.1/parse` 解析页面后续要支持多个招标文件，并触发专门解析 Skill；这不是旧 S1 步骤的简单字段补充。
- S7 里原先的 Agent 决策素材匹配，应前移到“缺口识别与处理”步骤中统一处理。
- 新工作流方向是收敛目录生成、缺口处理和校验，而不是继续扩展旧的独立 S2/S4/S5/S6/S7/S8 页面边界。

## 1. 当前结论

当前 `code` 目录的拆分是合理的，建议就按下面这套结构继续推进，不再来回改目录名：

```text
code/
  docker-compose.yml
  .env.example
  AGENT.md
  plan.md
  sewpg-bid-api/
  sewpg-bid-frontend/
  sewpg-bid-backend/
```

推荐理解：

- `sewpg-bid-frontend`
  - React + Vite 前端
  - 保留现有 `S0-S10` 展示流
- `sewpg-bid-backend`
  - 正式 FastAPI 后端
  - 后端内部再包含 `opencode` 和 `onlyoffice` 相关实现与参考资产
- `sewpg-bid-api`
  - API 契约与接口文档目录
  - 用来承接 Apifox/OAS/接口说明，不放运行时代码

一句话：

> **前端、后端、API 三层拆分是对的；`opencode` 和 `onlyoffice` 放在后端下面也合理。**

## 2. 目录职责

### 2.1 `sewpg-bid-frontend`

这是当前唯一前端工程。

职责：

- 页面、路由、阶段展示
- 调用统一 `/api`
- S9 页面挂载 OnlyOffice 编辑器
- 保留 `S0-S10` 完整展示流

当前注意：

- 前端当前只保留正式 FastAPI 联调路径
- 旧 `fastapi-mock / mock-server / smoke` 资产已从当前运行路径中移除
- 后续不要再恢复双后端或旧 mock 网关思路

### 2.2 `sewpg-bid-backend`

这是当前唯一后端工程。

职责：

- FastAPI 业务入口
- 项目、阶段、文件、解析、目录生成、正文拼装
- 对接 `opencode serve`
- 对接 OnlyOffice 文档会话和回调
- 为非 MVP 阶段返回 mock 数据

内部建议按下面理解：

```text
sewpg-bid-backend/
  app/           # 正式 FastAPI 代码
  opencode/      # opencode 镜像、配置与 skill 资产
  onlyoffice/    # OnlyOffice Document Server entrypoint
```

### 2.3 `sewpg-bid-api`

这是接口契约目录，不是运行时服务目录。

职责：

- 存放 MVP 正式 API 文档
- 存放 OpenAPI / Apifox 导出文件
- 作为前后端对齐基线

不建议往这里放：

- FastAPI 代码
- 前端代码
- 历史 mock / demo 脚本

## 3. 当前 MVP 口径

### 3.1 页面展示流

前端仍保留完整展示流：

```text
S0 -> S1 -> S2 -> S3 -> S4 -> S5 -> S6 -> S7 -> S8 -> S9 -> S10
```

### 3.2 当前真实阶段

现在真正要做成真实能力的是：

- `S0`：项目列表 / 新建项目
- `S1`：解析招标文件
- `S2`：FastAPI 调 futurecode/opencode 执行 `bid-tech-outline-generator` 的 `s2toc` 命令生成目录；futurecode/opencode 不可用时，本地运行同一 Skill 脚本降级生成
- `S3`：审核目录
- `S7`：调用 `bid-tech-assembler`，按 S2 目录 JSON 和素材库拼装正文
- `S8`：基于拼装计划校验未拼上的素材和未匹配目录项
- `S9`：OnlyOffice 共创编辑
- `S10`：下载最新版 Word

### 3.3 当前先 mock 的阶段

- `S4`
- `S5`
- `S6`

原则：

> **前端展示完整，后端实现收敛。**

## 4. 成品语义与当前实现的区别

正式版产品语义不变：

- `S5`：补料入库
- `S7`：从素材库拼接成稿

当前 MVP 已经把 `S7` 调整为正文拼装，接口名仍沿用 `/fill-generation` 以兼容现有前端。

所以必须记住：

> **当前 MVP 的 S7 已回到正式产品语义：按目录从素材库拼接成稿。**

## 5. 前后端边界

### 5.1 前端只做什么

- 调用 `/api`
- 展示状态
- 收集输入
- 挂载 OnlyOffice 编辑器

### 5.2 前端不做什么

- 不直接调 `opencode`
- 不直接处理 OnlyOffice callback
- 不自己拼 docx

### 5.3 后端做什么

- FastAPI 统一承接所有 `/api`
- 调 futurecode/opencode 执行 `s2toc` 生成 S2 目录，并在调用失败时本地运行同一 Skill 脚本
- 调本地 `bid-tech-assembler` skill 生成正文 docx
- 管项目状态
- 提供 OnlyOffice `config/meta/download/callback`
- 为非 MVP 阶段返回 mock 数据

### 5.4 S2 工作目录约定

- 最新成功 S2 产物固定在 `{DOCUMENTS_DIR}/{project_id}/technical-workspace/s2_toc_workdir/`。
- 新一轮先写 `{DOCUMENTS_DIR}/{project_id}/technical-workspace/s2_toc_workdir.new/`，成功后再发布，避免失败时破坏上一轮成功目录。
- 旧成功目录归档到 `{DOCUMENTS_DIR}/{project_id}/technical-workspace/s2_toc_workdir.runs/`。
- 不再写 `{PARSED_DIR}/{project_id}/s2.json` alias；`manifestPath` 与 `canonicalManifestPath` 都应指向 `s2_toc_workdir/s2_input.json`。

## 6. 本机运行目标

当前目标不是旧的多入口联调，而是：

```text
docker compose up
```

直接拉起：

- `web`
- `fastapi`
- `worker`
- `opencode`
- `onlyoffice`
- `postgres`
- `redis`
- `minio`

再配合数据卷：

- `postgres_data`
- `redis_data`
- `minio_data`
- `uploads`
- `documents`
- `parsed`

## 7. 当前代码里的已知错位

当前有几个地方必须按这个文件口径理解：

1. `code/docker-compose.yml`
   - 现在应该以 `sewpg-bid-backend` 为后端上下文
   - 不再使用旧的 `./backend` 目录名

2. `sewpg-bid-backend/onlyoffice`
   - 当前是接入参考与验证资产
   - 后续要把真实能力并入 `app/` 的正式业务路由

## 8. 开发原则

### 8.1 单一后端原则

前端最终只认一个后端：

> **FastAPI**

不能长期保留：

- 一部分接口走 FastAPI
- 一部分接口走第二套网关或历史 mock 服务

### 8.2 契约优先

所有真实实现都以这些文件为准：

- `/Users/wlb/Agent/bid-project/doc/05-MVP主链路说明.md`
- `/Users/wlb/Agent/bid-project/doc/06-MVP接口文档.md`
- `/Users/wlb/Agent/bid-project/doc/08-MVP部署说明.md`
- `/Users/wlb/Agent/bid-project/doc/11-内网离线部署说明.md`
- `/Users/wlb/Agent/bid-project/doc/12-数据存储与素材库数据说明.md`
- `/Users/wlb/Agent/bid-project/doc/13-S7技术标正文拼装与S8素材校验说明.md`
- `/Users/wlb/Agent/bid-project/doc/14-甲方新增需求待办.md`
- `/Users/wlb/Agent/bid-project/doc/15-技术标与商务标需求整理.md`

### 8.3 优先打通闭环

真正的关键链路是：

```text
frontend -> FastAPI -> opencode/skill -> docx -> OnlyOffice -> callback -> download
```

不要被非关键模块分散精力。

## 9. 当前最重要的落地顺序

旧 MVP 联调顺序已经基本完成，后续不要继续按本节旧序列扩功能。当前落地顺序改为：

1. 从 `/Users/wlb/Agent/bid-project/doc/14-甲方新增需求待办.md` 的序号 1 开始推进。
2. 每开始一项前，先确认它与当前代码、页面和接口的真实状态。
3. 完成后勾选待办，并写入 `/Users/wlb/Agent/bid-project/code/progress.md`。

## 10. 一句话总结

> **当前项目就按“前端、后端、API”三层推进；后端统一收 `opencode` 和 `onlyoffice`；已跑通的 MVP 继续保持，下一阶段按 `doc/14-甲方新增需求待办.md` 逐项收口。**

## 11. Git 分支约定

当前仓库按下面这套分支语义协作：

- `main`
  - 生产版本
  - 只保留已经验证稳定、可以作为正式版本使用的内容
- `Dev`
  - 测试版本
  - 仓库里当前实际测试分支名是大写 `Dev`，后续提到 `dev` 时都按这个分支理解
- `wlb`
  - 王立博个人开发分支
  - 日常开发默认在这个分支进行

协作规则：

- 平时开发先在 `wlb` 上完成
- 每次阶段性提交先进入 `Dev`，不要直接提交到 `main`
- `main` 只接收已经在 `Dev` 验证通过的稳定内容

一句话：

> **`main` 是生产，`Dev` 是测试，`wlb` 是个人开发；开发先落在 `wlb`，再并入 `Dev`。**
