# 项目执行说明

> 这份文件给后续参与这个项目的开发同学和智能体使用。  
> 目标只有一个：**在 `code` 目录下完成前后端联调，并能通过 Docker Compose 在本机跑通 MVP。**

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
  opencode/      # opencode skill / 调用参考 / demo
  onlyoffice/    # OnlyOffice 接入参考 / demo 资产
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
- demo 脚本

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
- `S2`：调用 `opencode skill` 生成目录
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
- 调 `opencode serve` 生成目录
- 调本地 `bid-tech-assembler` skill 生成正文 docx
- 管项目状态
- 提供 OnlyOffice `config/meta/download/callback`
- 为非 MVP 阶段返回 mock 数据

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
- `/Users/wlb/Agent/bid-project/doc/07-FastAPI承接与前端改造.md`
- `/Users/wlb/Agent/bid-project/doc/08-MVP部署说明.md`

### 8.3 优先打通闭环

真正的关键链路是：

```text
frontend -> FastAPI -> opencode/skill -> docx -> OnlyOffice -> callback -> download
```

不要被非关键模块分散精力。

## 9. 当前最重要的落地顺序

1. 把 `docker-compose.yml` 和真实目录对齐
2. 确定 `sewpg-bid-backend/app` 是唯一正式后端入口
3. 把 `S0/S1/S2/S3/S7/S8/S9/S10` 接成真链路
4. 把 `S8` 接到 S7 拼装计划和素材覆盖结果
5. 把 `S4/S5/S6` 改成 FastAPI mock / 承接
6. 最后继续收口文档与部署说明，保持“正式 FastAPI 单入口”口径一致

## 10. 一句话总结

> **当前项目就按“前端、后端、API”三层推进；后端统一收 `opencode` 和 `onlyoffice`；目标是在 `code` 目录下通过 Docker Compose 跑通 MVP 前后端联调。**

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
