# 代码审查报告

**项目**: AI 数智化投标平台 (Bid Project MVP)  
**审查日期**: 2026-06-26  
**审查范围**: `code/sewpg-bid-frontend`、`code/sewpg-bid-backend`、`code/sewpg-bid-api`、Docker 配置

---

## 目录

- [1. 安全风险](#1-安全风险)
- [2. 代码质量](#2-代码质量)
- [3. 测试覆盖](#3-测试覆盖)
- [4. 依赖与配置](#4-依赖与配置)
- [5. 修复优先级建议](#5-修复优先级建议)

---

## 1. 安全风险

### 1.1 高危问题

#### H-1: 弱默认管理员密码硬编码

**文件**:
- `sewpg-bid-backend/app/core/config.py:208` — fallback 值 `"123456"`
- `sewpg-bid-backend/app/services/auth_service.py:201` — 新建用户默认密码 `"123456"`
- `sewpg-bid-frontend/src/pages/Login.jsx:33` — 前端明文 `QUICK_LOGIN_PASSWORD = '123456'`
- `.env:50` — `AUTH_ADMIN_PASSWORD=123456`

**风险**: 若 `.env` 配置遗漏，生产环境将运行在弱密码下，攻击者可直接以管理员身份登录。

**修复建议**:
1. 后端移除密码 fallback，缺失环境变量时拒绝启动
2. `create_user` 的默认密码应要求调用方显式传入
3. 前端测试账号密码通过 `VITE_` 环境变量注入
4. `.env.example` 中密码留空或标注 `CHANGE_ME`

---

#### H-2: MinIO 使用默认凭据

**文件**:
- `.env:20-21` — `minioadmin/minioadmin`
- `docker-compose.yml:304-305`
- `config.py:196-197` — fallback 硬编码

**风险**: MinIO API 端口 (9000) 和 Console 端口 (9001) 直接映射到宿主机，任何能访问网络的人都可读取/删除/篡改所有上传文件。

**修复建议**:
1. 部署时必须修改为强随机值
2. `config.py` 中对 MinIO 凭据增加非默认值校验
3. 生产环境不应将 MinIO 端口映射到宿主机

---

#### H-3: PostgreSQL 弱密码 + 端口暴露

**文件**:
- `.env:13-14` — 密码 `bidpass`
- `docker-compose.yml:268-272` — 端口 5432 映射到宿主机

**风险**: 攻击者可直接连接数据库，读取所有用户密码哈希、项目数据。

**修复建议**:
1. 使用强随机密码
2. 生产环境移除 `ports` 映射，仅通过 Docker 内部网络访问

---

#### H-4: Redis 无密码保护

**文件**:
- `docker-compose.yml:284-298`
- `.env:43` — `redis://redis:6379/0` 无认证

**风险**: 同网络任何容器可无认证访问 Redis，若任一容器被攻陷可通过 Redis 执行任意操作。

**修复建议**:
1. 为 Redis 配置 `requirepass`
2. 在 `REDIS_URL` 中加入密码

---

#### H-5: `.env.example` 包含真实弱密码

**文件**:
- `.env.example:12-14, 20-21, 50`
- `.env.airgap.example:15-17, 23-24`

**风险**: 示例文件会被提交到版本控制，泄露默认凭据结构。

**修复建议**:
1. 所有密码值替换为 `CHANGE_ME_STRONG_PASSWORD`
2. 添加注释说明必须在部署前修改

---

### 1.2 中危问题

#### M-1: OnlyOffice JWT 认证禁用

**文件**: `.env:103-104`

`ONLYOFFICE_JWT_ENABLED=false` 且 `ONLYOFFICE_JWT_SECRET` 为空。任何能访问 OnlyOffice 的人都可无认证操作文档。

**修复**: 设置 `ONLYOFFICE_JWT_ENABLED=true`，生成强随机 JWT secret。

---

#### M-2: OnlyOffice 回调 Token 为空

**文件**: `.env:89`, `config.py:178`

**风险**: 攻击者可伪造回调请求替换文档内容。

**修复**: 设置长随机值作为 `ONLYOFFICE_CALLBACK_TOKEN`，回调端点强制校验。

---

#### M-3: CORS 配置过于宽松

**文件**: `app/main.py:33-39`

`allow_methods=["*"]` 和 `allow_headers=["*"]` 允许所有 HTTP 方法和请求头。

**修复**: 限制为 `["GET", "POST", "PUT", "DELETE", "OPTIONS"]` 和 `["Authorization", "Content-Type"]`。

---

#### M-4: 健康检查泄露内部路径

**文件**: `app/api/routes/system.py:12-43`

`/healthz` 无需认证，返回内部路径（`uploads_dir`、`documents_dir`）和服务地址。

**修复**: 基础健康检查仅返回 `{"status": "ok"}`，详细信息添加认证。

---

#### M-5: 无请求频率限制

**全局性问题** — 未发现任何 rate limiting 实现。

**风险**: 登录接口可暴力破解，文件上传接口可 DoS。

**修复**: 引入 `slowapi`，登录增加失败次数限制。

---

#### M-6: Docker 容器以 root 运行

**文件**: 所有 Dockerfile 均未指定 `USER` 指令。

**修复**: 添加 `RUN useradd -m appuser` 和 `USER appuser`。

---

#### M-7: Nginx 缺少安全响应头

**文件**: `sewpg-bid-frontend/nginx.conf`

缺少 `X-Content-Type-Options`、`X-Frame-Options`、`X-XSS-Protection`、`Content-Security-Policy`。

**修复**:
```nginx
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "SAMEORIGIN" always;
add_header X-XSS-Protection "1; mode=block" always;
```

---

#### M-8: 潜在 SQL 注入风险模式

**文件**: `performance_package_service.py:78,84`, `performance_library_service.py:44,48`

使用 `text(f"SELECT ... {where_sql}")` 动态拼接。当前实现安全（参数化查询），但模式易引入漏洞。

**修复**: 重构为 SQLAlchemy ORM 查询，或添加安全约束注释。

---

#### M-9: 前端 `.env.development` 未在 `.gitignore` 排除

**文件**: `sewpg-bid-frontend/.gitignore`

**修复**: 添加 `.env.development`、`.env.test` 到 `.gitignore`。

---

### 1.3 低危问题

| 编号 | 问题 | 文件 |
|------|------|------|
| L-1 | CSRF 防护缺失（当前 Bearer token 模式风险低） | 全局 |
| L-2 | Docker 镜像版本未用 SHA256 摘要固定 | 所有 Dockerfile |
| L-3 | opencode Dockerfile 使用 `--break-system-packages` | `opencode/Dockerfile:23-25` |
| L-4 | Nginx `client_max_body_size 30720m` 过大 | `nginx.conf:9` |

---

## 2. 代码质量

### 2.1 严重问题

#### 代码质量-H1: 默认密码暴露在源码中

同安全 H-1，三处硬编码 `123456`。

---

#### 代码质量-H2: 89 处 `except Exception:` 捕获缺乏日志

后端共 89 处 `except Exception:` 捕获，大量无 `logger.exception()` 或 `logger.warning()`。

**最典型问题位置**:

| 文件 | 行号 | 问题 |
|------|------|------|
| `app/workers/redis_worker.py` | 110 | `except Exception: continue`，后台任务失败静默跳过 |
| `app/services/template_store.py` | 47,53,59,71 | 4处 bare Exception，docx 验证失败无日志 |
| `app/services/onlyoffice_documents.py` | 68,84,119 | 文档同步/下载失败静默处理 |
| `app/services/auth_service.py` | 42 | 密码校验异常被吞掉（安全相关） |
| `app/services/business_gap_planning.py` | 99,211,219,497,524,779,790,1067,1110,1149,1156,1328,1346 | 单文件 13 处 |
| `app/services/technical_gap_ai_fill.py` | 295,314,341,506,525,545 | 6处 |
| `app/services/business_assembly.py` | 301,367,388,395,717,778 | 6处 |
| `app/services/technical_gap_fact_table.py` | 769,953,987,1009,1063 | 5处 |
| `app/services/parsing.py` | 3074,3192,3556 | 3处 |

**修复**: 每处至少加一行 `logger.warning("context: %s", exc, exc_info=True)`。

---

#### 代码质量-H3: 前端 23 处空 `catch {}` 块

分布在 15 个文件中:

| 文件 | 行号 |
|------|------|
| `Login.jsx` | 64, 76 |
| `App.jsx` | 26, 129 |
| `api/index.js` | 111 |
| `TechnicalMaterialDB.jsx` | 155, 164, 1858 |
| `BusinessMaterialDB.jsx` | 155, 164, 1723 |
| `TechnicalProjectWizardModal.jsx` | 78, 265 |
| `TechnicalParseResult.jsx` | 204 |
| `TechnicalOutlineReview.jsx` | 209 |
| `TechnicalTenderReview.jsx` | 660 |
| `TechnicalGapRecognition.jsx` | 499 |
| `BusinessTenderReview.jsx` | 808 |
| `BusinessParseResult.jsx` | 202 |
| `BusinessOutlineReview.jsx` | 217 |
| `BusinessGapRecognition.jsx` | 1238 |
| `projectInfoOptions.js` | 123 |
| `onlyoffice.js` | 128 |

**修复**: 每个空 catch 至少加一行注释说明吞掉理由，关键路径加 `console.debug`。

---

### 2.2 中等问题

#### 代码质量-M1: 超大文件

| 文件 | 行数 | 说明 |
|------|------|------|
| `app/services/parsing.py` | 5,718 | 解析标书模板、附件、结构化结果全部逻辑 |
| `TechnicalMaterialDB.jsx` | 2,946 | 上传、文件树、详情面板、编辑器集成全塞一个组件 |
| `BusinessMaterialDB.jsx` | 2,577 | 同上 |
| `BusinessGapRecognition.jsx` | 2,221 | |
| `app/services/performance_package_service.py` | 1,983 | |
| `BusinessTenderReview.jsx` | 1,906 | |
| `app/services/opencode_client.py` | 1,750 | |
| `app/services/business_gap_service.py` | 1,701 | |
| `app/services/business_wiki_generation.py` | 1,564 | |
| `app/services/business_material_splitter.py` | 1,511 | |
| `TechnicalTenderReview.jsx` | 1,417 | |

**修复**: `parsing.py` 拆为 `parse_tender.py`、`parse_template.py`、`parse_appendix.py`。前端大组件用自定义 Hook 拆分。单文件建议控制在 500 行以内。

---

#### 代码质量-M2: 技术标与商务标代码大面积复制

这是代码库中最显著的结构性问题。两条业务线代码几乎逐字镜像。

**前端对称重复**:
- `TechnicalMaterialDB.jsx` 与 `BusinessMaterialDB.jsx` 前 80 行完全一致
- `TechnicalProjectList.jsx` 与 `BusinessProjectList.jsx` 分页逻辑逐行相同

**后端对称重复**:
- `technical.py`(912行) 与 `business.py`(752行) — 路由结构完全对称
- `technical_material_store.py` 与 `business_material_store.py`
- `technical_gap_*.py` 系列与 `business_gap_*.py` 系列（各 6 个文件）
- `tech_assembly.py` 与 `business_assembly.py`
- `technical_wiki_generation.py` 与 `business_wiki_generation.py`

**修复**: 前端抽取通用组件 `<MaterialDB bidType="技术标" />`，后端抽取路由工厂 `create_bid_router(prefix, bid_type, service)`。

---

#### 代码质量-M3: 工具函数在多个文件中独立重写

**字节格式化函数**（4处独立实现）:
- `peripheral.py:42` — `size_label()`
- `file_utils.py:24` — `format_size_label()`
- `materials.py:13` — `_size_label()`
- `material_wiki_attachment_operations.py:30` — `_size_label()`

**文件名安全化函数**（8处独立实现）:
- `technical_gap_actions.py:27`、`technical_gap_ai_fill.py:39`、`technical_gap_planner.py:39`、`tech_assembly.py:1398`、`business_assembly.py:846`、`peripheral.py:58`、`file_utils.py:16`、`business_gap_planning.py:884`

**时间戳函数**（17处独立定义）:
- `_now_iso()` 在 `bid_runtime_state.py`、`wiki_blueprint_common.py`、`technical_gap_ai_fill.py` 等 10 个文件各自定义
- `now_display()` 在 `peripheral.py`、`file_utils.py` 等 6 个文件各自定义

**修复**: 统一收口到 `file_utils.py`，其余文件改为 `from app.services.file_utils import ...`。

---

#### 代码质量-M4: 21 处 `_ = param` 消除未使用参数警告

| 文件 | 行号 | 数量 |
|------|------|------|
| `technical.py` | 782,793,838,884,890 | 5 |
| `business.py` | 638,649,678,724,730 | 5 |
| `bid_parse_service.py` | 1318,1332,1412,1426 | 4 |
| `bid_directory_flow.py` | 465,478 | 2 |
| `parsing.py` | 416,2437,2689 | 3 |
| `business_gap_planning.py` | 1050 | 1 |
| `technical_gap_service.py` | 280 | 1 |

**修复**: 审查每个用例，若路由参数确实不需要则从签名中移除。

---

### 2.3 低等问题

#### 代码质量-L1: 命名一致性问题

- 后端路由参数混用 camelCase 和 snake_case
- `TechnicalMaterialDB.jsx:42` 中 `BUSINESS_BID_TYPE` 值为 `'技术标'`，变量名与值语义矛盾
- 技术标文件中定义 `BUSINESS_MATERIAL_KIND_OPTIONS`，前缀不合理

#### 代码质量-L2: 注释质量

- 多数 Python 文件缺少模块级 docstring
- 部分注释过于简略，如 `# ignore storage failures` 缺少上下文

#### 代码质量-L3: Magic Number

| 文件 | 行号 | 值 | 建议常量名 |
|------|------|-----|-----------|
| `config.py` | 177 | `30 * 1024 * 1024 * 1024` | `MAX_UPLOAD_BYTES` |
| `config.py` | 187 | `1024 * 1024 * 1024` | `MAX_DOWNLOAD_BYTES` |
| `config.py` | 204 | `2 * 60 * 60` | `REDIS_LOCK_TTL_SECONDS` |
| `config.py` | 205 | `24 * 60 * 60` | `REDIS_RESULT_TTL_SECONDS` |
| `auth_service.py` | 24 | `260_000` | `PBKDF2_ITERATIONS` |
| `onlyoffice_documents.py` | 136 | `120.0` | `HTTP_TIMEOUT_SECONDS` |
| `minio_client.py` | 121,136 | `64 * 1024` | `STREAM_CHUNK_SIZE` |

#### 代码质量-L4: `sewpg-bid-api` 目录无代码

`sewpg-bid-api/` 只有文档文件，无实际代码。如已废弃应清理。

---

## 3. 测试覆盖

### 3.1 总体概览

| 维度 | 前端 | 后端 |
|------|------|------|
| 源文件数 | ~80+ (.js/.jsx) | ~135 service + 10 route |
| 测试文件数 | **8 个** (.test.mjs) | **43 个** (test_*.py) |
| 测试框架 | Node.js 内置 `node:test` | pytest + unittest |
| 有 test 脚本 | 否 | 是 (pytest.ini) |
| 有覆盖率工具 | 否 | 否 |
| 估计覆盖率 | **5-10%** | **35-45%** |

---

### 3.2 前端测试详情

#### 现有测试文件 (8个)

| 文件 | 测试内容 |
|------|---------|
| `nginxCacheHeaders.test.mjs` | nginx 缓存头验证 |
| `src/utils/workspace.test.mjs` | bid type 辅助函数 |
| `src/utils/outlineNumber.test.mjs` | 目录编号显示逻辑 |
| `src/workspaces/business/businessRiskLevel.test.mjs` | 风险级别标签 |
| `src/workspaces/business/businessProjectRoutes.test.mjs` | 商务标路由辅助函数 |
| `src/workspaces/business/businessParseUploadRecovery.test.mjs` | 上传超时恢复轮询 |
| `src/workspaces/business/businessProjectWizardModal.test.mjs` | 项目弹窗源码模式 |
| `src/workspaces/technical/*.test.mjs` | 技术标路由和上传恢复 |

#### 前端测试重大缺失

1. **完全没有 React 组件测试** — 无 `@testing-library/react`、`vitest`、`jest`
2. **未覆盖的页面组件 (0% 覆盖)**:
   - `Dashboard.jsx`, `Login.jsx`, `Settings.jsx`
   - `BusinessProjectList.jsx`, `BusinessParseResult.jsx`, `BusinessGapRecognition.jsx`, `BusinessOutlineReview.jsx`, `BusinessTenderReview.jsx`, `BusinessCoCreationEditor.jsx`, `BusinessMaterialDB.jsx`, `BusinessMaterialWiki.jsx`
   - `TechnicalProjectList.jsx`, `TechnicalParseResult.jsx`, `TechnicalGapRecognition.jsx`, `TechnicalOutlineReview.jsx`, `TechnicalTenderReview.jsx`, `TechnicalCoCreationEditor.jsx`, `TechnicalMaterialDB.jsx`, `TechnicalMaterialWiki.jsx`
3. **没有 UI 组件测试** — `Button.jsx`, `Dialog.jsx`, `Badge.jsx` 等
4. **没有 API 层测试** — `src/api/index.js` 零测试
5. **没有端到端测试**

---

### 3.3 后端测试详情

#### 现有测试文件 (43个)

**核心业务逻辑测试（质量较高）**:
- `test_parse_pipeline.py` — 2000+ 行，覆盖 docx/md/图片解析、多文件、附件提取、cell merge、大文件性能
- `test_business_assembly.py` — 商务标组装 (1286行)
- `test_business_gap_planner.py` — 商务缺口规划 (2069行)
- `test_business_section_tree.py` — 章节树构建 (459行)
- `test_fill_generation.py` — 填充生成 (828行)
- `test_toc_skill_scripts.py` — TOC Skill 脚本 (2672行)
- `test_opencode_client.py` — OpenCode 客户端 (1003行)

**路由层测试 (5个)**:
- `test_auth_routes.py` — 登录/鉴权 API
- `test_peripheral_routes.py` — 集成测试（需外部服务）
- `test_security_settings_ocr_routes.py` — 集成测试
- `test_wiki_export_routes.py` — Wiki 导出路由

#### 后端测试重大缺失

**以下 Route 文件完全没有测试**:
- `app/api/routes/dashboard.py`
- `app/api/routes/performance.py`
- `app/api/routes/project_info.py`
- `app/api/routes/system.py`
- `app/api/routes/business_gaps.py`

**以下核心 Service 完全没有测试 (~50+ 个)**:

关键缺失:
- `dashboard_service.py` — 仪表盘数据聚合
- `bid_project_service.py` — 项目核心服务
- `bid_project_repository.py` — 项目持久化仓库
- `bid_generation_flow.py` — 标书生成流程
- `bid_document_flow.py` / `bid_document_state.py` — 文档流程和状态
- `bid_runtime_state.py` — 运行时状态
- `bid_ocr_service.py` / `ocr_service.py` — OCR 服务
- `audit_service.py` — 审计服务
- `auth_service.py` — 认证服务（安全关键）
- `job_queue.py` — 任务队列
- `identity.py` — 身份/权限
- `file_utils.py` / `filename_utils.py` — 文件工具
- `minio_client.py` — MinIO 客户端封装
- `template_store.py` — 模板存储

素材系统大量模块缺乏测试 (20+ 个):
- `material_store.py`, `material_tags.py`, `material_taxonomy.py`, `material_cleaning.py`
- `material_raw_*` (7个文件), `material_upload_*` (4个文件), `material_move_*` (2个文件)
- `material_wiki_*` (6个文件), `material_folder_*` (2个文件)

**集成测试严重不足**: 仅 3 个文件，默认跳过（需 `BID_RUN_INTEGRATION=1`）

---

### 3.4 测试优势

1. 后端核心解析管线测试质量高 (`test_parse_pipeline.py` 2000+ 行)
2. 商务标/技术标关键业务有较好覆盖
3. Skill 脚本有独立测试 (`test_toc_skill_scripts.py` 2672 行)
4. 前端工具函数测试覆盖正常/异常/边界
5. 集成测试有隔离标记，不会在普通 CI 中失败

---

## 4. 依赖与配置

### 4.1 安全与配置风险

| 问题 | 文件 | 说明 |
|------|------|------|
| 弱密码和默认凭据 | `.env`, `docker-compose.yml` | admin/MinIO/PostgreSQL 均使用弱密码 |
| OnlyOffice 安全机制未启用 | `.env.example:103-106` | JWT 关闭，回调 token 为空 |
| `.env` 缺少根目录 gitignore 保护 | `code/` 目录 | `.env.second` 等可能被意外提交 |

### 4.2 架构与运维问题

| 问题 | 说明 |
|------|------|
| **容器以 root 运行** | 三个 Dockerfile 均未指定 USER |
| **OnlyOffice 就绪判断不足** | 仅检查 `service_started`，未等待字体加载完成 |
| **数据库 schema 管理缺失** | 有 `alembic` 依赖但无迁移目录，全靠 `initdb/01-init.sql` |
| **环境变量默认值不一致** | `.env.example` 500MB vs `docker-compose.yml` 30GB |
| **缺少网络分层** | 所有服务同网络，数据层可被前端容器直连 |
| **依赖版本锁定不统一** | 部分 `==` 精确锁定，部分 `>=` 只设下限 |
| **第二实例卷隔离缺失** | `docker-compose.second.yml` 未覆盖卷映射，双实例共享数据 |

### 4.3 Docker 优化建议

- opencode Dockerfile 三次独立 `RUN pip install` 可合并
- 使用 `--break-system-packages` 绕过 PEP 668，建议改用虚拟环境
- 基础镜像未用 SHA256 摘要固定

---

## 5. 修复优先级建议

### P0 — 立即修复

| 问题 | 工作量 | 说明 |
|------|--------|------|
| 替换所有默认密码 (admin/MinIO/PostgreSQL) | 小 | 部署安全底线 |
| Redis 加密码保护 | 小 | |
| 限制数据库和 MinIO 端口暴露 | 小 | 改为 `expose` |
| `redis_worker.py:110` 异常补日志 | 极小 | 后台任务失败静默跳过是最危险的 |
| `.env.example` 敏感字段留空 | 极小 | 防止提交泄露 |

### P1 — 本迭代

| 问题 | 工作量 | 说明 |
|------|--------|------|
| 89 处 `except Exception:` 补日志 | 中 | 按文件逐批修复 |
| 23 处前端空 `catch` 补注释 | 小 | |
| 启用 OnlyOffice JWT 认证 | 小 | |
| Nginx 添加安全响应头 | 极小 | |
| 前端安装测试框架 (vitest) | 小 | `npm i -D vitest @testing-library/react` |
| 后端安装 pytest-cov | 小 | 添加依赖 + 更新 pytest.ini |
| 健康检查端点去除内部路径 | 小 | |

### P2 — 下个迭代

| 问题 | 工作量 | 说明 |
|------|--------|------|
| 工具函数收口到 `file_utils.py` | 中 | 消除 4+8+17 处重复 |
| `_ = param` 清理 | 小 | 21 处 |
| 补充 `auth_service.py` 单元测试 | 中 | 安全关键路径 |
| 补充素材系统核心模块测试 | 大 | 20+ 个模块 |
| 前端核心页面组件测试 | 大 | Login/Dashboard/ProjectList |
| CORS 配置收紧 | 极小 | |
| Docker 容器改用非 root 用户 | 小 | |

### P3 — 持续重构

| 问题 | 工作量 | 说明 |
|------|--------|------|
| `parsing.py` 拆分 (5718行) | 大 | 按职责拆为 4 个文件 |
| 技术标/商务标代码去重 | 大 | 前后端各 10+ 对对称文件 |
| 补充集成测试和 E2E 测试 | 大 | |
| 初始化 Alembic 数据库迁移 | 中 | |
| Docker 网络分层 | 中 | |
| 依赖版本统一锁定 | 中 | 引入 pip-compile |

---

## 附录: 审查方法

本次审查由 4 个并行子agent 完成:

1. **代码质量和风格检查** — 代码结构、命名规范、异常处理、重复代码
2. **安全风险检查** — 敏感信息泄露、注入漏洞、认证授权、Docker 安全
3. **依赖和配置检查** — 依赖版本、Docker 配置、环境变量、数据库配置
4. **测试覆盖检查** — 测试文件、覆盖率、测试框架、测试配置
