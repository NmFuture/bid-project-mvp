# 联调进展

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
