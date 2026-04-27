# MVP 正式 API 文档

> 用途：作为当前 MVP 阶段 `Web 前端 -> FastAPI` 的正式接口基线。  
> 说明：本文件定义的是前端要调用的业务接口，不是 `FastAPI -> opencode` 的内部调用接口。

## 1. 范围说明

当前 MVP 保留前端完整展示流 `S0-S10`，但只把关键阶段做成真实能力：

- 真实阶段：`S0`、`S1`、`S2`、`S3`、`S7`、`S8`、`S9`、`S10`
- Mock / 承接阶段：`S4`、`S5`、`S6`

补充说明：

- `S0` 当前只覆盖项目列表 / 新建项目
- 登录鉴权本轮先不纳入 MVP，可先保留空实现或 mock

关键边界：

- `S2`：调用 `opencode` 的目录生成 skill
- `S7`：调用本地 `bid-tech-assembler` skill，按 S2 目录 JSON 和素材库拼装正文
- `S8`：读取 S7 拼装计划，校验未拼上的素材和未匹配目录项
- `S9`：由 FastAPI 对接 OnlyOffice
- `S10`：下载最终 Word

## 2. 设计原则

- 前端只调用 FastAPI，不直接调用 `opencode`
- FastAPI 是唯一 `/api` 后端，同时承担真实执行和 mock 返回
- `S2` 由 FastAPI 内部调用 `opencode serve`
- `S7` 由 FastAPI/worker 调用 `opencode/skill/bid-tech-assembler` 下的本地 Python 拼装脚本
- 项目列表和项目状态需要持久化，MVP 统一使用 `PostgreSQL + 本地文件目录`
- 当前前端展示流保留 `S0-S10`，接口优先兼容现有 React 前端

## 3. 正式接口范围

## 3.1 项目与阶段

### `GET /api/projects`

- 用途：项目列表
- 是否真实：真实

### `POST /api/projects`

- 用途：创建项目并上传招标文件
- 是否真实：真实
- 请求类型：`multipart/form-data`

最少字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | string | 项目名称 |
| `customerName` | string | 客户名称 |
| `manager` | string | 负责人 |
| `bidType` | string | 标书类型 |
| `deadline` | string | 截止日期 |
| `bidFiles` | file[] | 招标文件 |

说明：

- 当前前端 `ProjectWizardModal` 还只传文件名，后续要补成真实文件上传
- 如果不传真实文件，`S1` 无法做真实解析

### `GET /api/projects/{id}`

- 用途：项目详情
- 是否真实：真实

### `PUT /api/projects/{id}`

- 用途：更新项目基础信息
- 是否真实：可先做轻量真实

### `DELETE /api/projects/{id}`

- 用途：删除项目
- 是否真实：真实

### `GET /api/projects/{id}/stages`

- 用途：获取阶段条
- 是否真实：真实

### `PUT /api/projects/{id}/stages/{stage}`

- 用途：阶段状态更新
- 是否真实：真实

说明：

- 主链路阶段由后端状态驱动
- `S4/S5/S6` 虽然是 mock / 承接，但仍需要这个接口配合前端流转；`S8` 已接到 S7 拼装覆盖结果

## 3.2 S1 解析

### `GET /api/projects/{id}/parse-results`

- 用途：获取解析结果
- 是否真实：真实

### `POST /api/projects/{id}/parse-results/run`

- 用途：触发解析
- 是否真实：真实

### `PUT /api/projects/{id}/parse-results/{rid}`

- 用途：更新解析结果项
- 是否真实：可先保留空实现或轻量实现

## 3.3 S2 目录生成

### `GET /api/projects/{id}/directory-generation`

- 用途：获取目录生成状态
- 是否真实：真实

### `POST /api/projects/{id}/directory-generation/run`

- 用途：触发目录生成
- 是否真实：真实

说明：

- FastAPI 内部调用 `opencode` 目录生成 skill

## 3.4 S3 目录审核

### `GET /api/projects/{id}/outline`

- 用途：获取目录草案
- 是否真实：真实

### `PUT /api/projects/{id}/outline`

- 用途：保存审核后的目录
- 是否真实：真实

### `POST /api/projects/{id}/outline/regenerate`

- 用途：重新生成目录
- 是否真实：真实

### `POST /api/projects/{id}/outline/confirm`

- 用途：确认目录，进入后续流程
- 是否真实：真实

## 3.5 S7 技术标正文拼装

### `GET /api/projects/{id}/fill-generation`

- 用途：获取正文拼装状态
- 是否真实：真实

### `POST /api/projects/{id}/fill-generation/run`

- 用途：触发正文拼装
- 是否真实：真实

说明：

- 当前仍兼容前端原有 `fill-generation` 接口名。
- 后端会读取 S2 目录 JSON、S2 Wiki 卡片和素材库清洗后 Word，调用 `bid-tech-assembler` 生成正文 docx。
- S7 输出会写入项目文档路径，供 S9 OnlyOffice 和 S10 下载继续使用。

## 3.6 S8 素材拼装覆盖校验

### `GET /api/projects/{id}/coverage`

- 用途：查看 S7 拼装后素材覆盖情况
- 是否真实：真实

说明：

- `fullCover` 表示已被拼装计划使用的素材数量。
- `noCover` 表示素材库中可用但未出现在 S2 目录 JSON 或拼装计划中的素材数量。
- `partialItems` 表示 S2 目录项中未匹配素材或需要人工确认的项。
- 当前 S8 是素材拼装覆盖校验，不等同于正式评分点覆盖审计。

## 3.7 S9 共创编辑

### `GET /api/projects/{id}/document`

- 用途：获取 OnlyOffice 配置和文档信息
- 是否真实：真实

### `PUT /api/projects/{id}/document/save`

- 用途：手动保存文档
- 是否真实：真实

### `POST /api/projects/{id}/document/force-save`

- 用途：触发强制保存
- 是否真实：真实

### `POST /api/projects/{id}/document/callback`

- 用途：接收 OnlyOffice 回调
- 是否真实：真实

## 3.8 S10 导出

### `GET /api/projects/{id}/final-document`

- 用途：获取最终 Word 下载信息
- 是否真实：真实

### `GET /api/projects/{id}/export/check`

- 用途：导出前检查
- 是否真实：可先 mock

### `POST /api/projects/{id}/export`

- 用途：导出动作
- 是否真实：可先做轻量真实，或直接复用最终文档下载

## 4. 当前先 mock 的接口

下面这些接口当前由 FastAPI 返回固定结构即可：

- `/api/projects/{id}/cockpit`
- `/api/customers/key-accounts`
- `/api/projects/{id}/gaps-detection*`
- `/api/projects/{id}/gaps*`
- `/api/projects/{id}/review-items*`
- `/api/materials/raw/*`
- `/api/materials/structured/*`
- `/api/materials/wiki/*`
- `/api/audit/*`
- `/api/settings/*`

要求只有一个：

> **返回结构与现有前端预期一致，保证页面不报错。**

## 5. 一句话总结

> **当前正式 API 文档服务于“现有前端 + FastAPI 统一承接”的 MVP 落地；前端接口保持兼容，真正的业务能力由 FastAPI 内部再去调用 `opencode` 和 OnlyOffice。**
