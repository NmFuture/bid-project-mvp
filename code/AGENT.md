# 项目执行说明

> 这份文件给后续参与这个项目的开发同学和智能体使用。
> 当前目标：在已跑通 Docker Compose MVP 的基础上，按甲方新增需求待办逐项推进，并保持 `S0-S6` 阶段口径一致。

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
- 每完成一项待办后，必须重新部署相关服务给用户检查；涉及前端展示的改动至少执行 `docker compose build web && docker compose up -d web`。
- 每完成一项待办后，同步创建一次 git commit，提交前确认工作树只包含本项相关改动。
- 新会话开工时先读 `doc/14-甲方新增需求待办.md`、`code/progress.md` 和本文件，再看具体代码。
- 用户明确说“先更新待办文档，不需要直接做”时，只改文档，不实现功能。

当前重要口径：

- `素材库` 是一级准备模块，和 `解析 / 技术标 / 商务标 / 审计 / 设置` 同级；不要再把它解释成某个标类工作区内部的附属页面。
- 项目在 `S0` 确认参与并补全信息时，会绑定素材读取范围：`通用素材/{标书类型}`、`客户素材/{客户}/{标书类型}`、`项目素材/{素材项目ID}/{标书类型}`。
- `S3 缺口处理` 与 `S4 生成标书` 的素材搜索和 Agent 输入应按上述项目范围读取，避免跨客户、跨项目误用素材。
- 技术标流程统一为 `S0-S6`：`S0 解析 -> S1 模板与目录 -> S2 审核目录 -> S3 缺口处理 -> S4 生成标书 -> S5 共创 -> S6 导出`。
- `S0` 属于全局 `解析` / `审核` 模块，负责上传招标文件、结构化解析、投标决策和补全项目信息。
- 项目模块进度条只展示 `S1-S6` 六个节点。
- 项目内历史 URL `/projects/:id/parse` 仅作为兼容跳转；当前 `S1 模板与目录` 的正式 URL 是 `/projects/:id/template-directory`。
- 旧阶段号 `S7/S8/S9/S10` 不再作为当前产品或接口基线；只在历史内部目录名和 legacy 请求映射中保留。
- 旧的 Agent 决策素材匹配已经前移到 `S3 缺口处理`，不要再恢复为独立生成后步骤。

## 1. 当前目录结构

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
  - 展示全局 `S0` 解析模块和项目内 `S1-S6` 流程
- `sewpg-bid-backend`
  - 正式 FastAPI 后端
  - 后端内部包含 `opencode` 和 `onlyoffice` 相关实现与运行资产
- `sewpg-bid-api`
  - API 契约与接口文档目录
  - 用来承接 Apifox/OAS/接口说明，不放运行时代码

一句话：

> **前端、后端、API 三层拆分保持不变；阶段口径统一改为 S0-S6。**

## 2. 目录职责

### 2.1 `sewpg-bid-frontend`

职责：

- 页面、路由、阶段展示
- 调用统一 `/api`
- 全局 `解析` 模块承接 `S0`
- 项目模块展示 `S1-S6`
- `S5` 页面挂载 OnlyOffice 编辑器

当前注意：

- 前端当前只保留正式 FastAPI 联调路径
- 旧 `fastapi-mock / mock-server / smoke` 资产已从当前运行路径中移除
- 后续不要再恢复双后端或旧 mock 网关思路

### 2.2 `sewpg-bid-backend`

职责：

- FastAPI 业务入口
- 项目、阶段、文件、解析、目录生成、缺口处理、正文拼装、覆盖诊断、导出
- 对接 `opencode serve`
- 对接 OnlyOffice 文档会话和回调
- 为未完成的后续专项返回明确 MVP 结果或错误

内部结构：

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

### 3.1 阶段流

```text
S0 解析
  -> S1 模板与目录
  -> S2 审核目录
  -> S3 缺口处理
  -> S4 生成标书
  -> S5 共创
  -> S6 导出
```

当前真实能力：

- `S0`：多招标文件上传、结构化解析、PDF/图片型文件无感识别、投标决策、项目信息补全
- `S1`：项目模板上传或设置侧系统默认模板读取；调用 futurecode/opencode 执行 `bid-tech-outline-generator` 的 `s2toc` 命令生成目录；失败时本地运行同一 Skill 脚本降级
- `S2`：审核并确认目录
- `S3`：缺口识别、补料、AI 填写、OnlyOffice 预览、完整性校验和缺口计划确认
- `S4`：调用 `bid-tech-assembler`，按目录 JSON、缺口计划、Wiki 和素材库拼装正文，并生成覆盖诊断
- `S5`：OnlyOffice 共创编辑
- `S6`：下载最新版 Word，导出前格式检查和 PDF 能力继续按待办推进

### 3.2 历史内部路径命名

下面这些目录名是历史实现名，不再代表当前用户阶段号：

- `s1_parse_manifest.json`：`S0 解析` Skill manifest 的历史文件名
- `s2_toc_workdir/`：`S1 模板与目录` 的目录生成工作区
- `s4_gap_workdir/`：`S3 缺口处理` 的工作区
- `s7_assembly_workdir/`：`S4 生成标书` 的正文拼装工作区
- `s7_assembly_input.json`：`S4 生成标书` 调用 `bid-tech-assembler` 的历史 manifest 文件名

可以保留这些文件名以兼容脚本和已有产物，但对外说明一律使用 `S0-S6`。

## 4. 前后端边界

### 4.1 前端只做什么

- 调用 `/api`
- 展示状态
- 收集输入
- 挂载 OnlyOffice 编辑器

### 4.2 前端不做什么

- 不直接调 `opencode`
- 不直接处理 OnlyOffice callback
- 不自己拼 docx

### 4.3 后端做什么

- FastAPI 统一承接所有 `/api`
- 调 futurecode/opencode 执行 `s2toc` 生成目录，并在调用失败时本地运行同一 Skill 脚本
- 调缺口识别和 AI 填写 Skill
- 调 futurecode/opencode 执行 `wikibuild` 生成素材 Wiki 蓝图，完整结果由脚本写入共享 `parsed/_wiki_build/*/wiki_blueprint.json` 后再由后端导入
- 调本地 `bid-tech-assembler` skill 生成正文 docx
- 管项目状态、设置、审计和素材库
- 提供 OnlyOffice `config/meta/download/callback`

## 5. 工作目录约定

- 最新成功目录产物固定在 `{DOCUMENTS_DIR}/{project_id}/technical-workspace/s2_toc_workdir/`。
- 新一轮目录生成先写 `{DOCUMENTS_DIR}/{project_id}/technical-workspace/s2_toc_workdir.new/`，成功后再发布。
- 旧成功目录归档到 `{DOCUMENTS_DIR}/{project_id}/technical-workspace/s2_toc_workdir.runs/`。
- 素材 Wiki 重建 manifest 和完整蓝图位于 `{PARSED_DIR}/_wiki_build/bid-wiki-build-*/`，这是 `fastapi` 与 `opencode` 共享的运行期工作区。
- 缺口处理产物位于 `{DOCUMENTS_DIR}/{project_id}/technical-workspace/s4_gap_workdir/`。
- 生成标书产物位于 `{DOCUMENTS_DIR}/{project_id}/technical-workspace/s7_assembly_workdir/`。
- 当前可编辑文档固定为 `{DOCUMENTS_DIR}/{project_id}.docx`。
- 不再写 `{PARSED_DIR}/{project_id}/s2.json` alias；`manifestPath` 与 `canonicalManifestPath` 都指向 `s2_toc_workdir/s2_input.json`。

## 6. 本机运行目标

当前目标是：

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

配合数据卷：

- `postgres_data`
- `redis_data`
- `minio_data`
- `uploads`
- `documents`
- `parsed`

## 7. 开发原则

### 7.1 单一后端原则

前端最终只认一个后端：

> **FastAPI**

不能长期保留：

- 一部分接口走 FastAPI
- 一部分接口走第二套网关或历史 mock 服务

### 7.2 契约优先

所有真实实现都以这些文件为准：

- `/Users/wlb/Agent/bid-project/README.md`
- `/Users/wlb/Agent/bid-project/doc/05-MVP主链路说明.md`
- `/Users/wlb/Agent/bid-project/doc/06-MVP接口文档.md`
- `/Users/wlb/Agent/bid-project/doc/08-MVP部署说明.md`
- `/Users/wlb/Agent/bid-project/doc/11-内网离线部署说明.md`
- `/Users/wlb/Agent/bid-project/doc/12-数据存储与素材库数据说明.md`
- `/Users/wlb/Agent/bid-project/doc/13-S4生成标书与覆盖诊断说明.md`
- `/Users/wlb/Agent/bid-project/doc/14-甲方新增需求待办.md`
- `/Users/wlb/Agent/bid-project/doc/15-技术标与商务标需求整理.md`

### 7.3 优先打通闭环

真正的关键链路是：

```text
frontend -> FastAPI -> opencode/skill -> docx -> OnlyOffice -> callback -> download
```

不要被非关键模块分散精力。

## 8. 当前最重要的落地顺序

旧 MVP 联调顺序已经基本完成，后续不要按旧十段阶段序列扩功能。当前落地顺序：

1. 从 `/Users/wlb/Agent/bid-project/doc/14-甲方新增需求待办.md` 的未完成项开始推进。
2. 每开始一项前，先确认它与当前代码、页面和接口的真实状态。
3. 完成后勾选待办，并写入 `/Users/wlb/Agent/bid-project/code/progress.md`。

## 9. Git 分支约定

当前仓库按下面这套分支语义协作：

- `main`
  - 生产版本，只保留已经验证稳定、可以作为正式版本使用的内容
- `Dev`
  - 测试版本；仓库里当前实际测试分支名是大写 `Dev`
- `wlb`
  - 王立博个人开发分支；日常开发默认在这个分支进行

协作规则：

- 平时开发先在 `wlb` 上完成
- 每次阶段性提交先进入 `Dev`，不要直接提交到 `main`
- `main` 只接收已经在 `Dev` 验证通过的稳定内容

一句话：

> **`main` 是生产，`Dev` 是测试，`wlb` 是个人开发；开发先落在 `wlb`，再并入 `Dev`。**
