# MVP 正式 API 文档

> 用途：作为当前 MVP 阶段 `Web 前端 -> FastAPI` 的正式接口基线。  
> 说明：本文件定义的是前端要调用的业务接口，不是 `FastAPI -> opencode` 的内部调用接口。

> 2026-05-02 更新：前端主进度已收敛为 6 个节点：模板与目录、审核目录、缺口处理、生成标书、共创、导出。本文保留 `directory-generation`、`gaps`、`review-items`、`fill-generation`、`coverage` 等接口名，是为了兼容当前代码和历史状态；这些接口不再代表独立的用户主流程页面。

## 1. 范围说明

当前 MVP 内部保留 S 段状态号和接口名，但前端主路径已经收敛为 6 个节点：

- 模板与目录
- 审核目录
- 缺口处理
- 生成标书
- 共创
- 导出

补充说明：

- 登录鉴权已真实化：`/api/auth/login` 校验系统用户密码并签发服务端会话 token，`/api/auth/me` 按 bearer token 返回当前用户。
- 设置、审计、OCR/视觉模型配置等关键接口依赖当前用户；无 token 或伪造 token 应返回 401。

关键边界：

- 模板与目录：FastAPI 本地规则引擎读取招标文件和投标模板生成目录
- 缺口处理：调用缺口识别 skill 和 AI 填写 skill，读取真实素材库、Wiki、解析结果和项目补料产物
- 生成标书：调用本地 `bid-tech-assembler` skill，按目录 JSON、缺口处理计划和素材库拼装正文
- 覆盖诊断：读取正文拼装计划，校验未拼上的素材和未匹配目录项；保留为诊断/导出检查能力
- 共创：由 FastAPI 对接 OnlyOffice
- 导出：下载最终 Word

## 2. 设计原则

- 前端只调用 FastAPI，不直接调用 `opencode`
- FastAPI 是唯一 `/api` 后端，同时承担真实执行和 mock 返回
- 目录生成、缺口识别、AI 填写、标书生成均由 FastAPI 内部调用 OpenCode/Skill 或对应本地 runner
- 项目列表和项目状态需要持久化，MVP 统一使用 `PostgreSQL + 本地文件目录`
- 当前接口优先兼容现有 React 前端；用户主路径以 6 个合并节点展示

## 3. 正式接口范围

## 3.0 认证、设置、审计和 OCR/视觉模型配置

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

- 主链路阶段由后端状态驱动。
- `/stages` 返回 6 个合并节点，并保留 `stageIds`、`routeStageId` 兼容内部 S 段状态。

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

- FastAPI 内部优先调用 futurecode/opencode 执行 S2 Skill 的 `s2toc` 命令；命令完成后后端直接读取 `toc.json` 和 `toc_evidence.json`，并把路径写入 `opencodeOutput`。
- futurecode/opencode 调用失败时，FastAPI 会本地运行同一 S2 Skill 脚本作为降级路径。
- 最新成功产物位于 `documents/{project_id}/technical-workspace/s2_toc_workdir/`；新一轮先写入 `s2_toc_workdir.new/`，成功后发布，旧目录归档到 `s2_toc_workdir.runs/`。
- 接口返回的 `manifestPath` 与 `canonicalManifestPath` 均指向 `s2_toc_workdir/s2_input.json`；不再生成 `parsed/{project_id}/s2.json` alias。

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

## 3.5 缺口识别与处理

### `GET /api/projects/{id}/gaps-detection`

- 用途：获取缺口识别状态和处理计划
- 是否真实：真实

### `POST /api/projects/{id}/gaps-detection/run`

- 用途：调用缺口识别 Skill，生成匹配/缺口/处理计划
- 是否真实：真实

### `GET /api/projects/{id}/gaps`

- 用途：获取统一缺口处理页数据
- 是否真实：真实

### `POST /api/projects/{id}/gaps/{gap_id}/upload`

- 用途：上传客户资料并挂回缺口计划
- 是否真实：真实，写入项目级缺口工作目录和 `gapPlan.resolvedArtifacts`

### `POST /api/projects/{id}/gaps/{gap_id}/select-material`

- 用途：选择素材库已有素材并挂回缺口计划
- 是否真实：真实

### `POST /api/projects/{id}/gaps/{gap_id}/ai-fill`

- 用途：调用 AI 填写 Skill，按人工指定的空表/Word 和参考素材补齐缺口
- 是否真实：真实

### `POST /api/projects/{id}/gaps/recheck`

- 用途：重新检查缺口完整性
- 是否真实：真实

### `POST /api/projects/{id}/gaps/submit-review`

- 用途：提交缺口处理确认
- 是否真实：真实

### `POST /api/projects/{id}/review-items/prepare`

- 用途：生成缺口处理确认预览文档
- 是否真实：真实

### `POST /api/projects/{id}/review-items/confirm`

- 用途：确认缺口处理结果，允许进入标书生成
- 是否真实：真实

## 3.6 生成标书

### `GET /api/projects/{id}/fill-generation`

- 用途：获取正文拼装状态
- 是否真实：真实

### `POST /api/projects/{id}/fill-generation/run`

- 用途：触发正文拼装
- 是否真实：真实

说明：

- 当前仍兼容前端原有 `fill-generation` 接口名。
- 后端会读取目录 JSON、Wiki 卡片、素材库清洗后 Word、缺口处理计划和补料/AI 填写产物，调用 `bid-tech-assembler` 生成正文 docx。
- 输出会写入项目文档路径，供 OnlyOffice 共创和导出继续使用。

## 3.7 覆盖诊断

### `GET /api/projects/{id}/coverage`

- 用途：查看标书生成后素材覆盖情况；当前保留为诊断/导出检查能力
- 是否真实：真实

说明：

- `fullCover` 表示已被拼装计划使用的素材数量。
- `noCover` 表示素材库中可用但未出现在 S2 目录 JSON 或拼装计划中的素材数量。
- `partialItems` 表示 S2 目录项中未匹配素材或需要人工确认的项。
- 当前覆盖诊断是素材拼装覆盖校验，不等同于正式评分点覆盖审计。

## 3.8 共创编辑

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

## 3.9 导出

### `GET /api/projects/{id}/final-document`

- 用途：获取最终 Word 下载信息
- 是否真实：真实

### `GET /api/projects/{id}/export/check`

- 用途：导出前检查
- 是否真实：可先 mock

### `POST /api/projects/{id}/export`

- 用途：导出动作
- 是否真实：可先做轻量真实，或直接复用最终文档下载

## 4. 当前仍需收紧的接口

下面这些接口仍有兼容或 MVP 形态，后续应继续按实际业务收紧：

- `/api/projects/{id}/cockpit`
- `/api/customers/key-accounts`
- `/api/materials/raw/*`
- `/api/materials/structured/*`
- `/api/materials/wiki/*`

要求只有一个：

> **返回结构与现有前端预期一致，保证页面不报错。**

## 5. 一句话总结

> **当前正式 API 文档服务于“现有前端 + FastAPI 统一承接”的 MVP 落地；前端接口保持兼容，真正的业务能力由 FastAPI 内部再去调用 `opencode` 和 OnlyOffice。**
