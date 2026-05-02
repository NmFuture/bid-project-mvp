# progress.md

## 记录规则

本文件记录标书工作区隔离改造的方案、过程和后续调整。

- 每次改动后追加一条进度记录。
- 记录内容包括：时间、改动目标、改动文件、验证结果、遗留问题。
- 已安装 Git `post-commit` hook：提交后会自动向本文件追加提交摘要。

## 进度记录

### 2026-05-02 13:21 待办 12/15 工作流收敛与 S4/S5/S6 真实化

改动目标：

- 完成待办 12/15 联合改造：模板页承接目录生成，缺口识别/补料/审核合并为“缺口识别与处理”，并用真实 `gapPlan` 串联素材匹配、AI 填写、完整性校验和 S7 拼接。

改动内容：

- 新增 `bid-tech-gap-planner` OpenCode Skill 和 `s4gap` 命令，输出 `bid-tech-gap-plan-v1` 匹配/缺口/处理计划。
- 新增 `bid-tech-table-filler` OpenCode Skill 和 `s4fill` 命令，AI 填写空表/Word 并输出 Word 产物、未填字段和证据引用。
- 后端新增 `app/services/gap_planning.py`，将已确认目录、解析结果和补料记录生成 `gapPlan`，支持 AI 填写产物挂回计划、OnlyOffice 预览 URL 和完整性校验。
- S4/S5/S6 接口改为读取和维护真实 `gapPlan`，不再自动跳过缺口；必须全部解决或人工忽略后才能提交审核。
- S7 manifest 增加 `gapPlanPath`，`bid-tech-assembler` 的 `build_assembly.py` 支持按缺口计划覆盖素材路径；S7 会把人工补料和 AI 填写产物写成运行时 Wiki 卡片纳入拼接。
- 前端模板上传页内嵌目录生成按钮、进度、任务状态和 OpenCode/Skill 输出；目录完成后直接进入目录审核。
- 前端 S5/S6 主流程收敛到 `/gaps`，旧 `/gaps-fill` 和 `/gaps/review` 重定向回统一缺口页。
- 前端缺口页升级为“缺口识别与处理”，展示匹配素材、缺口原因、AI 填写任务、处理产物、重新检查缺口和生成标书入口。
- 已勾选 `doc/14-甲方新增需求待办.md` 第 12 项和第 15 项。

验证结果：

- 后端 RED 测试已先失败，失败点为缺少 `gapPlan`、AI 填写接口和 S7 `gapPlanPath`。
- `python3 -m py_compile app/services/gap_planning.py app/services/store.py app/api/routes/gaps.py app/services/tech_assembly.py app/services/opencode_client.py opencode/skill/bid-tech-gap-planner/scripts/run_from_manifest.py opencode/skill/bid-tech-table-filler/scripts/run_from_manifest.py opencode/skill/bid-tech-assembler/scripts/build_assembly.py opencode/skill/bid-tech-assembler/scripts/run_from_manifest.py` 通过。
- `.venv/bin/python -m pytest tests/test_gap_review_flow.py tests/test_fill_generation.py tests/test_onlyoffice_document.py -q` 通过：23 passed。
- `.venv/bin/python -m pytest -q` 通过：78 passed，6 skipped。
- `npm run lint` 通过。
- `npm run build` 通过。
- 审计补强后新增统一缺口页客户资料上传闭环：`/api/projects/{project_id}/gaps/{gap_id}/upload` 会生成真实项目补料 Word 产物，挂回 `gapPlan.resolvedArtifacts` 并可供 S7 使用。
- 补强后 `.venv/bin/python -m pytest -q` 通过：79 passed，6 skipped。
- 补强后 `npm run lint` 通过。
- 补强后 `npm run build` 通过。
- 补强后 `docker compose build fastapi worker web && docker compose up -d --force-recreate fastapi worker web` 通过。
- 补强后 `/api/healthz` 返回 `status=ok`，`http://127.0.0.1/` 返回 HTTP 200。
- `docker compose build opencode fastapi worker web` 通过。
- `docker compose up -d --force-recreate opencode fastapi worker web` 已重建并启动，`fastapi` 和 `opencode` 健康，`web` 监听 80。
- `http://127.0.0.1/api/healthz` 返回 `status=ok`。
- `http://127.0.0.1/` 返回 HTTP 200。
- opencode 容器内 `s4gap`、`s4fill`、`s7assemble` 命令存在。
- opencode 容器内 `s4gap` 烟测通过，生成 `bid-tech-gap-plan-v1`，包含 3 个目录项、1 个匹配项、1 个缺口和 1 个 AI 填写任务。
- opencode 容器内 `s4fill` 烟测通过，生成 `bid-tech-table-fill-v1` JSON 和 Word 填写产物。

遗留问题：

- 当前 `bid-tech-gap-planner` 和 `bid-tech-table-filler` 已形成可运行 Skill 契约和本地 runner；实际模型效果、复杂表格填写准确率和证据页码质量仍需后续结合真实招标样本持续调优。
- S8 待办 16 仍需后续升级为评分点、证据和正文段落覆盖审计。

### 2026-05-02 12:59 待办 12/15 联合改造计划细化

改动目标：

- 细化待办 12“工作流收敛”和待办 15“S4/S5/S6 真实化”的联合实施口径。
- 明确 AI 填写也必须通过 OpenCode 调用专门 Skill 完成，而不是前端或后端本地规则直接填写。

改动内容：

- 在 `doc/14-甲方新增需求待办.md` 新增“待办 12/15 联合改造计划”。
- 明确目标流程：解析决策、模板上传/fallback、目录生成、目录审核、缺口识别与处理、AI 填写、OnlyOffice 预览、完整性校验、标书生成、共创。
- 明确核心中间产物 `gap_plan.json` / `gapPlan`，作为目录审核后到 S7 拼接前的统一桥梁。
- 明确新增两个 OpenCode Skill：
  - `bid-tech-gap-planner`：根据已确认目录、素材库 Wiki、真实素材库、解析结果和补料记录生成匹配/缺口/处理计划。
  - `bid-tech-table-filler` 或 `bid-appendix-filler`：根据空表/Word、人工指定参考素材和解析字段生成 AI 填写产物。
- 明确后端、前端、S7 拼接改造范围和完成标准。

验证结果：

- 本次仅更新需求计划文档，未改代码，未运行测试和部署。

遗留问题：

- 后续实现时需先确定 `gapPlan` 的具体 JSON Schema、Skill manifest 字段和 S7 `bid-tech-assembler` 对 `gapPlanPath` 的兼容方式。

### 2026-05-01 21:11 待办 8/13 项目日期与多招标文件结构化解析

改动目标：

- `http://127.0.0.1/parse` 支持多份招标文件一起解析，并输出评分细则、项目基础信息、风机参数、性能指标、环境适应性、专题方案等结构化结果。
- 结构化解析项保留来源文件、证据文本和证据位置。
- 项目支持起始日期和截止日期；S1 从招标文件识别日期并回填空字段，用户可在项目信息弹窗人工覆盖。

改动内容：

- 后端 S1 解析新增 `bid-tender-structured-parser` 目标 Skill、`s1parse` opencode 命令、结构化 JSON 产物和本地兜底解析。
- `parse_result` 增加 `items`、`structured`、`summary.categoryCounts` 和 `summary.projectDates`。
- 项目状态、列表、详情和驾驶舱增加 `startDate` / `endDate`，保留 `deadline` 作为截止日期兼容字段。
- 前端解析页从“关键技术参数”升级为结构化解析结果表，展示类别、字段、提取值、来源文件、证据位置和证据文本。
- 项目创建/完善弹窗增加起始日期和截止日期，确认提交时允许人工覆盖解析结果。
- 已勾选 `doc/14-甲方新增需求待办.md` 第 8 项和第 13 项。

验证结果：

- 后端 RED 测试已先失败并确认覆盖新增行为。
- `tests/test_parse_pipeline.py` 通过：8 passed。
- `.venv/bin/python -m pytest -q` 通过：62 passed，6 skipped。
- `python3 -m py_compile app/services/parsing.py app/services/store.py app/services/opencode_client.py app/api/routes/projects.py opencode/skill/bid-tender-structured-parser/scripts/run_from_manifest.py` 通过。
- `npm run lint` 通过。
- `npm run build` 通过；Vite 仍提示主 chunk 超过 500KB，这是既有构建体积提示。
- `docker compose build opencode fastapi web` 通过。
- `docker compose up -d opencode fastapi worker web` 已重建并启动，`fastapi` 健康，`web` 监听 80，`opencode` 健康。
- `http://127.0.0.1/` 返回 HTTP 200。
- `/api/healthz` 返回 `status=ok`。
- opencode 容器内 `s1parse` 命令存在，并已用容器内 manifest 烟测输出结构化 JSON。
- 已用临时项目调用 `/api/projects/{id}/parse-results/upload-and-run` 上传 Markdown 招标文件，返回 `extractedCount=7`，并正确识别 `startDate=2026-06-01`、`endDate=2026-09-30`；临时项目已删除。

遗留问题：

- S1 结构化解析当前是 Skill 命令 + 本地规则兜底，复杂自然语言和表格型 PDF 的高召回仍依赖后续 OCR/模型增强。

### 2026-05-01 20:03 素材库清洗稿 OnlyOffice 预览

改动目标：

- 素材库页面支持点击已清洗文件，在右侧用 OnlyOffice 只读预览清洗稿。
- 清洗失败、清洗中、待清洗或未生成清洗后 Word 的素材不开放预览。

改动内容：

- 后端新增 `/api/materials/raw/{file_id}/cleaned/preview`，返回清洗稿 OnlyOffice 会话。
- 清洗稿预览会话使用浏览器可访问 URL 和 OnlyOffice 容器可访问 URL 分离的现有口径。
- 清洗稿内容接口增加带文件名的 URL 形式，便于 OnlyOffice 识别文档。
- 前端素材库页面改为左侧素材库、右侧清洗稿预览的左右结构。
- 文件列表中已清洗且已生成 Word 的文件名和“预览”按钮可打开右侧预览；其他状态按钮禁用。
- 新增 OnlyOffice 预览路由回归测试。
- 已勾选 `doc/14-甲方新增需求待办.md` 第 5 项。

验证结果：

- `.venv/bin/python -m pytest -q` 通过：60 passed，6 skipped。
- `npm run lint && npm run build` 通过；Vite 仍提示主 chunk 超过 500KB，这是既有构建体积提示。
- `docker compose build fastapi web` 通过。
- `docker compose up -d fastapi web` 已重建并启动，`fastapi` 健康，`web` 监听 80。
- `http://127.0.0.1/` 返回 HTTP 200。
- `/api/materials/raw/RAW-0094/cleaned/preview` 对真实已清洗素材返回 `status=ready` 和 OnlyOffice 会话。
- 已用本地 Chrome headless 截图检查素材页左右结构，无明显布局重叠。

遗留问题：

- 清洗稿预览依赖 OnlyOffice Document Server 与 `ONLYOFFICE_BACKEND_BASE_URL` 连通性；若客户内网地址变化，需要按部署说明调整该环境变量。

### 2026-05-01 18:04 模板上传 Fallback 读取

改动目标：

- S1 模板上传界面支持查看和启停系统 fallback 模板来源。
- 项目未上传模板文件时，S2 目录生成和 S7 正文拼装可以读取 fallback 模板。
- 按用户指定文件 `/Users/wlb/Agent/bid-project/code/测试文档/投标文件-模板.docx` 入库为 fallback 模板。

改动内容：

- 新增系统 fallback 模板 MinIO 读取与下载逻辑。
- 项目状态增加 `templateFallback` 开关，新增 `/api/projects/{project_id}/template-fallback` 查询和更新接口。
- `store.get_parse_inputs()` 默认返回“有效生成输入”，仅在没有项目模板且 fallback 启用时临时追加 fallback 模板；上传/解析接口改为读取原始上传记录，避免把 fallback 混入项目模板列表。
- 前端 S1 模板上传页增加 fallback 来源、启停状态、MinIO bucket/key 展示。
- Docker Compose 增加 fallback 模板 bucket/key/name 环境变量。
- 已上传 fallback 模板到 MinIO：
  - bucket：`bid-templates`
  - key：`templates/fallback/technical/投标文件-模板.docx`
  - size：`190.53 MB`

验证结果：

- `.venv/bin/python -m pytest -q` 通过：58 passed，6 skipped。
- `npm run build` 通过。
- 受 Docker Hub metadata 查询影响，标准 `docker compose build fastapi web` 未能完成；已改用本机已有 `sewpg-bid/fastapi:latest`、`sewpg-bid/web:latest` 作为基础镜像做本地增量重建。
- 已重新部署并 force recreate：
  - `fastapi`
  - `worker`
  - `web`
- 烟测通过：
  - `http://127.0.0.1/` 返回 HTTP 200。
  - `/api/projects/{project_id}/template-fallback` 返回 `enabled=true`、`available=true`。
  - MinIO fallback 对象存在：`bid-templates/templates/fallback/technical/投标文件-模板.docx`。

遗留问题：

- 当前 fallback 模板来源只有一个系统默认源；后续如需要多套模板，可扩展 source 列表和选择器。

### 2026-04-27 11:19 上传文件夹弹窗滚动优化

改动目标：

- 上传文件夹时，如果选中文件很多，仍然能看到并点击底部“确认上传”按钮。

改动内容：

- 上传弹窗改为固定最大高度：`max-h-[calc(100vh-2rem)]`。
- 弹窗采用三段式布局：
  - 顶部标题固定。
  - 中间表单内容区域内部滚动。
  - 底部取消/确认上传按钮固定。
- 已选文件列表增加独立滚动区域，最大高度约为视口 32%。

验证结果：

- `npm run build` 通过。
- 已重新 build 并 force recreate `web`。
- `http://127.0.0.1/` 返回 HTTP 200，`web` 容器已使用新镜像启动。

### 2026-04-27 11:12 素材库递归显示与文件夹上传结构保留

改动目标：

- 解决素材库上传/触发清洗后前端文件列表为空的问题。
- 上传整个文件夹时保留原始文件夹名和内部层级。

改动内容：

- 后端 `raw_files` 查询从“精确目录”改为“当前目录 + 全部子目录”递归查询。
  - 选中 `通用素材`、`客户素材`、`项目素材` 母目录时，也能看到子目录中的文件。
  - 选中客户目录或项目目录时，也能看到对应子树文件。
- 后端 `raw_upload` 优化指定目录落位：
  - 上传到 `通用素材` 时自动落到 `通用素材/{标类}`。
  - 上传到 `客户素材/{客户}` 时自动落到 `客户素材/{客户}/{标类}`。
  - 上传到 `项目素材/{项目ID}` 时自动落到 `项目素材/{项目ID}/{标类}`。
- 文件夹上传继续使用浏览器的 `webkitRelativePath`，后端按该相对路径创建目录。
- 原文件夹结构写入文件元数据：
  - `sourceRelativePath`
  - `sourceRootFolder`
- 前端文件列表增加原始相对路径展示，便于确认文件夹上传结构。
- 前端在选中三母目录并点击“上传到此目录”时，自动切到“按素材层级”落位，避免文件直接散落到母目录根下。

验证结果：

- `py_compile app/services/material_store.py app/models/materials.py app/api/routes/materials.py` 通过。
- `npm run build` 通过。
- `.venv/bin/python -m pytest tests/test_toc_skill_scripts.py tests/test_opencode_client.py` 通过，9 个测试全部通过。
- 已重新 build 并 force recreate：
  - `fastapi`
  - `worker`
  - `web`
- API 烟测通过：
  - 临时上传 `FolderSmoke-xxxx/子目录/probe.txt` 到 `通用素材`。
  - 实际落位为 `通用素材/技术标/FolderSmoke-xxxx/子目录`。
  - `/api/materials/raw/files?folderPath=通用素材&bidType=技术标` 能递归查到该文件。
  - 返回中包含 `sourceRelativePath=FolderSmoke-xxxx/子目录/probe.txt`、`sourceRootFolder=FolderSmoke-xxxx`。
  - 烟测文件和空目录已删除，数据库无残留。

### 2026-04-27 10:58 素材库目录树固定三母目录

改动目标：

- 素材库目录树顶部固定为三个母目录，方便网页侧测试上传和 Wiki 构建：
  - `通用素材`
  - `客户素材`
  - `项目素材`

改动内容：

- 后端 `raw_tree` 增加固定根兜底：
  - 空库或根目录缺失时自动补齐三个母目录。
  - API 返回时只按固定顺序输出这三个根。
  - 根目录 `fileCount` 改为递归统计子树文件数。
- 前端 `MaterialDB.jsx` 增加固定根合并：
  - 即使接口返回为空，也会渲染三个母目录。
  - 按技术标/商务标过滤时，三个母目录仍保留显示，子目录继续按标类过滤。

验证结果：

- `py_compile app/services/material_store.py` 通过。
- `npm run build` 通过。
- 已重新 build 并 force recreate：
  - `fastapi`
  - `worker`
  - `web`
- API 验证 `/api/materials/raw/tree` 顶层固定返回：
  - `通用素材`
  - `客户素材`
  - `项目素材`
- `docker compose ps` 显示 `fastapi / web / worker` 已使用新容器启动，`fastapi` 健康。

### 2026-04-27 10:36 素材库与 Wiki 库结构清理

改动目标：

- 按当前工作流把素材库收敛为三层：通用素材、客户素材、项目素材。
- 技术标/商务标在素材库和 Wiki 中继续隔离。
- 移除旧的“标准模板/客户定制/项目定制/通用材料/质量审计/平台级 Wiki”口径。
- 删除前期清洗烟测留下的测试素材 `RAW-0012`。

改动内容：

- 前端素材库默认入口改为：
  - `通用素材/技术标`
  - `通用素材/商务标`
- 项目创建归档路径预览改为：
  - `客户素材/{客户名}/{标类}`
  - `项目素材/{项目ID}/{标类}`
- 后端项目材料路径、mock fallback、初始化 SQL 全部改为新素材根。
- Wiki 生成 prompt、确定性 fallback、opencode repair schema 和测试用例统一为 `质量日志`。
- 删除旧的通用 Wiki skill：`bid-wiki-bootstrap-json`。
- 保留底层 legacy alias，仅用于读取历史路径，不再作为新写入口径。
- 当前 PostgreSQL 数据已迁移：
  - `标准模板` -> `通用素材`
  - `客户定制` -> `客户素材`
  - `项目定制` -> `项目素材`
  - `客户素材/{客户}/通用材料` -> `客户素材/{客户}/技术标`
  - 补齐 `客户素材/{客户}/商务标`
- 删除旧 Wiki 根：
  - `风资源`
  - `机组选型`
  - `平台级Wiki（自动生成）`
- 重新生成并覆盖：
  - `技术标Wiki（自动生成）`
  - `商务标Wiki（自动生成）`

验证结果：

- 已备份清理前数据到 `/tmp/bid_material_wiki_cleanup_20260427_103117.sql`。
- `py_compile` 通过：
  - `material_store.py`
  - `wiki_generation.py`
  - `opencode_client.py`
  - `peripheral.py`
  - `store.py`
  - `projects.py`
- `.venv/bin/python -m pytest tests/test_wiki_generation.py tests/test_opencode_client.py tests/test_toc_skill_scripts.py` 通过，13 个测试全部通过。
- `npm run build` 通过。
- 已重新 build 并 force recreate：
  - `opencode`
  - `fastapi`
  - `worker`
  - `web`
- API 验证：
  - `/api/materials/raw/tree` 只返回 `通用素材 / 客户素材 / 项目素材` 三个根。
  - `/api/materials/wiki?bidType=技术标` 只返回 `技术标Wiki（自动生成）`。
  - `/api/materials/wiki?bidType=商务标` 只返回 `商务标Wiki（自动生成）`。
  - Wiki 子节点已改为 `07-技术标质量日志` 和 `07-商务标质量日志`。
  - `opencode` 容器内 skill 只保留两个 Wiki builder：`bid-tech-wiki-material-builder`、`bid-business-wiki-material-builder`。

遗留问题：

- 历史内置技术标素材已标记为 `pending`，表示还没有可下载的清洗后 Word；后续需要用真实源文件重新上传或批量补源后再触发清洗。
- 商务标当前没有真实素材，所以商务标 Wiki 是待补料框架。

### 2026-04-27 10:17 技术标素材库清洗与 Wiki 创建入口收敛

改动目标：

- 技术标/商务标素材库上传时让用户选择素材层级：通用素材、客户素材、项目素材。
- 上传后自动触发 `format-cleaner-v4`，把 PDF/Excel/Word 统一清洗为 Word。
- 源文件继续保留在 MinIO `raw/...`，清洗后的正式 Word 存入 MinIO `cleaned/...`。
- 前端状态收敛为少量可用状态，重点展示“已清洗 / 清洗失败”。
- 创建 Wiki 从三个模式按钮收敛为两个入口：生成/更新 Wiki、重建 Wiki。

改动内容：

- 安装 `format-cleaner-v4` 到 `opencode/skill/format-cleaner-v4/`，并补充 Docker 依赖：
  - `PyMuPDF`
  - `pandas`
  - `openpyxl`
  - `lxml`
- `format-cleaner-v4` driver 增加 `FORMAT_CLEANER_ALLOW_SYSTEM_PY=1`，允许 Docker/worker 使用系统 Python 运行。
- 新增 `app/services/material_cleaning.py`：
  - 从 PostgreSQL 读取 `raw_files`。
  - 从 MinIO 下载源文件。
  - 调用 `format-cleaner-v4/scripts/driver.py`。
  - 上传清洗后的 Word 到 MinIO `cleaned/RAW-xxxx/...docx`。
  - 把 `cleanStatus / cleanMessage / cleanedMinioKey / cleanedFileName / cleanedSize` 写回 `raw_files.ext_fields`。
- Redis worker 新增 `material_cleaning` 任务类型。
- `raw_upload` 上传成功后自动入队清洗任务。
- 新增 API：
  - `POST /api/materials/raw/{file_id}/clean`
  - `GET /api/materials/raw/{file_id}/cleaned/download`
  - `GET /api/materials/raw/{file_id}/cleaned/content`
- 前端 `MaterialDB.jsx`：
  - 上传弹窗增加素材层级选择。
  - 文件列表增加层级和清洗状态列。
  - 支持下载源文件、下载清洗后 Word、清洗失败后重试。
  - 状态筛选收敛为全部、已清洗、清洗失败。
  - Wiki 操作收敛为“生成/更新 Wiki”和“重建 Wiki”两个按钮。
- 更新上传白名单：`.pdf,.doc,.docx,.md,.xls,.xlsx,.xlsm`。

验证结果：

- `npm run build` 通过。
- `py_compile` 通过：
  - `material_store.py`
  - `material_cleaning.py`
  - `materials.py`
  - `job_queue.py`
  - `redis_worker.py`
  - `models/materials.py`
  - `format-cleaner-v4/scripts/driver.py`
- `.venv/bin/python -m pytest tests/test_wiki_generation.py tests/test_opencode_client.py` 通过，10 个测试全部通过。
- 已重新部署并 force recreate：
  - `opencode`
  - `fastapi`
  - `worker`
  - `web`
- 运行时核对：
  - `opencode` 容器内存在 `format-cleaner-v4`，且 `fitz/pandas/openpyxl/lxml/docx` 依赖可导入。
  - `fastapi` 容器内存在 `format-cleaner-v4/scripts/driver.py`，且依赖可导入。
  - `docker compose ps` 显示 `fastapi / opencode / postgres / redis / minio` 健康。
- 真实链路烟测通过：
  - 上传测试文件 `RAW-0012` 到 `标准模板/技术标`。
  - Redis worker 自动清洗完成。
  - API 返回 `cleanStatus=cleaned`、`cleanResultStatus=SKIP`、`hasCleanedWord=true`。
  - 清洗后 Word 已上传至 MinIO `bid-materials/cleaned/RAW-0012/...docx`。
  - `GET /api/materials/raw/RAW-0012/cleaned/content` 下载成功，HTTP 200，大小 36721 bytes。

遗留问题：

- `tests/test_peripheral_routes.py` 在当前本地测试环境仍存在 asyncpg 连接跨事件循环问题，表现为 `Future attached to a different loop / cannot perform operation: another operation is in progress`。本次改造相关的运行时 API 已用真实 Docker 链路验证通过。
- 目前 `format-cleaner-v4` 支持 `.pdf/.doc/.docx/.xls/.xlsx/.xlsm`；图片、zip、md 等非 Word 化素材后续需要单独定义 OCR/解包/文本清洗策略。

### 2026-04-27 09:19 S2 目录 skill 三段式优化

改动目标：

- 按“投标模板主骨架 -> 招标文件修订 -> Wiki 小标题/素材补充”的思路优化 `bid-toc-wiki-driven-v2`。
- 让目录 JSON 不只是标题，而是带模板来源、招标证据和素材引用，供后续 S3 审核、S4 缺口识别和 S7 正文生成继续使用。

改动内容：

- `extract_template.py`
  - 优先使用 Word TOC 样式作为目录主骨架。
  - 当 TOC 可用时，不再把正文 Heading 1/2 重复抽成第 7/8/9 章。
  - 保留模板来源信息：`raw_text / page / style / source_kind`。
- `extract_tender.py`
  - 招标关键词抽取增加 `site_evidence / model_evidence / plot_evidence`。
  - `specials[]` 增加 `confidence` 和 `evidence`，不再只是关键词。
- `wiki_lookup.py`
  - 支持把聚合 Wiki 卡片中的 `### 素材名` 拆成具体素材条目。
  - 从 `attach / skeleton / docx / title` 推断素材挂载章节。
  - 跳过“投标文件-模板”这类主模板素材，避免把主模板又加回目录子项。
- `build_plan.py`
  - 模板 H1/H2 始终作为主骨架。
  - Wiki 同名素材挂到模板 H2 的 `material_refs`，不重复生成标题。
  - Wiki 中模板未覆盖的小标题作为子目录补充。
  - 招标 specials 可插入多个新增条目，不再每章只插入一个。
  - 每个条目尽量补充 `source_refs / material_refs`。
- `outline_generation.py`
  - V2 JSON 转前端审核树时透传 `sourceRefs / materialRefs`。
- `bid-toc-wiki-driven-v2/SKILL.md`
  - 更新输出契约，明确 `source_refs / material_refs` 和三段式生成原则。

验证结果：

- `.venv/bin/python -m py_compile ...` 通过。
- `.venv/bin/python -m pytest tests/test_opencode_client.py tests/test_directory_generation.py tests/test_wiki_generation.py tests/test_toc_skill_scripts.py` 通过，22 个测试全部通过。
- 使用 `PRJ-0022` 真实输入本地 manifest 烟测通过，输出 62 条目录项：
  - 保留 27
  - 适配 30
  - 新增-招标要求 4
  - 新增-素材库建议 1
- 已重新部署 `opencode / fastapi / worker / web`。
- 已用新版 skill 重新生成并写回 `PRJ-0022`：
  - 一级章从 13 个收敛为 6 个。
  - 总节点从 115 个收敛为 62 个。
  - API 验证 `/api/projects/PRJ-0022/outline` 返回 `roots=6 / total=62`。
  - 节点已包含 `materialRefs`，例如 `技术评分标准索引表` 指向 `RAW-0004`。

遗留问题：

- 招标 specials 的证据已经进入 JSON，但仍可能包含“提到但不是明确要求”的上下文；后续需要继续做否定语义和“强要求/弱出现”的区分。
- Wiki 的 `attach` 和 `skeleton` 元数据质量会直接影响小标题挂载准确性，后续仍需把 Wiki 卡片维护得更规范。

### 2026-04-27 08:49 S3 目录审核卡顿修复

问题现象：

- 进入目录审核界面后页面明显卡顿，滚动和交互都很慢。

根因：

- `PRJ-0022` 的 S2 目录结果被抽成 659 个节点，其中一级节点 385 个。
- 大量正文句子、日期、测风塔数据、页码等被 `extract_template.py` 的兜底逻辑误判成目录标题。
- S3 目录审核前端会递归渲染每个节点为可编辑输入框，且默认全部展开；几百个受控输入框一起渲染，导致页面滚动卡顿。

修复：

- 收紧 `extract_template.py` 的模板目录兜底识别：
  - 限制标题长度。
  - 排除日期、正文长句、带明显正文标点的段落、`#` 开头的数据行。
  - 普通编号标题必须有明确分隔符。
  - 限制异常的大编号一级章节。
  - H2 必须匹配当前 H1 编号。
  - 清理目录行尾页码。
- 优化 `OutlineReview.jsx`：
  - 增加节点计数。
  - 当目录节点超过 180 个时默认折叠所有可展开节点，避免一次性展开大树拖慢页面。

验证结果：

- `extract_template.py` 手工夹具验证通过，日期、正文句子和测风塔数据不再被识别为标题。
- `.venv/bin/python -m py_compile opencode/skill/bid-toc-wiki-driven-v2/scripts/extract_template.py opencode/skill/bid-toc-wiki-driven-v2/scripts/run_from_manifest.py` 通过。
- `npm run build` 通过。
- `.venv/bin/python -m pytest tests/test_opencode_client.py tests/test_directory_generation.py tests/test_wiki_generation.py` 通过，19 个测试全部通过。
- `docker compose up -d --build opencode web` 已重新部署，`fastapi / opencode / web` 均为 healthy/up。
- 已重新生成并写回 `PRJ-0022` 目录状态：由 659 个节点降为 115 个节点，一级节点由 385 个降为 13 个。

遗留问题：

- 当前目录不再是灾难性膨胀，但仍能看到部分模板章节重复，例如第七章到第九章重复出现技术章节名；后续还需要继续优化模板目录去重和章节边界识别。

### 2026-04-27 08:40 S2 流式输出卡住排查与修复

问题现象：

- 本地测试 `PRJ-0022` 时，S2 目录生成页面停在流式输出阶段。
- 前端 SSE 连接存在，但后续没有新内容。

根因：

- `bid-toc-wiki-driven-v2` 已经成功生成完整目录 JSON：`/data/parsed/PRJ-0022/s2_toc_workdir/投标文件-总目录.json`。
- 本次完整 JSON 有 659 条目录项，约 158KB。
- OpenCode 在 Bash 命令完成后尝试把完整 JSON 再读回模型上下文，读到 50KB 截断后继续调用 `Glob` 检查输出文件。
- 这个 `Glob` 工具调用长期处于 running，导致 worker 一直等待 OpenCode 最终响应，页面流式输出不再更新。

修复：

- `run_from_manifest.py` 新增 `--response summary`。
- OpenCode 现在只返回小型摘要 JSON：`schema_version / document_title / outputFile / summary / itemCount`。
- 后端 `outline_generation.py` 收到 `outputFile` 后，直接从共享卷读取完整 `投标文件-总目录.json`，再转换为 S3 所需的 `nodes[]`。
- OpenCode prompt 明确禁止再用 `Read/Glob` 打开完整大 JSON。
- `opencode_client.py` 接受 `outputFile` 型 S2 摘要响应。

验证结果：

- `.venv/bin/python -m pytest tests/test_opencode_client.py tests/test_directory_generation.py tests/test_wiki_generation.py` 通过，19 个测试全部通过。
- `run_from_manifest.py --response summary` 本地烟测通过。
- `docker compose up -d --build opencode fastapi worker` 已重新部署。
- 容器内确认 `bid-toc-wiki-driven-v2` 已使用 `--response summary`，脚本 py_compile 通过。
- 当前 `PRJ-0022` 已用已生成的 V2 JSON 收口为 completed：共 659 条目录项，输出为 385 个一级节点。
- Redis `directory_generation:PRJ-0022` 锁不存在。

### 2026-04-27 08:23 S2 目录 skill 替换与 API/wiki 适配

改动目标：

- 删除旧目录生成 skill，替换为 `bid-toc-wiki-driven-v2`。
- 新 skill 不再只吃 prompt 文本，而是通过后端准备的 manifest 读取招标文件、投标正文模板、可选附表模板。
- 新 skill 在缺少文件系统 wiki 时，通过后端 API 读取数据库中的对应标类 Wiki 并导出为 `wiki/卡片`。
- 放开 OpenCode Bash 权限，让 skill 可以运行 Python 脚本。

改动文件：

- `code/sewpg-bid-backend/opencode/skill/bid-toc-wiki-driven-v2/`
- `code/sewpg-bid-backend/opencode/skill/bid-outline-json/`（已删除）
- `code/sewpg-bid-backend/opencode/skill/bid-toc-wiki-driven/`（已删除）
- `code/sewpg-bid-backend/opencode/skill/bid-wiki-material-builder/`（旧共享 Wiki skill，已删除）
- `code/sewpg-bid-backend/opencode/.opencode/skills/bid-outline-json/`（已删除）
- `code/sewpg-bid-backend/app/services/outline_generation.py`
- `code/sewpg-bid-backend/app/services/opencode_client.py`
- `code/sewpg-bid-backend/app/core/config.py`
- `code/sewpg-bid-backend/opencode/opencode.json`
- `code/sewpg-bid-backend/opencode/docker-entrypoint.sh`
- `code/docker-compose.yml`
- `code/sewpg-bid-backend/tests/test_directory_generation.py`
- `code/sewpg-bid-backend/tests/test_opencode_client.py`

实现说明：

- S2 后端会创建 `s2_toc_workdir/s2_input.json`，其中包含项目 ID、标类、工作目录、后端 API 地址、招标文件路径、投标正文模板路径、附表模板路径、wiki 目录和输出 JSON 路径。
- OpenCode prompt 改为调用 `bid-toc-wiki-driven-v2`，并明确执行：
  `python3 /workspace/.opencode/skills/bid-toc-wiki-driven-v2/scripts/run_from_manifest.py --manifest <s2_input.json>`。
- 新增 `export_wiki_from_api.py`：通过 `GET /api/materials/wiki?bidType=技术标/商务标` 拉取数据库 Wiki，导出为 V2 可读的文件系统卡片。
- 新增 `run_from_manifest.py`：串起 `extract_template / extract_tender / extract_attach / build_plan`，最终把完整 V2 JSON 打印给 OpenCode。
- `opencode` 容器增加 `/data/uploads:ro` 和 `/data/parsed` volume，使 skill 能读取上传文件并写回输出 JSON。
- `outline_generation.py` 增加 V2 `items[] -> nodes[]` 适配层，S3 前端仍可使用原来的目录树，同时在 `opencodeOutput` 保留 skill 名、manifest 路径和 V2 JSON 路径。
- `extract_template.py` 增加普通编号段落兜底识别，避免模板没有 Word Heading 样式时抽空。
- 旧共享 Wiki skill 已下线，Wiki 生成只保留 `bid-tech-wiki-material-builder` 和 `bid-business-wiki-material-builder` 两个分标类入口。

验证结果：

- `python -m py_compile` 通过。
- `.venv/bin/python -m pytest tests/test_opencode_client.py tests/test_directory_generation.py tests/test_wiki_generation.py` 通过，17 个测试全部通过。
- 使用临时 docx + 临时 wiki 跑 `run_from_manifest.py` 通过，输出 `bid-toc-json-v1`，并生成 4 条目录项。
- `docker compose config` 通过。
- `docker compose up -d --build opencode fastapi worker` 已完成部署，`opencode / fastapi / worker` 均已重建并启动。
- 运行时核对通过：`opencode` 容器内 `bash=allow`，存在 `bid-toc-wiki-driven-v2`，不存在旧 `bid-outline-json` 和旧共享 `bid-wiki-material-builder`。
- 运行时 API 导出通过：`opencode` 容器调用 `http://fastapi:8000/api/materials/wiki?bidType=技术标` 成功导出 7 张 wiki 卡片。

遗留问题：

- 真实业务效果取决于数据库 Wiki 卡片中的 `skeleton_section` 质量；当前导出脚本会从 Markdown Merge 信息和标题兜底推断，但后续仍应把 Wiki 卡片元数据维护得更规范。

### 2026-04-27 S2 新目录 skill 替换前理解

改动目标：

- 理解当前 S2 目录生成链路。
- 理解 `/Users/wlb/Downloads/skills/bid-toc-wiki-driven-v2.zip` 的输入输出契约，为后续替换做准备。

当前链路结论：

- 当前 S2 已调用 OpenCode，但使用的是轻量 `bid-outline-json` skill。
- 当前 S2 输入来自 S1：
  - `parse_storage.combinedTextPath`：招标文件解析后的合并文本。
  - `templateFileRecords`：S1 上传的投标模板文件记录。
- 当前后端只从招标文本和模板 docx 中提取少量章节线索，再把线索放进 prompt，不把原始 docx 工作目录交给 skill。
- 当前 S2 没有读取素材 Wiki。

新 skill 结论：

- `bid-toc-wiki-driven-v2` 是文件工作目录型 skill。
- 它要求工作目录里能识别：
  - `*招标*.docx`
  - `*投标*正文*.docx`
  - 可选 `*投标*附表*.docx`
  - 文件系统版 `wiki/卡片` 与规则文件
- 它输出的是总目录 JSON，结构为 `schema_version / document_title / project / source_files / summary / items`，不是当前前端直接使用的 `summary / nodes`。

替换前需要做的适配：

- 安装新 skill 到 `opencode/skill/bid-toc-wiki-driven-v2/`。
- S2 后端准备项目级临时工作目录，把招标 docx、投标正文模板、可选附表模板、技术标或商务标 wiki 放进去。
- OpenCode prompt 改为调用 `bid-toc-wiki-driven-v2`。
- 增加 JSON 适配层：把新 skill 的 `items[]` 转成 S3 前端需要的 `nodes[]`，同时保留完整目录 JSON 作为审计/后续正文生成输入。
- 当前 OpenCode 配置里 `bash` 是 `deny`；新 skill 依赖 Bash 调 python 脚本，替换时需要调整权限或改成后端直接执行脚本。

验证结果：

- 已解压新 skill 到临时目录。
- `python -m py_compile scripts/*.py` 通过。

### 2026-04-27 工作区入口收敛

改动目标：

- 将原方案文档改名为 `progress.md`，作为持续进度记录文件。
- 创建进度记录 hook，后续提交后自动写入本文件。
- 技术标/商务标工作区顶部标签只保留 `项目 / 素材库 / 日志`。
- 移除顶部的 `流程` 和 `Wiki` 标签。

改动说明：

- `项目` 是工作区的自然入口，点击项目后进入 S1-S10 流程，因此不再单独暴露 `流程` 标签。
- `素材库` 是人可见入口，Wiki 仍保留在素材库内部展示；Wiki 本质上主要给 AI/Skill 读取，不作为工作区顶部独立入口。
- `/workspace/:workspace/flow` 保留兼容，但会跳回对应工作区的项目页。
- `/workspace/:workspace/materials/wiki` 仍保留兼容，素材库内部切换到 Wiki 时继续可用。
- 原 `code/progress.md` 的联调历史已合并到本文末尾，避免改名时丢失旧记录。

涉及文件：

- `code/progress.md`
- `code/hooks/record-progress.sh`
- `.git/hooks/post-commit`
- `code/sewpg-bid-frontend/src/components/layout/AppShell.jsx`
- `code/sewpg-bid-frontend/src/App.jsx`

验证结果：

- `npm run build` 通过。
- `sh -n code/hooks/record-progress.sh && sh -n .git/hooks/post-commit` 通过。
- `docker compose up -d --build web` 已完成，web 容器已重建并启动。
- 代码检查确认工作区顶部标签只剩 `项目 / 素材库 / 日志`；素材库内部仍保留 Wiki 切换。

## 标书工作区隔离改造方案

## 目标

系统入口调整为：

```text
解析（共用）
  -> 解析通过后创建投标项目
    -> 技术标工作区
    -> 商务标工作区

设置（共用）
```

除 `解析` 和 `设置` 外，项目、S1-S10 流程、素材库、Wiki、日志都按标类隔离。

对人可见的工作区顶部入口收敛为：

```text
项目 / 素材库 / 日志
```

其中：

- `项目` 内自然进入 S1-S10 撰写流程。
- `素材库` 内保留原始素材和 Wiki 展示。
- `Wiki` 不作为顶部独立入口，主要作为 AI/Skill 可读取的素材组织层。

## 入口定义

### 解析

解析是全局共用入口。用户在这里上传招标文件，点击解析后调用后续的 opencode skill。

该 skill 的目标：

- 解析招标文件。
- 提取资格、评分、技术、商务、交付、合同等关键关注点。
- 判断公司是否满足招标要求。
- 给出参与 / 不参与 / 风险待确认的前置判断。

解析通过后，系统进入正式标书撰写阶段，并创建技术标、商务标两个工作区入口。

### 技术标工作区

技术标工作区只展示技术标数据：

- 技术标项目
- 技术标 S1-S10 流程
- 技术标素材库
- 技术标 Wiki
- 技术标日志

技术标页面不展示商务标项目、商务标素材、商务标 Wiki。

### 商务标工作区

商务标工作区只展示商务标数据：

- 商务标项目
- 商务标 S1-S10 流程
- 商务标素材库
- 商务标 Wiki
- 商务标日志

商务标页面不展示技术标项目、技术标素材、技术标 Wiki。

### 设置

设置仍为全局共用，管理系统级配置：

- 用户与角色
- opencode 配置
- OnlyOffice 配置
- 模板和系统参数

## 第一版落地边界

第一版先搭框架，不一次性重写全部业务：

1. 全局导航改为 `解析 / 技术标 / 商务标 / 设置`。
2. 技术标、商务标进入独立工作区。
3. 工作区内提供 `项目 / 素材库 / 日志`。
4. 前端路由带工作区上下文。
5. 所有项目、素材、Wiki 请求自动带 `bidType`。
6. 保留旧路由作为兼容入口，避免当前演示链路断开。

## 路由草案

```text
/parse

/workspace/tech/projects
/workspace/tech/projects/:projectId/parse
/workspace/tech/projects/:projectId/directory
/workspace/tech/projects/:projectId/outline
/workspace/tech/projects/:projectId/gaps
/workspace/tech/projects/:projectId/gaps-fill
/workspace/tech/projects/:projectId/gaps/review
/workspace/tech/projects/:projectId/generate
/workspace/tech/projects/:projectId/coverage
/workspace/tech/projects/:projectId/editor
/workspace/tech/projects/:projectId/export
/workspace/tech/materials/structured
/workspace/tech/materials/wiki
/workspace/tech/logs

/workspace/business/projects
/workspace/business/projects/:projectId/...
/workspace/business/materials/structured
/workspace/business/materials/wiki
/workspace/business/logs

/settings
```

## 底层数据边界

短期使用现有字段做兼容隔离：

```text
project.bidType
raw_folder.bid_type
raw_file.ext_fields.bidType
wiki_node.bid_types
```

后续正式化时建议补充 `bid_workspace` 概念：

```text
tender_parse
  id
  tender_file
  parsed_requirements
  eligibility_result
  status

bid_project
  id
  tender_parse_id
  project_name
  owner
  status

bid_workspace
  id
  project_id
  bid_type: 技术标 / 商务标
  current_stage
  current_document
  status
```

正式版本中，S1-S10、素材、Wiki、日志都应挂到 `bid_workspace`，而不是只靠项目 ID。

## Skill 分工

解析阶段：

- `bid-tender-parse-eligibility`：解析招标文件并判断是否满足投标要求。

技术标工作区：

- 技术标目录生成 skill。
- 技术标正文生成 skill。
- `bid-tech-wiki-material-builder`。

商务标工作区：

- 商务标目录生成 skill。
- 商务标正文生成 skill。
- `bid-business-wiki-material-builder`。

## 验收标准

第一版验收：

- 顶部/侧边入口从 `审核` 改为 `解析`，从 `审计` 改为 `日志`。
- 点击 `技术标` 只看到技术标项目、素材库、日志。
- 点击 `商务标` 只看到商务标项目、素材库、日志。
- Wiki 不出现在工作区顶部标签中，但可在素材库内部展示。
- 技术标和商务标都能进入自己的 S1-S10 流程。
- 旧的 `/projects`、`/materials/*`、`/audit` 路由不立即删除，作为兼容入口保留。

## 历史联调进展（原 progress.md）

### 联调进展

## 当前状态

- 已完成 API 核心文档收敛
- 已完成 FastAPI 最小骨架
- 已完成 `sewpg-bid-backend` 目录结构整理
- 已完成 S1 真实解析
- 已完成 S9 / S10 OnlyOffice 真实链路
- 已完成 `opencode` Docker 部署与 S2 真实目录生成
- 已完成 `S7` 真实初稿生成与 `S8` 覆盖 mock 承接
- 当前下一步：收成完整 `docker compose`

## 已完成

### 2026-04-19

- 重写 [MVP接口与参数核心版_极简版.md](/Users/wlb/Agent/bid-project/code/sewpg-bid-api/MVP接口与参数核心版_极简版.md)
  - 对齐当前前端真实接口
  - 补齐 `GET /directory-generation`
  - 补齐 `POST /outline/regenerate`
  - 补齐 `GET /fill-generation`
  - 补齐 `POST /document/force-save`
  - 把 S9 返回结构改成顶层 `onlyoffice`

- 新增 FastAPI 骨架
  - [main.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/main.py)
  - [config.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/core/config.py)
  - [router.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/api/router.py)
  - [routes](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/api/routes)
  - [store.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/services/store.py)

- 补齐后端依赖
  - [requirements.txt](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/requirements.txt)

- 整理 `sewpg-bid-backend` 结构
  - 新增 [README.md](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/README.md)
  - 新增 [.gitignore](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/.gitignore)
  - 路由按领域拆到 `app/api/routes`
  - `store` 移到 `app/services`

- 本机验证通过
  - `GET /healthz`
  - `POST /api/projects`
  - `POST /api/projects/{id}/parse-results/upload-and-run`
  - `GET /api/projects/{id}/stages`
  - `POST /api/projects/{id}/directory-generation/run`
  - `GET /api/projects/{id}/outline`
  - `POST /api/projects/{id}/fill-generation/run`
  - `GET /api/projects/{id}/document`
  - `PUT /api/projects/{id}/document/save`
  - `GET /api/projects/{id}/final-document`

- OnlyOffice 接入前检查已完成
  - 确认前端 `CoCreationEditor.jsx` 已有 `DocsAPI.DocEditor(...)` 挂载逻辑
  - 确认前端 `.env.development` 默认指向：
    - Document Server: `http://localhost:8080`
    - demo backend: `http://127.0.0.1:8000`
  - 已启动本机 Docker Desktop
  - 已发现并清理 `8080` 端口上的临时 `python -m http.server`
  - 已拉起 `onlyoffice/documentserver`
  - 已确认 `http://127.0.0.1:8080/healthcheck` 返回 `true`

- 已接入真实 OnlyOffice 文档链路
  - 后端新增 [onlyoffice_documents.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/services/onlyoffice_documents.py)
  - [document.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/api/routes/document.py) 已改成真实 `.docx` 文件链路
  - `GET /api/projects/{id}/document/file` 已返回真实 docx，而不是纯文本
  - `GET /api/projects/{id}/document` 已返回 Docker 可访问的 `host.docker.internal` fileUrl / callbackUrl
  - `POST /api/projects/{id}/document/callback` 已支持回拉 OnlyOffice 保存结果并更新版本

- 已同步当前项目 S9 前端
  - [CoCreationEditor.jsx](/Users/wlb/Agent/bid-project/code/sewpg-bid-frontend/src/pages/CoCreationEditor.jsx) 已切到“只要后端给会话就尝试挂载”
  - [onlyoffice.js](/Users/wlb/Agent/bid-project/code/sewpg-bid-frontend/src/config/onlyoffice.js) 已补齐 `loadOnlyOfficeScript`
  - 已去掉 S9 对 browser healthcheck 的强依赖

- 已完成旧 mock 资产收口
  - 已停用并移除旧 `fastapi-mock`
  - 已停用并移除旧 `mock-server`
  - 已移除旧 `smoke` 脚本入口
  - [package.json](/Users/wlb/Agent/bid-project/code/sewpg-bid-frontend/package.json) 当前只保留正式后端相关脚本
  - [start.sh](/Users/wlb/Agent/bid-project/code/sewpg-bid-frontend/start.sh) 与 [start.bat](/Users/wlb/Agent/bid-project/code/sewpg-bid-frontend/start.bat) 当前都已切到启动正式后端

- 验证已通过
  - 后端测试：[test_onlyoffice_document.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/tests/test_onlyoffice_document.py) `2/2 OK`
  - 前端校验：`npm run check` 通过
  - 本机接口验证：
    - `POST /api/projects`
    - `GET /api/projects/{id}/document`
    - `GET /api/projects/{id}/document/file`
    - `POST /api/projects/{id}/document/callback`

- 已完成 SQLite 持久化
  - [store.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/services/store.py) 已从纯内存态切到 SQLite 持久化
  - 新增测试：[test_store_persistence.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/tests/test_store_persistence.py)
  - 测试通过：
    - `test_project_persists_across_store_restart`
    - `test_project_id_continues_after_restart`
  - 运行态已验证：创建项目后，重启 FastAPI 仍可读取同一项目
  - 本机数据目录：
    - SQLite：[/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/.localdata/sqlite/app.db](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/.localdata/sqlite/app.db)
    - 上传文件：[/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/.localdata/uploads](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/.localdata/uploads)
    - 生成文档：[/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/.localdata/documents](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/.localdata/documents)

- 已完成 S1 真实解析第一版
  - 后端新增 [parsing.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/services/parsing.py)
  - 当前支持：
    - `docx` 真实抽文本
    - `pdf` 预留真实抽文本能力（`pypdf`）
  - 当前策略：
    - 上传原文件继续落到 `uploads/`
    - 解析后的大文本不写入 SQLite
    - 解析 artifact 单独落到 `parsed/`
    - SQLite 只保存摘要、预览和 artifact 路径
  - 前端 S1 已切到真实 `FormData` 上传：
    - [ParseResult.jsx](/Users/wlb/Agent/bid-project/code/sewpg-bid-frontend/src/pages/ParseResult.jsx)
    - [index.js](/Users/wlb/Agent/bid-project/code/sewpg-bid-frontend/src/api/index.js)
  - 新增测试：[test_parse_pipeline.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/tests/test_parse_pipeline.py)
  - 本机大文件实测：
    - `招标文件.docx`（约 20.8 MB）解析成功
    - 解析总文本长度约 `351908`
    - SQLite 文件仍仅约 `16 KB`
  - 新增本机数据目录：
    - 解析 artifact：[/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/.localdata/parsed](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/.localdata/parsed)
  - S1 前端解析摘要已展示：
    - 文本总长度
    - 解析警告
    - 文本预览
  - 已修复 S1 二次上传逻辑：
    - 首次上传招标文件并解析后
    - 再上传投标模板时，允许继续点击“上传并自动解析”
    - 后端会复用已上传的招标文件，追加模板文件，再重新解析

- 已修复 S9 空白页的 OnlyOffice 保存链路配置
  - 根因：OnlyOffice Docker 默认禁止私网地址请求，导致 `fileUrl/callbackUrl` 指向 `host.docker.internal` 时保存失败，前端随后白屏
  - 已在 [docker-compose.onlyoffice.yml](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/onlyoffice/docker-compose.onlyoffice.yml) 增加 `ALLOW_PRIVATE_IP_ADDRESS=true`
  - 已在 [start.sh](/Users/wlb/Agent/bid-project/code/sewpg-bid-frontend/start.sh) 和 [package.json](/Users/wlb/Agent/bid-project/code/sewpg-bid-frontend/package.json) 固定本机开发态 `ONLYOFFICE_BACKEND_BASE_URL=http://host.docker.internal:8000`
  - 当前 `GET /api/projects/PRJ-0001/document` 已返回可供 OnlyOffice 使用的 `host.docker.internal` 地址
  - 浏览器端已实测：S9 页面可编辑、保存、回写

- 已完成 `opencode` Docker 部署与 S2 真实接入
  - [docker-compose.yml](/Users/wlb/Agent/bid-project/code/docker-compose.yml) 已补 `opencode` 本机端口映射 `4096:4096`
  - `opencode` 容器启动时会复制本机 `~/.local/share/opencode/auth.json`
  - 新增配置：[opencode.json](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/opencode/opencode.json)
  - 新增轻量 skill：[bid-outline-json/SKILL.md](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/opencode/.opencode/skills/bid-outline-json/SKILL.md)
  - 新增后端 client：[opencode_client.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/services/opencode_client.py)
  - 新增目录生成服务：[outline_generation.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/services/outline_generation.py)
  - [directory.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/api/routes/directory.py) 已切到真实 `FastAPI -> opencode serve`
  - S2 当前策略已修正为：
    - 先读取投标模板目录线索
    - 再结合招标章节线索进行删改、补改
    - 输出前端 `S3` 可直接编辑的目录 JSON
  - 新增测试：[test_directory_generation.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/tests/test_directory_generation.py)
  - 后端测试当前 `9/9` 通过
  - 本机 smoke test 通过：
    - `http://127.0.0.1:4096/global/health`
    - `POST /session`
    - `POST /session/{id}/message`
    - `POST /api/projects/PRJ-0001/directory-generation/run`
    - `POST /api/projects/PRJ-0002/directory-generation/run`
  - `S3` 已能读取真实生成的目录树
  - `PRJ-0001` 已实测：
    - 目录根节点已按投标模板输出 `第1章 标前概述 / 第2章 技术标准 / 第3章 风资源评估与机位排布方案`
    - 不再是只看招标文本生成的通用目录

- 已完成 S4 / S5 / S6 mock 流程接入
  - 新增路由：
    - [gaps.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/api/routes/gaps.py)
    - [review.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/api/routes/review.py)
  - [router.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/api/router.py) 已纳入 S4/S5/S6 路由
  - [store.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/services/store.py) 已新增持久化状态：
    - `gap_state`
    - `review_document_state`
  - S4 当前逻辑：
    - 基于 `S3` 当前目录生成缺口 mock 数据
    - 缺口识别结果持久化到 SQLite
  - S5 当前逻辑：
    - 支持补料提交
    - 支持标记已补录 / 跳过
    - 支持提交至 S6 审核
  - S6 当前逻辑：
    - 支持生成审核预览文档
    - 支持返回 OnlyOffice 预览会话
    - 支持确认审核进入 S7
  - 新增测试：
    - [test_gap_review_flow.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/tests/test_gap_review_flow.py)
  - 后端全量测试当前 `10/10` 通过
  - 本机 smoke test 已通过：
    - `POST /api/projects/PRJ-0001/gaps-detection/run`
    - `GET /api/projects/PRJ-0001/gaps`
    - `POST /api/projects/PRJ-0001/materials/submissions`
    - `POST /api/projects/PRJ-0001/gaps/submit-review`
    - `POST /api/projects/PRJ-0001/review-items/prepare`
    - `GET /api/projects/PRJ-0001/review-items/document`
    - `POST /api/projects/PRJ-0001/review-items/confirm`

- 已完成 S7 真实初稿生成
  - 新增服务：[draft_generation.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/services/draft_generation.py)
  - 新增轻量 skill：[bid-draft-sections-json/SKILL.md](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/opencode/.opencode/skills/bid-draft-sections-json/SKILL.md)
  - [generation.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/api/routes/generation.py) 已切到真实 `FastAPI -> opencode serve`
  - [opencode_client.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/services/opencode_client.py) 已新增 `generate_draft_sections`
  - 当前 S7 逻辑：
    - 输入 `S1` 解析文本 + `S3` 已确认目录 + 模板章节线索 + `S6` 审核摘要
    - 调 `opencode` 生成章节 JSON
    - 后端把章节内容写成真实 `.docx`
    - S9 直接打开这份初稿
  - 当前生成策略：
    - 可泛化内容直接生成
    - 可核验事实改成 `【待补充：...】`
    - 用 `generationMode=generated / generated_with_placeholder / placeholder` 标记章节状态
  - 新增测试：
    - [test_fill_generation.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/tests/test_fill_generation.py)
  - 后端全量测试当前 `12/12` 通过
  - 本机最小烟测已通过：
    - `PRJ-0004` 从 `S1 -> S6` 走完后
    - `POST /api/projects/PRJ-0004/fill-generation/run` 返回 `200`
    - 真实生成了 [PRJ-0004.docx](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/.localdata/documents/PRJ-0004.docx)
    - `GET /api/projects/PRJ-0004/document` 已返回可供 S9 打开的真实会话

- 已完成 S8 mock 承接
  - 新增路由：[coverage.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/api/routes/coverage.py)
  - [store.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/services/store.py) 已新增覆盖树与问题清单计算
  - 当前 S8 逻辑：
    - 基于 `S7` 的 `generationMode`
    - 自动映射为 `full / partial / none`
    - 生成：
      - `tree`
      - `partialItems`
      - `noCoverItems`
  - 这样 `S7 -> S8 -> S9` 现在已经能继续走通

- 已补稳定性收口
  - `opencode` 默认超时已提高到 `600s`
  - [opencode_client.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/services/opencode_client.py) 已把 timeout 转成可读错误，不再直接冒成 500 栈
  - 前端 [index.js](/Users/wlb/Agent/bid-project/code/sewpg-bid-frontend/src/api/index.js) 已给：
    - `directory-generation/run`
    - `fill-generation/run`
    单独放宽超时

- 已完成外围模块正式承接
  - 后端新增外围路由：
    - [materials.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/api/routes/materials.py)
    - [audit.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/api/routes/audit.py)
    - [settings.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/api/routes/settings.py)
    - [export.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/api/routes/export.py)
  - 后端新增 [peripheral.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/app/services/peripheral.py)
    - 正式承接原始材料库、结构化素材、Wiki、审计日志、系统设置、导出校验
    - 当前采用轻量 fixture / mock-backed 状态，先保证前端页面可用与联调闭环
  - 新增测试：[test_peripheral_routes.py](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/tests/test_peripheral_routes.py)
  - 后端外围测试通过：
    - `raw materials`
    - `structured/wiki`
    - `audit/settings/export`

- 已完成文档口径更新
  - [sewpg-bid-frontend/README.md](/Users/wlb/Agent/bid-project/code/sewpg-bid-frontend/README.md) 已改为“正式 FastAPI + 外围模块已承接”口径
  - [sewpg-bid-backend/README.md](/Users/wlb/Agent/bid-project/code/sewpg-bid-backend/README.md) 已补外围模块分层说明
  - [10-API接口总览与契约说明.md](/Users/wlb/Agent/bid-project/code/sewpg-bid-frontend/docs/10-API接口总览与契约说明.md) 已修正正式入口与现状说明
  - [11-API字段级契约明细.md](/Users/wlb/Agent/bid-project/code/sewpg-bid-frontend/docs/11-API字段级契约明细.md) 已修正正式入口与全局说明

## 下一步

1. 把当前本机启动方式进一步收敛到完整 `docker compose`
2. 继续补齐非主链路 mock 或外围接口
3. 把 `opencode` 的部署配置收成用户可自行修改的口径
   - `baseUrl` 需要可配置
   - 外部模型 `apiKey` 需要可配置
   - `.env.example` / 部署文档 / Compose 保持一致

## 2026-04-27 11:32 上传弹窗与素材清洗排障

- 前端上传弹窗改为固定视口高度：头部与底部操作区固定，中间内容区滚动，已选文件列表限制高度，避免文件夹内文件过多时“确认上传”按钮被顶出屏幕。
- 排查素材清洗队列：Redis `bid:jobs` 队列为空，但 5 个素材停在 `pending`；worker 日志显示 `asyncpg` 连接跨 `asyncio.run()` event loop 复用导致 `cannot perform operation: another operation is in progress`。
- 后端清洗同步入口改为复用 worker 内同一个 event loop，避免 SQLAlchemy asyncpg 连接池跨 loop 使用。
- 已重新构建并重启 `web / fastapi / worker`。重新触发 `RAW-0017` 至 `RAW-0021` 清洗后，当前 6 个素材均为 `cleaned`，Redis 队列为 0，worker 未再出现 asyncpg 报错。

## 2026-04-27 11:45 素材与项目字段匹配检查

- 核查项目主数据与素材库：项目主数据目前在 SQLite，本地素材库在 PostgreSQL，二者尚未做强约束关联。
- 当前项目素材存在不一致：上传到 `项目素材/1/技术标` 的文件记录了 `projectId=1`，但系统项目编号是 `PRJ-xxxx`；当前没有独立“外部项目编号”字段。
- 当前客户素材存在口径差异：项目里有 `华能集团`，素材目录是 `客户素材/华能/技术标`，只能靠模糊/包含关系识别，不能算严格匹配。
- 修复上传弹窗的参数：指定目录上传时不再额外提交默认 `materialTier=standard`，让后端按目标目录推断 `客户素材/项目素材`，避免写错素材层级。
- 已校正本次已上传素材元数据：`RAW-0089` 至 `RAW-0093` 改为 `项目素材/projectId=1`，`RAW-0094` 改为 `客户素材/customerName=华能`。
- `npm run build` 通过，已重新 build 并 force recreate `web`。

## 2026-04-27 12:34 项目/客户身份统一与 AI Wiki 改造

改动目标：

- 统一项目、业主、素材库、Wiki 和 S2 目录 skill 的身份口径。
- 人仍然按 `通用素材 / 客户素材 / 项目素材` 管理文件；AI 读取 Wiki 时按标准身份字段过滤素材。
- 清洗后的 Word 作为 Wiki 建卡和后续 AI 使用的正式素材来源。

改动内容：

- 新增轻量身份层：
  - 项目返回 `identity`，包含 `projectId / projectCode / customerId / customerCanonicalName / customerAliases`。
  - 新建/编辑项目增加 `业务项目编号` 字段。
  - 客户名如 `华能 / 华能集团 / 中国华能` 统一归一到 `CUST-HUANENG / 华能集团`。
- 素材上传与查询：
  - `raw_files.ext_fields` 写入 `identityScope / materialScope / customerId / customerCanonicalName / customerAliases / projectCode`。
  - 客户筛选改为客户 ID/别名匹配；项目筛选改为 `projectId/projectCode` 匹配。
  - 指定三母目录上传文件夹时，保留原文件夹结构并按路径推断客户/项目/标类。
- Wiki 生成：
  - 卡片新增 `AI 检索身份` 和 Merge 身份字段。
  - 索引、目录骨架、装配规则写入身份匹配规则。
  - Wiki 生成优先使用已清洗 Word；PDF/Excel 源文件只要已有 `cleanedMinioKey`，也会进入 Wiki 卡片。
- S2 目录 skill：
  - manifest 增加 `projectIdentity`。
  - `export_wiki_from_api.py` 导出身份字段到 frontmatter。
  - `wiki_lookup.py` 读取身份字段。
  - `build_plan.py` 在目录生成前过滤 Wiki：通用素材可读，客户素材需客户命中，项目素材需项目编号命中。
- 数据修复：
  - 71 个历史素材已补齐身份字段。
  - 当前技术标 Wiki 已重建：60 张通用卡片、6 张华能客户卡片、5 张项目编号 `1` 卡片。

验证结果：

- `py_compile` 通过：
  - `identity.py`
  - `store.py`
  - `material_store.py`
  - `wiki_generation.py`
  - `outline_generation.py`
  - `export_wiki_from_api.py`
  - `wiki_lookup.py`
  - `build_plan.py`
  - `run_from_manifest.py`
- `.venv/bin/python -m pytest tests/test_wiki_generation.py tests/test_toc_skill_scripts.py` 通过，8 个测试全部通过。
- `npm run build` 通过。
- 已重新 build 并 force recreate：
  - `opencode`
  - `fastapi`
  - `worker`
  - `web`
- API 验证：
  - 项目列表返回 `identity`。
  - 客户素材返回 `identityScope=customer / customerId=CUST-HUANENG`。
  - Wiki 卡片包含 `identity_scope`、`customer_id`、`project_code`、`cleaned_file_name`。
  - 文件系统版 Wiki 导出后，`wiki_lookup --list-by-section` 可读到 6 个客户素材和 5 个项目素材身份字段。

遗留问题：

- 现有 `项目素材/1/技术标` 只会命中 `projectCode=1` 或招标解析出的项目编号 `1`。旧项目默认 `projectCode=PRJ-xxxx`，如要让某个旧项目使用这批项目素材，需要在项目信息里把业务项目编号改为 `1`。

## 2026-04-27 13:56 客户/项目选择式素材上传

改动目标：

- 用户上传客户素材、项目素材时不再手填客户名或项目编号。
- 前端改为“选择客户 / 选择项目”；系统把 `customerId / projectId / projectCode / projectName` 写入素材元数据。
- 项目素材目录统一使用系统项目 ID，例如 `项目素材/PRJ-0021/技术标`；业务编号保留为 `projectCode`，供 Wiki 和 AI 检索使用。

改动内容：

- `/api/customers/key-accounts` 返回 `CUST-*` 客户 ID、标准客户名和别名。
- 原始素材上传接口接收 `customerId / projectCode / projectName`。
- 素材入库时保留系统项目 ID，同时写入业务项目编号、项目名、客户 ID 和标准客户名。
- 素材库上传弹窗中，客户素材改为“选择客户”，项目素材改为“选择项目”；选择项目会自动带出所属客户、业务编号和项目名。
- 项目材料路径接口改为返回系统项目 ID 目录，避免继续生成 `项目素材/业务编号/...` 这种容易混淆的路径。

验证结果：

- `python3 -m py_compile` 通过：`materials.py / auth.py / projects.py / material_store.py`。
- `npm run build` 通过。
- `.venv/bin/python -m pytest tests/test_toc_skill_scripts.py tests/test_wiki_generation.py` 通过，8 个测试全部通过。
- 已重新 build 并 force recreate：`fastapi / worker / web`。
- API 冒烟：
  - `/api/customers/key-accounts` 返回 `CUST-HUANENG / CUST-DATANG / CUST-CHNENERGY`。
  - `/api/projects?pageSize=3` 返回项目 `identity`。
  - `/api/projects/PRJ-0021/materials-path` 返回 `项目素材/PRJ-0021/技术标`。

注意事项：

- 旧数据里的 `项目素材/1/技术标` 仍保留，不自动迁移；后续已改回以素材库项目 ID 为准，见下一条记录。

## 2026-04-27 14:49 素材库身份作为项目创建依据

改动目标：

- 改回“素材库为准”：投标项目列表只是工作单，客户/素材项目身份由素材库提供。
- 创建投标项目时选择素材库客户、素材库项目；同时保留普通客户、普通项目入口，由系统生成稳定 ID。
- 后续 Wiki/目录/AI 检索使用绑定到投标项目上的素材库身份，而不是把投标工作单的 `PRJ-*` 当素材项目。

改动内容：

- 新增 `/api/materials/identity-options`：
  - 返回素材库客户选项，当前包括 `CUST-HUANENG / CUST-DATANG / CUST-CHNENERGY`。
  - 返回素材库项目选项，当前从 `项目素材/...` 与文件身份字段汇总，现有项目素材为 `projectId=1`。
- 创建项目弹窗：
  - 客户来源改为 `素材库客户 / 普通客户`。
  - 素材项目来源改为 `素材库项目 / 普通项目`。
  - 选择素材库项目时写入 `materialProjectId / materialProjectCode / materialProjectName`。
  - 普通客户生成 `CUST-*`，普通项目生成 `MATPRJ-*`。
- 项目身份结构：
  - `id` 仍是投标工作单 ID，例如 `PRJ-0025`。
  - `identity.projectId` 改为素材库项目 ID，例如 `1` 或 `MATPRJ-*`。
  - `identity.workspaceProjectId / bidProjectId` 保留投标工作单 ID。
  - `/api/projects/{id}/materials-path` 返回素材库项目路径，例如 `项目素材/1/技术标` 或 `项目素材/MATPRJ-.../技术标`。
- 素材上传弹窗的“选择项目”改为读取素材库身份选项，不再读取投标项目列表。

验证结果：

- `python3 -m py_compile` 通过：`identity.py / store.py / material_store.py / materials.py / projects.py`。
- `npm run build` 通过。
- `.venv/bin/python -m pytest tests/test_toc_skill_scripts.py tests/test_wiki_generation.py` 通过，8 个测试全部通过。
- 已重新 build 并 force recreate：`fastapi / worker / web`。
- API 冒烟：
  - `/api/materials/identity-options?bidType=技术标` 返回 3 个客户、1 个素材库项目。
  - 普通客户 + 普通项目临时创建验证：生成 `CUST-C5CE12F7EB` 与 `MATPRJ-6D38EC5521`，材料路径为 `项目素材/MATPRJ-6D38EC5521/技术标`。
  - 素材库客户 + 素材库项目临时创建验证：`CUST-HUANENG + projectId=1`，材料路径为 `项目素材/1/技术标`。

注意事项：

- 当前素材库项目只有旧数据 `1`；后续如果要更清晰，需要在素材库侧补“素材项目管理/重命名/归属客户”能力，而不是从投标项目列表里倒推。

### 2026-04-27 14:55:31 post-commit 13b6d71

提交摘要：chore(runtime): wire redis worker runtime

变更文件：

- `code/.env.airgap.example`
- `code/.env.example`
- `code/docker-compose.yml`
- `code/sewpg-bid-backend/Dockerfile`
- `code/sewpg-bid-backend/app/core/config.py`
- `code/sewpg-bid-backend/app/services/job_queue.py`
- `code/sewpg-bid-backend/app/workers/redis_worker.py`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-05-01 21:39 S1 解析进度与 3.1 字段增强

变更摘要：

- S1 `/parse` 上传并解析改为记录真实后端进度，前端轮询展示进度条、步骤记录与 opencode 输出片段。
- 解析结果按 3.1 要求拆成确定字段表：评分细则、项目基础信息、风机核心参数、性能保证指标、环境适应性。
- 专题方案、供货范围、考核条款改为展示“是否有明确要求”及摘要/证据。
- 附表识别支持 markdown 空表和 Word 招标文件中“附表/副表”标题后的空表，并生成 `.docx` 到技术标工作区 `technical-workspace/appendices`。
- S1 opencode 调用继续使用 `bid-tender-structured-parser` skill；本地结构化结果会补齐 opencode 摘要里缺失的字段组、存在性判断和附表产物。

验证结果：

- `code/sewpg-bid-backend/.venv/bin/python -m pytest tests/test_parse_pipeline.py -q`：11 passed。
- `code/sewpg-bid-backend/.venv/bin/python -m pytest -q`：65 passed, 6 skipped。
- `code/sewpg-bid-frontend/npm run lint`：通过。
- `code/sewpg-bid-frontend/npm run build`：通过，保留既有 Vite chunk > 500KB 提示。
- `docker compose build opencode fastapi web`：通过。
- `docker compose up -d opencode fastapi worker web`：通过，FastAPI healthy。
- 真实 API 烟测：临时项目上传 markdown 招标文件，进度事件包含 `upload/extract/appendix/skill/opencode/complete`，评分项拆分为 2 条，附表 Word 生成到 `/data/documents/.../technical-workspace/appendices/`。

### 2026-04-27 14:55:49 post-commit 6cdeaa9

提交摘要：feat(material-store): add persisted materials and cleaning

变更文件：

- `code/initdb/01-init.sql`
- `code/sewpg-bid-backend/app/api/routes/auth.py`
- `code/sewpg-bid-backend/app/api/routes/materials.py`
- `code/sewpg-bid-backend/app/api/routes/projects.py`
- `code/sewpg-bid-backend/app/models/materials.py`
- `code/sewpg-bid-backend/app/services/identity.py`
- `code/sewpg-bid-backend/app/services/material_cleaning.py`
- `code/sewpg-bid-backend/app/services/material_store.py`
- `code/sewpg-bid-backend/app/services/peripheral.py`
- `code/sewpg-bid-backend/app/services/store.py`
- `code/sewpg-bid-backend/requirements.txt`
- `code/sewpg-bid-backend/tests/test_peripheral_routes.py`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-04-27 14:56:02 post-commit 07ec90e

提交摘要：feat(opencode-skills): refactor toc wiki and cleaner skills

变更文件：

- `code/sewpg-bid-backend/app/services/opencode_client.py`
- `code/sewpg-bid-backend/app/services/outline_generation.py`
- `code/sewpg-bid-backend/app/services/wiki_generation.py`
- `code/sewpg-bid-backend/opencode/.opencode/skills/bid-outline-json/SKILL.md`
- `code/sewpg-bid-backend/opencode/Dockerfile`
- `code/sewpg-bid-backend/opencode/docker-entrypoint.sh`
- `code/sewpg-bid-backend/opencode/opencode.json`
- `code/sewpg-bid-backend/opencode/skill/bid-business-wiki-material-builder/SKILL.md`
- `code/sewpg-bid-backend/opencode/skill/bid-outline-json/SKILL.md`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-wiki-material-builder/SKILL.md`
- `code/sewpg-bid-backend/opencode/skill/bid-toc-wiki-driven-v2/SKILL.md`
- `code/sewpg-bid-backend/opencode/skill/bid-toc-wiki-driven-v2/references/example_run.md`
- `code/sewpg-bid-backend/opencode/skill/bid-toc-wiki-driven-v2/scripts/build_plan.py`
- `code/sewpg-bid-backend/opencode/skill/bid-toc-wiki-driven-v2/scripts/export_wiki_from_api.py`
- `code/sewpg-bid-backend/opencode/skill/bid-toc-wiki-driven-v2/scripts/extract_attach.py`
- `code/sewpg-bid-backend/opencode/skill/bid-toc-wiki-driven-v2/scripts/extract_template.py`
- `code/sewpg-bid-backend/opencode/skill/bid-toc-wiki-driven-v2/scripts/extract_tender.py`
- `code/sewpg-bid-backend/opencode/skill/bid-toc-wiki-driven-v2/scripts/run_from_manifest.py`
- `code/sewpg-bid-backend/opencode/skill/bid-toc-wiki-driven-v2/scripts/wiki_lookup.py`
- `code/sewpg-bid-backend/opencode/skill/bid-toc-wiki-driven/SKILL.md`
- `code/sewpg-bid-backend/opencode/skill/bid-toc-wiki-driven/references/example_run.md`
- `code/sewpg-bid-backend/opencode/skill/bid-toc-wiki-driven/references/style_spec.md`
- `code/sewpg-bid-backend/opencode/skill/bid-toc-wiki-driven/scripts/build_plan.py`
- `code/sewpg-bid-backend/opencode/skill/bid-toc-wiki-driven/scripts/extract_attach.py`
- `code/sewpg-bid-backend/opencode/skill/bid-toc-wiki-driven/scripts/extract_template.py`
- `code/sewpg-bid-backend/opencode/skill/bid-toc-wiki-driven/scripts/extract_tender.py`
- `code/sewpg-bid-backend/opencode/skill/bid-toc-wiki-driven/scripts/gen_toc.py`
- `code/sewpg-bid-backend/opencode/skill/bid-toc-wiki-driven/scripts/wiki_lookup.py`
- `code/sewpg-bid-backend/opencode/skill/bid-wiki-bootstrap-json/SKILL.md`
- `code/sewpg-bid-backend/opencode/skill/bid-wiki-material-builder/SKILL.md`
- `code/sewpg-bid-backend/opencode/skill/bid-wiki-material-builder/references/card_template.md`
- `code/sewpg-bid-backend/opencode/skill/bid-wiki-material-builder/references/wiki_material_rules.md`
- `code/sewpg-bid-backend/opencode/skill/bid-wiki-material-builder/scripts/bootstrap_wiki.py`
- `code/sewpg-bid-backend/opencode/skill/bid-wiki-material-builder/scripts/check.py`
- `code/sewpg-bid-backend/opencode/skill/bid-wiki-material-builder/scripts/extract_headings.py`
- `code/sewpg-bid-backend/opencode/skill/bid-wiki-material-builder/scripts/parse_skeleton.py`
- `code/sewpg-bid-backend/opencode/skill/format-cleaner-v4/SKILL.md`
- `code/sewpg-bid-backend/opencode/skill/format-cleaner-v4/scripts/driver.py`
- `code/sewpg-bid-backend/opencode/skill/format-cleaner-v4/scripts/excel_to_word.py`
- `code/sewpg-bid-backend/opencode/skill/format-cleaner-v4/scripts/pdf_to_word.py`
- `code/sewpg-bid-backend/opencode/skill/format-cleaner-v4/scripts/word_cleaner.py`
- `code/sewpg-bid-backend/tests/test_directory_generation.py`
- `code/sewpg-bid-backend/tests/test_opencode_client.py`
- `code/sewpg-bid-backend/tests/test_toc_skill_scripts.py`
- `code/sewpg-bid-backend/tests/test_wiki_generation.py`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-04-27 14:56:11 post-commit 1cf5c15

提交摘要：feat(frontend-materials): reorganize materials workspace

变更文件：

- `code/sewpg-bid-frontend/src/App.jsx`
- `code/sewpg-bid-frontend/src/api/index.js`
- `code/sewpg-bid-frontend/src/components/layout/AppShell.jsx`
- `code/sewpg-bid-frontend/src/components/modals/AuditDetailModal.jsx`
- `code/sewpg-bid-frontend/src/components/modals/ProjectWizardModal.jsx`
- `code/sewpg-bid-frontend/src/components/shared/MaterialsViewSwitch.jsx`
- `code/sewpg-bid-frontend/src/components/shared/ProjectStageProgress.jsx`
- `code/sewpg-bid-frontend/src/components/shared/StageBreadcrumb.jsx`
- `code/sewpg-bid-frontend/src/pages/AuditLog.jsx`
- `code/sewpg-bid-frontend/src/pages/CoCreationEditor.jsx`
- `code/sewpg-bid-frontend/src/pages/CoverageHeatmap.jsx`
- `code/sewpg-bid-frontend/src/pages/DirectoryGeneration.jsx`
- `code/sewpg-bid-frontend/src/pages/GapFilling.jsx`
- `code/sewpg-bid-frontend/src/pages/GapRecognition.jsx`
- `code/sewpg-bid-frontend/src/pages/GenerateProgress.jsx`
- `code/sewpg-bid-frontend/src/pages/MaterialDB.jsx`
- `code/sewpg-bid-frontend/src/pages/MaterialReview.jsx`
- `code/sewpg-bid-frontend/src/pages/MaterialWiki.jsx`
- `code/sewpg-bid-frontend/src/pages/OutlineReview.jsx`
- `code/sewpg-bid-frontend/src/pages/ParseResult.jsx`
- `code/sewpg-bid-frontend/src/pages/ProjectCockpit.jsx`
- `code/sewpg-bid-frontend/src/pages/ProjectEntryRedirect.jsx`
- `code/sewpg-bid-frontend/src/pages/ProjectList.jsx`
- `code/sewpg-bid-frontend/src/pages/TenderReview.jsx`
- `code/sewpg-bid-frontend/src/utils/stageFlow.js`
- `code/sewpg-bid-frontend/src/utils/workspace.js`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-04-27 14:57:45 post-commit 2445c54

提交摘要：docs: align delivery and storage guidance

变更文件：

- `code/AGENT.md`
- `code/hooks/record-progress.sh`
- `code/progress.md`
- `"code/sewpg-bid-frontend/docs/10-API\346\216\245\345\217\243\346\200\273\350\247\210\344\270\216\345\245\221\347\272\246\350\257\264\346\230\216.md"`
- `"code/sewpg-bid-frontend/docs/11-API\345\255\227\346\256\265\347\272\247\345\245\221\347\272\246\346\230\216\347\273\206.md"`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-04-27 15:33:31 post-commit 560eeff

提交摘要：refactor(storage): migrate project state to postgres

变更文件：

- `.github/workflows/mvp-quality.yml`
- `README.md`
- `code/.env.airgap.example`
- `code/.env.example`
- `code/AGENT.md`
- `code/docker-compose.yml`
- `code/initdb/01-init.sql`
- `code/sewpg-bid-backend/app/api/routes/system.py`
- `code/sewpg-bid-backend/app/core/config.py`
- `code/sewpg-bid-backend/app/models/__init__.py`
- `code/sewpg-bid-backend/app/services/material_store.py`
- `code/sewpg-bid-backend/app/services/store.py`
- `code/sewpg-bid-backend/pytest.ini`
- `code/sewpg-bid-backend/requirements.txt`
- `code/sewpg-bid-backend/tests/conftest.py`
- `code/sewpg-bid-backend/tests/test_auth_routes.py`
- `code/sewpg-bid-backend/tests/test_directory_generation.py`
- `code/sewpg-bid-backend/tests/test_fill_generation.py`
- `code/sewpg-bid-backend/tests/test_gap_review_flow.py`
- `code/sewpg-bid-backend/tests/test_onlyoffice_document.py`
- `code/sewpg-bid-backend/tests/test_parse_pipeline.py`
- `code/sewpg-bid-backend/tests/test_peripheral_routes.py`
- `code/sewpg-bid-backend/tests/test_store_persistence.py`
- `code/sewpg-bid-frontend/src/components/modals/ProjectWizardModal.jsx`
- `code/sewpg-bid-frontend/src/pages/MaterialDB.jsx`
- `"doc/06-MVP\346\216\245\345\217\243\346\226\207\346\241\243.md"`
- `"doc/07-FastAPI\346\211\277\346\216\245\344\270\216\345\211\215\347\253\257\346\224\271\351\200\240.md"`
- `"doc/08-MVP\351\203\250\347\275\262\350\257\264\346\230\216.md"`
- `"doc/12-\346\225\260\346\215\256\345\255\230\345\202\250\344\270\216\347\264\240\346\235\220\345\272\223\346\225\260\346\215\256\350\257\264\346\230\216.md"`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-04-27 15:56:04 post-commit c93abb0

提交摘要：fix(ci): restore backend quality gate

变更文件：

- `.github/workflows/mvp-quality.yml`
- `code/sewpg-bid-backend/app/services/material_store.py`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-04-27 22:01:10 post-commit 6d4e9df

提交摘要：fix(s7): assemble large bid materials via skill

变更文件：

- `code/.env.airgap.example`
- `code/.env.example`
- `code/docker-compose.yml`
- `code/sewpg-bid-backend/app/api/routes/generation.py`
- `code/sewpg-bid-backend/app/core/config.py`
- `code/sewpg-bid-backend/app/services/draft_generation.py`
- `code/sewpg-bid-backend/app/services/opencode_client.py`
- `code/sewpg-bid-backend/app/services/store.py`
- `code/sewpg-bid-backend/app/services/tech_assembly.py`
- `code/sewpg-bid-backend/onlyoffice/docker-entrypoint.sh`
- `code/sewpg-bid-backend/opencode/Dockerfile`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-assembler/SKILL.md`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-assembler/references/heading_style.json`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-assembler/references/style_spec.md`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-assembler/scripts/_merger_core.py`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-assembler/scripts/_postprocessor_reference.py`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-assembler/scripts/build_assembly.py`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-assembler/scripts/cleaner.py`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-assembler/scripts/finalize.py`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-assembler/scripts/fix_invalid_headings.py`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-assembler/scripts/init_params.py`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-assembler/scripts/merger.py`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-assembler/scripts/merger_v1.py`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-assembler/scripts/numbering_fixer.py`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-assembler/scripts/officecli_adapter.py`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-assembler/scripts/parse_toc.py`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-assembler/scripts/preprocess.py`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-assembler/scripts/run_from_manifest.py`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-assembler/scripts/verify.py`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-assembler/tools/clean_master_numbering.py`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-assembler/tools/create_tech_master.py`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-assembler/tools/docx_xml.py`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-assembler/tools/render_docx.py`
- `code/sewpg-bid-backend/requirements.txt`
- `code/sewpg-bid-backend/tests/test_fill_generation.py`
- `code/sewpg-bid-backend/tests/test_gap_review_flow.py`
- `code/sewpg-bid-backend/tests/test_onlyoffice_document.py`
- `code/sewpg-bid-backend/tests/test_toc_skill_scripts.py`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-04-27 22:44:22 post-commit 266ae02

提交摘要：docs: align MVP delivery status

变更文件：

- `README.md`
- `code/AGENT.md`
- `code/plan.md`
- `code/progress.md`
- `code/scripts/build-airgap-bundle.ps1`
- `code/scripts/build-airgap-bundle.sh`
- `"code/sewpg-bid-api/MVP\346\216\245\345\217\243\344\270\216\345\217\202\346\225\260\346\240\270\345\277\203\347\211\210_\346\236\201\347\256\200\347\211\210.md"`
- `code/sewpg-bid-backend/README.md`
- `code/sewpg-bid-backend/app/api/routes/projects.py`
- `code/sewpg-bid-backend/app/services/outline_generation.py`
- `code/sewpg-bid-backend/app/services/peripheral.py`
- `code/sewpg-bid-backend/opencode/skill/bid-toc-wiki-driven-v2/SKILL.md`
- `code/sewpg-bid-backend/tests/test_directory_generation.py`
- `code/sewpg-bid-backend/tests/test_peripheral_routes.py`
- `"code/sewpg-bid-frontend/docs/10-API\346\216\245\345\217\243\346\200\273\350\247\210\344\270\216\345\245\221\347\272\246\350\257\264\346\230\216.md"`
- `"code/sewpg-bid-frontend/docs/11-API\345\255\227\346\256\265\347\272\247\345\245\221\347\272\246\346\230\216\347\273\206.md"`
- `code/sewpg-bid-frontend/src/pages/CoverageHeatmap.jsx`
- `code/sewpg-bid-frontend/src/pages/GapFilling.jsx`
- `code/sewpg-bid-frontend/src/pages/GenerateProgress.jsx`
- `"doc/01-\351\234\200\346\261\202\344\270\216\347\233\256\346\240\207.md"`
- `"doc/03-UI\350\256\276\350\256\241.md"`
- `"doc/04-\350\267\257\347\272\277\345\244\207\351\200\211\344\270\216\345\212\237\350\203\275\347\233\230\347\202\271.md"`
- `"doc/05-MVP\344\270\273\351\223\276\350\267\257\350\257\264\346\230\216.md"`
- `"doc/06-MVP\346\216\245\345\217\243\346\226\207\346\241\243.md"`
- `"doc/07-FastAPI\346\211\277\346\216\245\344\270\216\345\211\215\347\253\257\346\224\271\351\200\240.md"`
- `"doc/08-MVP\351\203\250\347\275\262\350\257\264\346\230\216.md"`
- `"doc/09-\344\272\214\351\230\266\346\256\265\345\210\206\345\267\245\344\270\216\347\254\254\344\270\200\345\221\250\351\207\214\347\250\213\347\242\221.md"`
- `"doc/10-\347\224\262\346\226\271\346\212\200\346\234\257\347\273\206\350\256\256\350\215\211\346\241\210-\345\220\210\345\220\214\351\242\204\346\234\237\346\234\200\347\273\210\344\272\244\344\273\230\347\211\210.md"`
- `"doc/11-\345\206\205\347\275\221\347\246\273\347\272\277\351\203\250\347\275\262\350\257\264\346\230\216.md"`
- `"doc/12-\346\225\260\346\215\256\345\255\230\345\202\250\344\270\216\347\264\240\346\235\220\345\272\223\346\225\260\346\215\256\350\257\264\346\230\216.md"`
- `"doc/13-S7\346\212\200\346\234\257\346\240\207\346\255\243\346\226\207\346\213\274\350\243\205\344\270\216S8\347\264\240\346\235\220\346\240\241\351\252\214\350\257\264\346\230\216.md"`
- `doc/README.md`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-04-27 22:44:49 post-commit d4f91de

提交摘要：docs: record delivery status commit

变更文件：

- `code/progress.md`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-05-01 14:41:55 post-commit 8d47514

提交摘要：fix(s7): keep material sub-headings out of word navigation

变更文件：

- `code/sewpg-bid-backend/app/services/tech_assembly.py`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-assembler/SKILL.md`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-assembler/scripts/merger.py`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-assembler/scripts/numbering_fixer.py`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-assembler/scripts/verify.py`
- `code/sewpg-bid-backend/tests/test_fill_generation.py`
- `code/sewpg-bid-backend/tests/test_toc_skill_scripts.py`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-05-01 14:42:53 post-commit 8e6108d

提交摘要：docs: reorder customer backlog by implementation difficulty

变更文件：

- `"doc/14-\347\224\262\346\226\271\346\226\260\345\242\236\351\234\200\346\261\202\345\276\205\345\212\236.md"`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-05-01 15:36:17 post-commit 4f8a115

提交摘要：docs(backlog): add S7 agent matching as new high-difficulty item

变更文件：

- `"doc/14-\347\224\262\346\226\271\346\226\260\345\242\236\351\234\200\346\261\202\345\276\205\345\212\236.md"`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-05-01 16:17:29 post-commit 3c96d92

提交摘要：fix(web): resolve stale compose upstream dns

变更文件：

- `code/sewpg-bid-frontend/nginx.conf`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-05-01 16:17:35 post-commit e9c7547

提交摘要：docs: consolidate bid requirements backlog

变更文件：

- `"doc/14-\347\224\262\346\226\271\346\226\260\345\242\236\351\234\200\346\261\202\345\276\205\345\212\236.md"`
- `"doc/15-\346\212\200\346\234\257\346\240\207\344\270\216\345\225\206\345\212\241\346\240\207\351\234\200\346\261\202\346\225\264\347\220\206.md"`
- `doc/README.md`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-05-01 16:24:01 post-commit 802a3c1

提交摘要：docs: simplify requirements backlog

变更文件：

- `"doc/14-\347\224\262\346\226\271\346\226\260\345\242\236\351\234\200\346\261\202\345\276\205\345\212\236.md"`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-05-01 16:52:49 手动记录：待办推进规则更新

改动目标：

- 从现在开始按 `doc/14-甲方新增需求待办.md` 的待办清单推进。
- 待办清单增加“完成情况”列，完成一项即在文档中勾选。
- 每完成或推进一项待办，同步在本文件记录进度。

变更文件：

- `doc/14-甲方新增需求待办.md`
- `code/progress.md`

验证结果：

- 文档结构调整，无代码验证。

### 2026-05-01 17:00:09 手动记录：neat-freak 文档与记忆同步

改动目标：

- 把项目根 README、agent 执行说明、历史联调计划和子项目 README 同步到当前口径：后续按 `doc/14-甲方新增需求待办.md` 推进。
- 明确待办完成后需要勾选“完成情况”，并同步记录到本文件。
- 更新 Codex 记忆，避免后续会话继续把旧 MVP 联调计划当作下一阶段待办。

变更文件：

- `README.md`
- `code/AGENT.md`
- `code/plan.md`
- `code/sewpg-bid-backend/README.md`
- `code/sewpg-bid-frontend/README.md`
- `doc/README.md`
- `/Users/wlb/.codex/memories/MEMORY.md`
- `/Users/wlb/.codex/memories/memory_summary.md`
- `code/progress.md`

验证结果：

- 文档与记忆同步，无代码验证。

### 2026-05-01 17:04:59 手动记录：doc 目录清理与新会话规则

改动目标：

- 清理 `doc/` 入口，把早期设计、路线讨论、迁移方案和阶段分工资料移入 `doc/archive/`。
- 重写 `doc/README.md`，让新会话先看 `doc/14`、`doc/15`、根 README 和当前运行基线。
- 记录用户的新协作规则：准备开始逐项做待办清单，每个待办默认开新会话。

变更文件：

- `doc/README.md`
- `doc/archive/README.md`
- `doc/archive/01-需求与目标.md`
- `doc/archive/02-技术选型与架构.md`
- `doc/archive/03-UI设计.md`
- `doc/archive/04-路线备选与功能盘点.md`
- `doc/archive/07-FastAPI承接与前端改造.md`
- `doc/archive/09-二阶段分工与第一周里程碑.md`
- `doc/14-甲方新增需求待办.md`
- `README.md`
- `code/AGENT.md`
- `code/sewpg-bid-api/README.md`
- `code/progress.md`

验证结果：

- 文档整理，无代码验证。

### 2026-05-01 17:10:23 post-commit 243ddcf

提交摘要：Organize doc archive and backlog workflow

变更文件：

- `README.md`
- `code/AGENT.md`
- `code/plan.md`
- `code/progress.md`
- `code/sewpg-bid-api/README.md`
- `code/sewpg-bid-backend/README.md`
- `code/sewpg-bid-frontend/README.md`
- `"doc/01-\351\234\200\346\261\202\344\270\216\347\233\256\346\240\207.md"`
- `"doc/02-\346\212\200\346\234\257\351\200\211\345\236\213\344\270\216\346\236\266\346\236\204.md"`
- `"doc/03-UI\350\256\276\350\256\241.md"`
- `"doc/04-\350\267\257\347\272\277\345\244\207\351\200\211\344\270\216\345\212\237\350\203\275\347\233\230\347\202\271.md"`
- `"doc/07-FastAPI\346\211\277\346\216\245\344\270\216\345\211\215\347\253\257\346\224\271\351\200\240.md"`
- `"doc/09-\344\272\214\351\230\266\346\256\265\345\210\206\345\267\245\344\270\216\347\254\254\344\270\200\345\221\250\351\207\214\347\250\213\347\242\221.md"`
- `"doc/14-\347\224\262\346\226\271\346\226\260\345\242\236\351\234\200\346\261\202\345\276\205\345\212\236.md"`
- `doc/README.md`
- `"doc/archive/01-\351\234\200\346\261\202\344\270\216\347\233\256\346\240\207.md"`
- `"doc/archive/02-\346\212\200\346\234\257\351\200\211\345\236\213\344\270\216\346\236\266\346\236\204.md"`
- `"doc/archive/03-UI\350\256\276\350\256\241.md"`
- `"doc/archive/04-\350\267\257\347\272\277\345\244\207\351\200\211\344\270\216\345\212\237\350\203\275\347\233\230\347\202\271.md"`
- `"doc/archive/07-FastAPI\346\211\277\346\216\245\344\270\216\345\211\215\347\253\257\346\224\271\351\200\240.md"`
- `"doc/archive/09-\344\272\214\351\230\266\346\256\265\345\210\206\345\267\245\344\270\216\347\254\254\344\270\200\345\221\250\351\207\214\347\250\213\347\242\221.md"`
- `doc/archive/README.md`
- `tmp/active-projects-20260427-230500.txt`
- `tmp/bid-project-snapshot-20260427-230500.tar.gz`
- `"tmp/docx_pdf/10-\347\224\262\346\226\271\346\212\200\346\234\257\347\273\206\350\256\256\350\215\211\346\241\210-\345\220\210\345\220\214\351\242\204\346\234\237\346\234\200\347\273\210\344\272\244\344\273\230\347\211\210.pdf"`
- `tmp/export_contract_docx.py`
- `tmp/orphan-before-documents-20260427-230500.txt`
- `tmp/orphan-before-parsed-20260427-230500.txt`
- `tmp/orphan-before-uploads-20260427-230500.txt`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-05-01 17:11:43 手动记录：待办 1 清理旧 mock/demo 资产

改动目标：

- 完成 `doc/14-甲方新增需求待办.md` 序号 1。
- 清理前端历史 `mock-server`、`legacy/fastapi-mock` 残留目录。
- 清理后端不再进入当前运行路径的 opencode FastAPI Word Skill demo。
- 清理 OnlyOffice 独立 demo、smoke、样例文件、历史 compose、运行数据和日志，仅保留当前 Docker Compose 需要的 `docker-entrypoint.sh`。
- 增加后端 `.dockerignore`，避免旧 demo 和本地运行产物重新进入 Docker build context。

变更文件：

- `doc/14-甲方新增需求待办.md`
- `code/progress.md`
- `code/AGENT.md`
- `code/sewpg-bid-backend/README.md`
- `code/sewpg-bid-backend/.dockerignore`
- `code/sewpg-bid-backend/onlyoffice/README.md`
- `code/sewpg-bid-backend/opencode/opencode-fastapi-word-skill-demo/`
- `code/sewpg-bid-frontend/mock-server/`
- `code/sewpg-bid-frontend/legacy/`

验证结果：

- 静态引用检查：无正式前后端代码引用已删除的 demo/smoke 入口。
- `docker compose config --quiet`：通过。
- `npm run build`：通过。
- `python -m pytest`：56 passed, 6 skipped。

### 2026-05-01 17:19:04 手动记录：待办 2 OnlyOffice 左右布局与全屏

改动目标：

- 完成 `doc/14-甲方新增需求待办.md` 序号 2。
- 抽取统一的 `OnlyOfficeWorkspace` 工作台组件，提供左侧上下文、右侧文档和全屏/退出全屏开关。
- S3 目录审核、S6 解析文档预览、S9 共创编辑统一接入左右布局。
- 全屏状态支持 Esc 退出，并在全屏时锁定页面滚动。

变更文件：

- `doc/14-甲方新增需求待办.md`
- `code/progress.md`
- `code/sewpg-bid-frontend/src/components/shared/OnlyOfficeWorkspace.jsx`
- `code/sewpg-bid-frontend/src/pages/OutlineReview.jsx`
- `code/sewpg-bid-frontend/src/pages/MaterialReview.jsx`
- `code/sewpg-bid-frontend/src/pages/CoCreationEditor.jsx`

验证结果：

- `npm run lint`：通过。
- `npm run build`：通过。

### 2026-05-01 17:26:35 手动记录：前端 Docker web 重新部署

改动目标：

- 用户反馈浏览器中未看到 OnlyOffice 布局变化后，确认此前只启动了 Vite 开发服务，Docker `sewpg_bid_web` 仍是旧镜像。
- 重新构建并重启 compose 中的 `web` 服务，让正式入口 `http://127.0.0.1/` 也加载待办 2 的前端改动。

变更文件：

- `code/progress.md`

验证结果：

- `docker compose build web && docker compose up -d web`：通过。
- `sewpg_bid_web`：已重启并运行。
- `http://127.0.0.1/`：返回新前端 bundle `index-0YSUo2CI.js`。

### 2026-05-01 17:29:48 手动记录：待办完成后的部署与提交规则

改动目标：

- 记录用户新规则：以后每完成一项待办，都要重新部署相关服务给用户检查。
- 涉及前端展示的改动，至少要重建并重启 compose 的 `web` 服务，不能只启动 Vite 开发服务。
- 每完成一项待办后，同步创建一次 git commit，保持一项待办一个提交的节奏。

变更文件：

- `code/AGENT.md`
- `doc/README.md`
- `code/progress.md`

验证结果：

- 文档规则更新，无代码验证。

### 2026-05-01 17:22:45 post-commit 919ce2e

提交摘要：chore: complete backlog items 1 & 2 — clean old demos, OnlyOffice layout

变更文件：

- `code/AGENT.md`
- `code/progress.md`
- `code/sewpg-bid-backend/.dockerignore`
- `code/sewpg-bid-backend/README.md`
- `code/sewpg-bid-backend/onlyoffice/README.md`
- `code/sewpg-bid-backend/onlyoffice/data/.private/ds_release_date`
- `code/sewpg-bid-backend/onlyoffice/docker-compose.onlyoffice.yml`
- `code/sewpg-bid-backend/onlyoffice/files/sample.docx`
- `code/sewpg-bid-backend/onlyoffice/frontend_bridge_reference.md`
- `code/sewpg-bid-backend/onlyoffice/onlyoffice_demo_backend.py`
- `code/sewpg-bid-backend/onlyoffice/requirements.txt`
- `code/sewpg-bid-backend/onlyoffice/smoke_test.html`
- `code/sewpg-bid-backend/opencode/opencode-fastapi-word-skill-demo/README.md`
- `code/sewpg-bid-backend/opencode/opencode-fastapi-word-skill-demo/app/__init__.py`
- `code/sewpg-bid-backend/opencode/opencode-fastapi-word-skill-demo/app/main.py`
- `code/sewpg-bid-backend/opencode/opencode-fastapi-word-skill-demo/requirements.txt`
- `code/sewpg-bid-frontend/src/components/shared/OnlyOfficeWorkspace.jsx`
- `code/sewpg-bid-frontend/src/pages/CoCreationEditor.jsx`
- `code/sewpg-bid-frontend/src/pages/MaterialReview.jsx`
- `code/sewpg-bid-frontend/src/pages/OutlineReview.jsx`
- `"doc/14-\347\224\262\346\226\271\346\226\260\345\242\236\351\234\200\346\261\202\345\276\205\345\212\236.md"`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-05-01 17:22:58 post-commit f28e5bb

提交摘要：docs: add post-commit progress record for items 1 & 2

变更文件：

- `code/progress.md`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-05-01 17:23:06 post-commit ddd95b0

提交摘要：docs: update progress log

变更文件：

- `code/progress.md`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-05-01 17:23:16 post-commit 27312d1

提交摘要：docs: sync progress log

变更文件：

- `code/progress.md`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-05-01 17:47:18 手动记录：撤回待办 3 目录模板沉淀实现

改动目标：

- 撤回 `258a131 feat: add technical bid directory templates` 和 `723d6be docs: record directory template progress`。
- 将 `doc/14-甲方新增需求待办.md` 序号 3 恢复为未完成。
- 删除本次新增的内置通用/华能目录模板沉淀逻辑，恢复 S2 目录生成 skill 原有职责边界。

撤回原因：

- 当前 `bid-toc-wiki-driven-v2` 已负责读取招标文件、投标文件和素材 Wiki，并输出目录 JSON。
- 内置目录模板沉淀会把目录结构配置写死到后端/skill，和当前“由 Skill 根据输入文件与 Wiki 生成目录”的方向不一致。
- 真正有价值的下一项是待办 4：当用户不上传投标模板时，给 S2/S7 提供 fallback 模板文件来源。

验证计划：

- `.venv/bin/python -m pytest tests/test_directory_generation.py tests/test_toc_skill_scripts.py`：24 passed。
- `.venv/bin/python -m py_compile app/services/outline_generation.py opencode/skill/bid-toc-wiki-driven-v2/scripts/build_plan.py opencode/skill/bid-toc-wiki-driven-v2/scripts/run_from_manifest.py`：通过。
- `docker compose build fastapi worker opencode && docker compose up -d fastapi worker opencode`：通过。
- `docker compose ps fastapi worker opencode`：`fastapi`、`opencode` healthy，`worker` 已启动。
- `GET http://127.0.0.1/api/healthz`：返回 `status=ok`。
- 容器内验证：`app.services.directory_templates` 不存在；`bid-toc-wiki-driven-v2` 中无 `directoryTemplates / directory_template` 残留。

### 2026-05-01 17:50:35 手动记录：删除无效的目录模板沉淀待办

改动目标：

- 从 `doc/14-甲方新增需求待办.md` 删除原序号 3“技术标通用/华能目录模板沉淀”。
- 将后续待办重新编号，原“模板上传 Fallback 读取”成为新的序号 3。
- 在 `doc/15-技术标与商务标需求整理.md` 中同步口径：不单独沉淀目录模板，目录仍由 S2 Skill 基于招标文件、投标模板和 Wiki 生成；后续重点是未上传投标模板时读取 fallback 模板。

验证结果：

- 文档清理，无代码变更。

### 2026-05-01 18:06:21 post-commit e238a55

提交摘要：feat: add fallback bid template source

变更文件：

- `code/.env.example`
- `code/docker-compose.yml`
- `code/progress.md`
- `code/sewpg-bid-backend/app/api/routes/parse.py`
- `code/sewpg-bid-backend/app/api/routes/projects.py`
- `code/sewpg-bid-backend/app/services/store.py`
- `code/sewpg-bid-backend/app/services/template_store.py`
- `code/sewpg-bid-backend/tests/test_parse_pipeline.py`
- `code/sewpg-bid-frontend/src/api/index.js`
- `code/sewpg-bid-frontend/src/pages/ParseResult.jsx`
- `"doc/14-\347\224\262\346\226\271\346\226\260\345\242\236\351\234\200\346\261\202\345\276\205\345\212\236.md"`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-05-01 18:06:44 post-commit 7913aaf

提交摘要：feat: add fallback bid template source

变更文件：

- `code/.env.example`
- `code/docker-compose.yml`
- `code/progress.md`
- `code/sewpg-bid-backend/app/api/routes/parse.py`
- `code/sewpg-bid-backend/app/api/routes/projects.py`
- `code/sewpg-bid-backend/app/services/store.py`
- `code/sewpg-bid-backend/app/services/template_store.py`
- `code/sewpg-bid-backend/tests/test_parse_pipeline.py`
- `code/sewpg-bid-frontend/src/api/index.js`
- `code/sewpg-bid-frontend/src/pages/ParseResult.jsx`
- `"doc/14-\347\224\262\346\226\271\346\226\260\345\242\236\351\234\200\346\261\202\345\276\205\345\212\236.md"`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-05-01 20:08:08 post-commit 03d1f19

提交摘要：feat: preview cleaned materials with onlyoffice

变更文件：

- `code/progress.md`
- `code/sewpg-bid-backend/app/api/routes/materials.py`
- `code/sewpg-bid-backend/app/services/material_store.py`
- `code/sewpg-bid-backend/tests/test_onlyoffice_document.py`
- `code/sewpg-bid-frontend/src/api/index.js`
- `code/sewpg-bid-frontend/src/pages/MaterialDB.jsx`
- `"doc/14-\347\224\262\346\226\271\346\226\260\345\242\236\351\234\200\346\261\202\345\276\205\345\212\236.md"`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-05-01 20:57:06 post-commit 5ec4384

提交摘要：Fix OnlyOffice fullscreen and folder loading

变更文件：

- `code/sewpg-bid-backend/app/api/routes/materials.py`
- `code/sewpg-bid-backend/app/services/material_store.py`
- `code/sewpg-bid-backend/app/services/peripheral.py`
- `code/sewpg-bid-frontend/src/components/shared/OnlyOfficeWorkspace.jsx`
- `code/sewpg-bid-frontend/src/pages/MaterialDB.jsx`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-05-01 21:13:06 post-commit cfe4488

提交摘要：feat: add structured tender parsing and project dates

变更文件：

- `code/docker-compose.yml`
- `code/progress.md`
- `code/sewpg-bid-backend/app/api/routes/projects.py`
- `code/sewpg-bid-backend/app/core/config.py`
- `code/sewpg-bid-backend/app/services/opencode_client.py`
- `code/sewpg-bid-backend/app/services/parsing.py`
- `code/sewpg-bid-backend/app/services/store.py`
- `code/sewpg-bid-backend/opencode/Dockerfile`
- `code/sewpg-bid-backend/opencode/skill/bid-tender-structured-parser/SKILL.md`
- `code/sewpg-bid-backend/opencode/skill/bid-tender-structured-parser/scripts/run_from_manifest.py`
- `code/sewpg-bid-backend/tests/test_parse_pipeline.py`
- `code/sewpg-bid-frontend/src/components/modals/ProjectWizardModal.jsx`
- `code/sewpg-bid-frontend/src/pages/ParseResult.jsx`
- `code/sewpg-bid-frontend/src/pages/ProjectCockpit.jsx`
- `code/sewpg-bid-frontend/src/pages/ProjectList.jsx`
- `code/sewpg-bid-frontend/src/pages/TenderReview.jsx`
- `"doc/14-\347\224\262\346\226\271\346\226\260\345\242\236\351\234\200\346\261\202\345\276\205\345\212\236.md"`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-05-01 21:40:20 post-commit 3f986b3

提交摘要：feat: stream parse progress and appendix extraction

变更文件：

- `code/progress.md`
- `code/sewpg-bid-backend/app/api/routes/parse.py`
- `code/sewpg-bid-backend/app/services/opencode_client.py`
- `code/sewpg-bid-backend/app/services/parsing.py`
- `code/sewpg-bid-backend/app/services/store.py`
- `code/sewpg-bid-backend/opencode/skill/bid-tender-structured-parser/scripts/run_from_manifest.py`
- `code/sewpg-bid-backend/tests/test_parse_pipeline.py`
- `code/sewpg-bid-frontend/src/api/index.js`
- `code/sewpg-bid-frontend/src/pages/TenderReview.jsx`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-05-01 22:28:25 S1 招标解析结构化增强

- 将 S1 解析核心抽到 `bid-tender-structured-parser/scripts/parser_core.py`，后端本地解析和 opencode `s1parse` 共用同一套规则。
- 新增多文件 Word 表格解析契约：`sourceDocuments`、分组 `scoringCriteria`、固定字段 `fieldGroups`、存在性 `requirementPresence`、覆盖度 `coverage` 与项目日期。
- 前端解析结果改为分表展示技术评分、商务评分、报价评分、度电成本、符合性审查，并保留来源/章节/证据位置。
- 真实华能两份招标文件本地解析烟测：技术评分 18 条、商务评分 11 条、报价 2 条、度电成本 1 条、符合性审查 13 条；风机核心参数从“招标机型要求/风资源情况”提取。
- 已重建并启动 `opencode / fastapi / worker / web`，容器内 `s1parse` 烟测通过。

验证：

- `./.venv/bin/python -m pytest -q`：67 passed, 6 skipped。
- `npm run lint`：通过。
- `npm run build`：通过，保留 Vite chunk >500KB 既有警告。
- `docker compose build opencode fastapi web`：通过。
- `docker compose up -d opencode fastapi worker web`：通过。
- `docker compose exec -T opencode ... s1parse ...`：通过。

### 2026-05-01 22:51:10 S1 附表 Word 与 OnlyOffice 预览调整

- 附表识别改为仅匹配明确“附表/副表/技术附表”标题，避免正文句子误入附表清单。
- 所有识别到的附表条目都会生成 Word；没有空表样例时生成仅含标题的空 Word，并对历史 `required_no_template` 结果做读取时补齐。
- 新增 S1 附表 OnlyOffice 预览 API，前端附表区改为左侧条目列表、右侧 OnlyOffice 预览框，不再显示“待处理/已生成 Word”状态列。

验证：

- `./.venv/bin/python -m pytest tests/test_parse_pipeline.py -q`：15 passed。
- `./.venv/bin/python -m pytest -q`：69 passed, 6 skipped。
- `npm run lint`：通过。
- `npm run build`：通过，保留 Vite chunk >500KB 既有警告。
- `docker compose build fastapi worker web && docker compose up -d --force-recreate fastapi worker web`：通过。
- 浏览器验证 `http://127.0.0.1/parse`：附表 159 个，状态列消失，左侧条目 + 右侧 OnlyOffice 预览 iframe 可见。

### 2026-05-02 12:51:52 post-commit 4b36b7e

提交摘要：Refine tech bid workflow with real gap planning

变更文件：

- `code/progress.md`
- `code/sewpg-bid-backend/app/api/routes/parse.py`
- `code/sewpg-bid-backend/app/services/onlyoffice_documents.py`
- `code/sewpg-bid-backend/app/services/parsing.py`
- `code/sewpg-bid-backend/app/services/store.py`
- `code/sewpg-bid-backend/app/services/workspace_artifacts.py`
- `code/sewpg-bid-backend/opencode/skill/bid-tender-structured-parser/SKILL.md`
- `code/sewpg-bid-backend/opencode/skill/bid-tender-structured-parser/scripts/parser_core.py`
- `code/sewpg-bid-backend/opencode/skill/bid-tender-structured-parser/scripts/run_from_manifest.py`
- `code/sewpg-bid-backend/tests/test_onlyoffice_document.py`
- `code/sewpg-bid-backend/tests/test_parse_pipeline.py`
- `code/sewpg-bid-frontend/src/api/index.js`
- `code/sewpg-bid-frontend/src/index.css`
- `code/sewpg-bid-frontend/src/pages/ParseResult.jsx`
- `code/sewpg-bid-frontend/src/pages/TenderReview.jsx`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-05-02 13:25:19 post-commit 84d4a20

提交摘要：Implement tech bid gap planning workflow

变更文件：

- `code/progress.md`
- `code/sewpg-bid-backend/app/api/routes/gaps.py`
- `code/sewpg-bid-backend/app/services/gap_planning.py`
- `code/sewpg-bid-backend/app/services/opencode_client.py`
- `code/sewpg-bid-backend/app/services/store.py`
- `code/sewpg-bid-backend/app/services/tech_assembly.py`
- `code/sewpg-bid-backend/opencode/Dockerfile`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-assembler/scripts/build_assembly.py`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-assembler/scripts/run_from_manifest.py`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-gap-planner/SKILL.md`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-gap-planner/scripts/run_from_manifest.py`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-table-filler/SKILL.md`
- `code/sewpg-bid-backend/opencode/skill/bid-tech-table-filler/scripts/run_from_manifest.py`
- `code/sewpg-bid-backend/tests/test_fill_generation.py`
- `code/sewpg-bid-backend/tests/test_gap_review_flow.py`
- `code/sewpg-bid-backend/tests/test_onlyoffice_document.py`
- `code/sewpg-bid-frontend/src/App.jsx`
- `code/sewpg-bid-frontend/src/api/index.js`
- `code/sewpg-bid-frontend/src/pages/GapRecognition.jsx`
- `code/sewpg-bid-frontend/src/pages/ParseResult.jsx`
- `code/sewpg-bid-frontend/src/utils/stageFlow.js`
- `"doc/14-\347\224\262\346\226\271\346\226\260\345\242\236\351\234\200\346\261\202\345\276\205\345\212\236.md"`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-05-02 13:25:38 post-commit 33c3b66

提交摘要：Record tech bid gap workflow progress

变更文件：

- `code/progress.md`

验证结果：提交后自动记录，需结合提交前测试记录确认。

### 2026-05-02 13:39:34 待办 12/15 联合改造收尾审计

- S4 缺口识别补齐读取 S2 目录生成产物中的 Wiki 卡片：当人工确认目录没有 `material_refs` 时，`bid-tech-gap-planner` 会按 Wiki frontmatter 的 `skeleton_section` 匹配素材。
- S5/S6 缺口页上传改为浏览器读取真实文件 Data URL 后提交；后端对 `.docx` Data URL 保存原始 Word 字节并挂回 `gapPlan.resolvedArtifacts`，S7 可直接读取该路径拼接。
- 保留纯文本上传兼容路径，用于测试或非 Word 输入生成可预览的补料 Word。

验证：

- `python3 -m py_compile app/services/gap_planning.py opencode/skill/bid-tech-gap-planner/scripts/run_from_manifest.py`：通过。
- `./.venv/bin/python -m pytest tests/test_gap_review_flow.py tests/test_fill_generation.py tests/test_onlyoffice_document.py -q`：26 passed。
- `./.venv/bin/python -m pytest -q`：81 passed, 6 skipped。
- `npm run lint`：通过。
- `npm run build`：通过。
- `docker compose build opencode fastapi worker web`：通过。
- `docker compose up -d --force-recreate opencode fastapi worker web`：通过，`fastapi` healthy。
- `curl -fsS http://127.0.0.1/api/healthz`：返回 `status=ok`。
- `curl -fsS -o /tmp/bid-web-home.html -w '%{http_code}' http://127.0.0.1/`：200。
- `docker compose exec -T opencode sh -lc 'command -v s4gap && command -v s4fill && command -v s7assemble'`：三个命令存在。
- 容器内 `s4gap` 最小 Wiki 卡片匹配烟测：输出 `matched wiki`。
- 容器内 `s4fill` 最小填写烟测：生成 `out.docx`，首段为“性能保证附表”。

### 2026-05-02 13:52:37 待办 12/15 完成审计补齐

- 完成审计时发现“缺口页选择已有素材 / AI 填写人工指定参考素材”已有计划但缺少前端主流程入口。
- 缺口页新增素材库搜索、勾选和“挂回缺口”能力；后端新增 `POST /api/projects/{projectId}/gaps/{gapId}/select-material`。
- 选择已有素材时，后端从真实素材库清洗稿或原始 Word 下载到项目 S4 工作目录，并以 `source=material_library` 挂回 `gapPlan.resolvedArtifacts`，确保 S7 可按真实 `path` 拼接。
- AI 填写会优先使用人工勾选的素材 ID 作为 `referenceMaterialIds`，未勾选时才 fallback 到已匹配素材。

验证：

- `python3 -m py_compile app/services/gap_planning.py app/services/store.py app/api/routes/gaps.py`：通过。
- `./.venv/bin/python -m pytest tests/test_gap_review_flow.py tests/test_fill_generation.py tests/test_onlyoffice_document.py -q`：27 passed。
- `./.venv/bin/python -m pytest -q`：82 passed, 6 skipped。
- `npm run lint && npm run build`：通过，保留既有 Vite chunk size warning。
- `docker compose build fastapi worker web`：通过。
- `docker compose up -d --force-recreate fastapi worker web`：通过，`fastapi` healthy。
- `curl -fsS http://127.0.0.1/api/healthz`：返回 `status=ok`。
- `curl -fsS -o /tmp/bid-web-home.html -w '%{http_code}' http://127.0.0.1/`：200。
- `docker compose exec -T opencode sh -lc 'command -v s4gap && command -v s4fill && command -v s7assemble'`：三个命令存在。

### 2026-05-02 14:04:56 待办 12/15 S4 OpenCode 调用审计补齐

- 完成最终审计时发现 S4 缺口识别虽已沉淀为 `bid-tech-gap-planner` Skill，但后端入口仍直接跑本地 runner。
- `run_gap_planner_skill` 已改为 OpenCode-first：先调用 `OpencodeClient.run_bid_tech_gap_planner_with_trace()`，prompt 明确要求使用 `bid-tech-gap-planner` 并执行 `s4gap <manifest>`。
- 保留本地 runner fallback，用于离线测试或 OpenCode 服务异常时生成同一份 `bid-tech-gap-plan-v1` 契约。
- `OpencodeClient` 新增 S4 缺口识别 session、返回 JSON 校验和 repair schema，和 S4 AI 填写、S7 正文拼装的调用形态保持一致。
- 测试补齐 S4 缺口识别 OpenCode-first 行为，并在相关后端测试中 mock OpenCode 调用，避免测试套件依赖外部模型服务。

验证：

- `python3 -m py_compile code/sewpg-bid-backend/app/services/gap_planning.py code/sewpg-bid-backend/app/services/opencode_client.py`：通过。
- `python3 -m py_compile code/sewpg-bid-backend/app/services/store.py`：通过。
- `./.venv/bin/python -m pytest tests/test_gap_review_flow.py tests/test_fill_generation.py tests/test_onlyoffice_document.py tests/test_opencode_client.py -q`：34 passed。
- `./.venv/bin/python -m pytest -q`：83 passed, 6 skipped。
- `npm run lint && npm run build`：通过，保留既有 Vite chunk size warning。
- `docker compose build fastapi worker`：通过。
- `docker compose up -d --force-recreate fastapi worker`：通过，`fastapi` healthy。
- `curl -fsS http://127.0.0.1/api/healthz`：返回 `status=ok`。
- `curl -fsS -o /tmp/bid-web-home.html -w '%{http_code}' http://127.0.0.1/`：200。
- `docker compose exec -T opencode sh -lc 'command -v s4gap && command -v s4fill && command -v s7assemble'`：三个命令存在。

### 2026-05-02 14:21:23 待办 12/15 主流程进度条同步

- 将项目阶段进度条从旧 10 节点展示收敛为 6 个主流程节点：模板与目录、审核目录、缺口处理、生成标书、共创、导出。
- 后端 `/projects/{project_id}/stages` 保留内部阶段范围 `stageIds` 和跳转用 `routeStageId`，避免破坏现有阶段状态推进。
- 前端进度条圆点改为 1-6 连续编号，点击合并节点时按 `routeStageId` 跳转到真实页面。
- 生成标书页完成后直接进入共创，不再把旧 S8 校验作为主流程下一步。

验证：

- `python3 -m py_compile code/sewpg-bid-backend/app/services/store.py`：通过。
- `./.venv/bin/python -m pytest tests/test_stage_progress.py tests/test_gap_review_flow.py tests/test_fill_generation.py -q`：16 passed。
- `./.venv/bin/python -m pytest -q`：85 passed, 6 skipped。
- `npm run lint && npm run build`：通过，保留既有 Vite chunk size warning。
- `docker compose build fastapi worker web`：通过。
- `docker compose up -d --force-recreate fastapi worker web`：通过，`fastapi` healthy。
- `curl -fsS http://127.0.0.1/api/healthz`：返回 `status=ok`。
- `curl -fsS -o /tmp/bid-web-home.html -w '%{http_code}' http://127.0.0.1/`：200。
- `/api/projects/{project_id}/stages` 烟测返回 6 个节点：模板与目录、审核目录、缺口处理、生成标书、共创、导出；烟测项目已删除。
