# MVP 正式 API 文档

> 用途：作为当前 MVP 阶段 `Web 前端 -> FastAPI` 的正式接口基线。
> 说明：本文件定义的是前端要调用的业务接口，不是 `FastAPI -> opencode` 的内部调用接口。
> 更新日期：2026-05-03

## 1. 范围说明

当前主流程统一为：

```text
S0 解析 -> S1 模板与目录 -> S2 审核目录 -> S3 缺口处理 -> S4 生成标书 -> S5 共创 -> S6 导出
```

接口兼容说明：

- `/api/projects/{id}/stages` 只返回项目模块 `S1-S6` 六个节点。
- `S0` 是全局解析/审核模块，不出现在项目阶段条中。
- `directory-generation`、`gaps`、`review-items`、`fill-generation`、`coverage` 等接口名保留，是为了兼容当前代码和历史客户端；它们不再代表旧 `S2/S4/S5/S6/S7/S8` 独立用户阶段。
- `PUT /api/projects/{id}/stages/{stage}` 接受旧阶段号作为 legacy 请求兼容，但返回和持久化会折叠到当前 `S1-S6`。

补充说明：

- 登录鉴权已真实化：`/api/auth/login` 校验系统用户密码并签发服务端会话 token，`/api/auth/me` 按 bearer token 返回当前用户。
- 设置、审计、OCR/视觉模型配置等关键接口依赖当前用户；无 token 或伪造 token 应返回 401。

关键边界：

- `S1 模板与目录`：FastAPI 读取招标文件、项目模板或设置侧系统默认模板，调用目录 Skill 生成目录。
- `S3 缺口处理`：当前已认可缺口识别 Skill，读取真实素材库、Wiki、解析结果、项目身份和投标机型；AI 填写 Skill 仍待重新规划验收。
- `S4 生成标书`：调用本地 `bid-tech-assembler` Skill，按目录 JSON、缺口处理计划和素材库拼装正文。
- 覆盖诊断：读取正文拼装计划，校验未拼上的素材和未匹配目录项；保留为诊断/导出检查能力。
- `S5 共创`：由 FastAPI 对接 OnlyOffice。
- `S6 导出`：下载最终 Word。

## 2. 设计原则

- 前端只调用 FastAPI，不直接调用 `opencode`。
- FastAPI 是唯一 `/api` 后端，同时承担真实执行和兼容返回。
- 目录生成、缺口识别、标书生成均由 FastAPI 内部调用 OpenCode/Skill 或对应本地 runner；AI 填写仍待后续验收收口。
- 项目列表和项目状态持久化，MVP 统一使用 `PostgreSQL + 本地文件目录 + MinIO`。
- 用户主路径以 `S0-S6` 展示。

## 3. 认证、设置、审计和 OCR/视觉模型配置

### `POST /api/auth/login`

- 用途：真实账号密码登录
- 是否真实：真实

### `GET /api/auth/me`

- 用途：按 bearer token 获取当前用户
- 是否真实：真实

### `POST /api/auth/logout`

- 用途：退出登录并注销当前会话
- 是否真实：真实

### `GET /api/settings/users`

- 用途：读取系统用户列表
- 是否真实：真实

### `POST /api/settings/users`

- 用途：新增系统用户
- 是否真实：真实，写入审计日志

### `PUT /api/settings/users/{user_id}`

- 用途：更新用户资料、状态或密码
- 是否真实：真实，密码只保存哈希，审计日志不记录明文密码

### `GET /api/settings/default-templates`

- 用途：读取技术标/商务标系统默认模板
- 是否真实：真实

### `POST /api/settings/default-templates`

- 用途：上传技术标/商务标系统默认模板
- 是否真实：真实，写入 MinIO 或本地模板存储，并写审计日志

### `POST /api/settings/default-templates/{template_id}/activate`

- 用途：启用指定系统默认模板
- 是否真实：真实；项目上传模板优先，项目未上传时才使用系统默认模板

### `GET /api/settings/llm-gateway` / `PUT /api/settings/llm-gateway` / `POST /api/settings/llm-gateway/test`

- 用途：维护和测试 LLM Base URL、API Key、模型和超时
- 是否真实：真实；API Key 不向前端回传明文

### `GET /api/settings/ocr` / `PUT /api/settings/ocr` / `POST /api/settings/ocr/test`

- 用途：维护和测试 OCR/视觉模型 Base URL、API Key、模型和超时；供招标文件解析、模板读取等后端链路按需使用
- 是否真实：真实；API Key 不向前端回传明文

### `GET /api/settings/backups` / `POST /api/settings/backups/create` / `POST /api/settings/backups/{backup_id}/restore`

- 用途：管理备份记录和恢复操作
- 是否真实：真实，写入审计日志

### `GET /api/settings/health`

- 用途：探测 FastAPI、Postgres、Redis、MinIO、OnlyOffice、OpenCode、LLM 网关和 OCR/视觉模型网关
- 是否真实：真实探测

### `GET /api/audit` / `GET /api/audit/{audit_id}` / `GET /api/audit/export`

- 用途：查询、查看和导出真实审计日志
- 是否真实：真实持久化日志

说明：`/api/projects/{id}/ocr/*` 这组项目级 OCR 调试接口仍保留用于兼容和排障，但不作为前端主流程入口。用户在解析页或模板与目录页上传 PDF、扫描件、图片后，由后端自动调用 OCR/视觉模型并把识别文本交给原有 LLM/Skill 解析链路。

## 4. 项目与阶段

### `GET /api/projects`

- 用途：项目列表
- 是否真实：真实

返回字段中 `currentStage` 为项目模块阶段号 `1-6`，`stageLabel` 为当前阶段名称。

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

项目补全字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `projectCode` | string | 业务项目编号 |
| `materialCustomerId` | string | 重要客户 ID；普通客户为空或由后端生成 |
| `materialCustomerName` | string | 重要客户标准名称或普通客户名称 |
| `materialProjectMode` | string | `library` 表示已有项目，`ordinary` 表示普通项目 |
| `materialProjectId` | string | 已有项目或普通项目的素材项目 ID |
| `materialProjectCode` | string | 已有项目或普通项目编号 |
| `materialProjectName` | string | 已有项目或普通项目名称 |
| `turbineModel` | object | 技术标投标机型结构化字段，包含 `model/platform/layout/ratedPowerKw/rotorDiameterM/status/source` 等 |

说明：

- 前端项目信息页的客户来源展示为 `重要客户 / 普通客户`；接口字段仍沿用 `materialCustomer*`，表示项目绑定的客户素材读取身份。
- 前端项目信息页的项目来源展示为 `已有项目 / 普通项目`；接口字段仍沿用 `materialProject*`，表示项目绑定的项目素材读取身份。
- 技术标项目创建或更新时应提交已确认的 `turbineModel`。备选机型不作为静态 JSON 保存；页面通过 `/api/materials/turbine-model-options` 实时读取素材库参数表解析结果，只有选中的机型随项目保存。

### `GET /api/projects/{id}`

- 用途：项目详情
- 是否真实：真实

### `PUT /api/projects/{id}`

- 用途：更新项目基础信息和 `S0` 投标决策
- 是否真实：真实

说明：可更新 `projectCode`、客户/项目素材身份、负责人、起止日期和 `turbineModel`。`turbineModel` 会规范化后写入项目 payload，并在项目详情、列表摘要、缺口处理和生成标书 manifest 中复用。

### `DELETE /api/projects/{id}`

- 用途：删除项目
- 是否真实：真实

### `GET /api/projects/{id}/stages`

- 用途：获取项目模块阶段条
- 是否真实：真实

返回示例：

```json
[
  { "id": 1, "name": "模板与目录", "status": "active", "isHuman": false, "routeStageId": 1 },
  { "id": 2, "name": "审核目录", "status": "pending", "isHuman": true, "routeStageId": 2 },
  { "id": 3, "name": "缺口处理", "status": "pending", "isHuman": true, "routeStageId": 3 },
  { "id": 4, "name": "生成标书", "status": "pending", "isHuman": false, "routeStageId": 4 },
  { "id": 5, "name": "共创", "status": "pending", "isHuman": true, "routeStageId": 5 },
  { "id": 6, "name": "导出", "status": "pending", "isHuman": false, "routeStageId": 6 }
]
```

### `PUT /api/projects/{id}/stages/{stage}`

- 用途：阶段状态更新
- 是否真实：真实

说明：

- `stage` 推荐传当前 `1-6`。
- legacy 请求 `7/8/9/10` 会分别折叠到当前 `S4/S4/S5/S6`。
- 返回 `currentStage` 和 `stageLabel` 始终按当前 `S1-S6`。

## 5. S0 解析

### `GET /api/projects/{id}/parse-results`

- 用途：获取解析结果
- 是否真实：真实

### `GET /api/projects/{id}/parse-results/progress`

- 用途：获取解析进度
- 是否真实：真实

### `POST /api/projects/{id}/parse-results/run`

- 用途：触发解析
- 是否真实：真实

### `POST /api/projects/{id}/parse-results/upload-and-run`

- 用途：上传一个或多个招标文件和可选项目模板，并触发解析
- 是否真实：真实

说明：

- 请求为 `multipart/form-data`。
- `tenderFiles[]` 支持多个招标文件。
- PDF、图片型 PDF 和图片文件会按需调用 OCR/视觉模型，无需前端单独 OCR 入口。
- 解析完成后，`S0` 还需要在审核模块做“参与投标 / 不参与”决策；参与后进入项目模块 `S1`。

## 6. S1 模板与目录

### `GET /api/projects/{id}/template-fallback`

- 用途：查看项目当前有效模板来源
- 是否真实：真实

说明：

- 项目上传模板优先。
- 项目没有上传模板时，读取设置侧当前启用的同标类系统默认模板。
- 系统默认模板不会写入项目上传模板列表。

### `PUT /api/projects/{id}/template-fallback`

- 用途：启用或停用项目使用系统默认模板
- 是否真实：真实

### `POST /api/projects/{id}/template-files/upload`

- 用途：上传项目模板文件
- 是否真实：真实

### `GET /api/projects/{id}/directory-generation`

- 用途：获取目录生成状态
- 是否真实：真实

### `POST /api/projects/{id}/directory-generation/run`

- 用途：触发目录生成
- 是否真实：真实

说明：

- FastAPI 内部优先调用 futurecode/opencode 执行 `bid-tech-outline-generator` 的 `s2toc` 命令；命令完成后后端直接读取 `toc.json` 和 `toc_evidence.json`，并把路径写入 `opencodeOutput`。
- futurecode/opencode 调用失败时，FastAPI 会本地运行同一 Skill 脚本作为降级路径。
- 最新成功产物位于 `documents/{project_id}/technical-workspace/s2_toc_workdir/`；这是历史内部目录名，对应当前 `S1 模板与目录`。
- 新一轮先写入 `s2_toc_workdir.new/`，成功后发布，旧目录归档到 `s2_toc_workdir.runs/`。
- 接口返回的 `manifestPath` 与 `canonicalManifestPath` 均指向 `s2_toc_workdir/s2_input.json`；不再生成 `parsed/{project_id}/s2.json` alias。

## 7. S2 审核目录

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

## 8. S3 缺口处理

### `GET /api/projects/{id}/gaps-detection`

- 用途：获取缺口识别状态和处理计划
- 是否真实：真实

### `POST /api/projects/{id}/gaps-detection/run`

- 用途：调用缺口识别 Skill，生成匹配/缺口/处理计划
- 是否真实：真实

### `GET /api/projects/{id}/gaps`

- 用途：获取统一缺口处理页数据
- 是否真实：真实

### `PUT /api/projects/{id}/gaps/{gap_id}`

- 用途：更新缺口项处理动作或人工说明
- 是否真实：真实

### `POST /api/projects/{id}/gaps/{gap_id}/upload`

- 用途：上传客户资料并挂回缺口计划
- 是否真实：真实，写入项目级缺口工作目录和 `gapPlan.resolvedArtifacts`

### `POST /api/projects/{id}/gaps/{gap_id}/select-material`

- 用途：选择素材库已有素材并挂回缺口计划
- 是否真实：真实

### `POST /api/projects/{id}/gaps/{gap_id}/ai-fill`

- 用途：调用 AI 填写 Skill，按人工指定的空表/Word 和参考素材补齐缺口
- 是否真实：实验中，尚未作为当前 S3 已验收能力

### `POST /api/projects/{id}/gaps/recheck`

- 用途：重新检查缺口完整性
- 是否真实：待重新规划，尚未作为当前 S3 已验收能力

### `POST /api/projects/{id}/gaps/submit-review`

- 用途：提交缺口处理确认
- 是否真实：真实

### `POST /api/projects/{id}/review-items/prepare`

- 用途：生成缺口处理确认预览文档
- 是否真实：真实

### `POST /api/projects/{id}/review-items/confirm`

- 用途：确认缺口处理结果，允许进入标书生成
- 是否真实：真实

## 9. S4 生成标书

### `GET /api/projects/{id}/fill-generation`

- 用途：获取正文拼装状态
- 是否真实：真实

### `POST /api/projects/{id}/fill-generation/run`

- 用途：触发正文拼装
- 是否真实：真实

说明：

- 当前仍兼容前端原有 `fill-generation` 接口名。
- 后端会读取目录 JSON、Wiki 卡片、素材库清洗后 Word、缺口处理计划和补料/AI 填写产物，调用 `bid-tech-assembler` 生成正文 docx。
- 历史内部工作区为 `documents/{project_id}/technical-workspace/s7_assembly_workdir/`。
- 输出会写入项目文档路径，供 `S5 共创` 和 `S6 导出` 继续使用。

### `GET /api/projects/{id}/coverage`

- 用途：查看标书生成后素材覆盖情况；当前保留为诊断/导出检查能力
- 是否真实：真实

说明：

- `fullCover` 表示已被拼装计划使用的素材数量。
- `noCover` 表示素材库中可用但未出现在目录 JSON 或拼装计划中的素材数量。
- `partialItems` 表示目录项中未匹配素材或需要人工确认的项。
- 当前覆盖诊断是素材拼装覆盖校验，不等同于正式评分点覆盖审计。

## 10. S5 共创

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

## 11. S6 导出

### `GET /api/projects/{id}/final-document`

- 用途：获取最终 Word 下载信息
- 是否真实：真实

### `GET /api/projects/{id}/export/check`

- 用途：导出前检查
- 是否真实：MVP 轻量真实，评分点级覆盖审计仍待升级

### `POST /api/projects/{id}/export`

- 用途：导出动作
- 是否真实：MVP 轻量真实，当前仅支持 DOCX

## 12. 当前仍需收紧的接口

下面这些接口仍有兼容或 MVP 形态，后续应继续按实际业务收紧：

- `/api/projects/{id}/cockpit`
- `/api/customers/key-accounts`
- `/api/materials/raw/*`
- `/api/materials/structured/*`
- `/api/materials/wiki/*`

要求只有一个：

> **返回结构与现有前端预期一致，保证页面不报错。**

### 12.1 素材 Wiki 自动生成当前口径

`POST /api/materials/wiki/bootstrap` 当前用于生成或覆盖指定标类 Wiki：

```json
{ "mode": "replace", "bidType": "技术标" }
```

后端内部会直接执行技术标专用 Wiki Skill runner：

```bash
python opencode/skill/bid-tech-wiki-material-builder/scripts/run_from_manifest.py <wiki_build_manifest.json>
```

该命令只在 stdout 返回小摘要，完整 Wiki 蓝图写入共享 `outputFile`。FastAPI 再读取 `outputFile` 并导入 `wiki_nodes/wiki_docs`。这样可以避免大素材库经过 OpenCode 会话时超时，也避免大 JSON 被模型摘要或截断。

自动生成的 Wiki 一级结构固定为：

- `01-素材总表`
- `02-章节映射表`
- `03-素材卡片`
- `04-待填写清单`
- `05-使用规则`

其中 `03-素材卡片` 按 `通用素材 / 客户素材 / 项目素材` 分层，供 `S3 缺口处理`、空表填写来源选择和 `S4 生成标书` 按需加载。

## 13. 一句话总结

> **当前正式 API 文档服务于 S0-S6 MVP 落地；接口名可以兼容历史，用户阶段、返回标签和验收口径必须统一到 S0-S6。**
