# kimi-1 代码审阅报告

> **审阅范围**：素材库、素材标签、共用业绩库、素材清洗、商务 Wiki
> **负责人**：安博成（Whisper）
> **审阅日期**：2026-06-13
> **文档版本**：v1.0

---

## 1. 审阅范围概览

| 模块类型 | 文件数量 | 核心文件 |
|---------|---------|---------|
| 后端服务 | 25+ | `business_material_store.py`, `material_tags.py`, `material_wiki_*.py`, `performance_library_service.py`, `wiki_generation.py`, `wiki_export.py` |
| API 路由 | 2 | `business.py`, `performance.py` |
| 前端页面 | 3 | `BusinessMaterialDB.jsx`, `BusinessMaterialWiki.jsx`, `BusinessMaterialsViewSwitch.jsx` |
| Skills | 2 | `bid-material-format-cleaner`, `bid-business-wiki-material-builder` |
| 测试 | 3 | `test_business_material_library_rules.py`, `test_wiki_generation.py`, `test_wikibuild_router.py` |
| 设计文档 | 8 | `doc/anbc_doc/` 下全部文档 |

---

## 2. 后端服务层审阅

### 2.1 素材库核心架构

**总体评价：⭐⭐⭐⭐ 良好**

素材库采用三层架构：

```
Operations 层（原子操作）
  material_raw_tree.py / material_raw_file_operations.py / material_raw_folder_operations.py
  material_wiki_node_operations.py / material_wiki_tree.py / material_move_operations.py
    ↓
Store 层（门面 + Scope 校验）
  business_material_store.py
    ↓
API 路由层
  business.py / performance.py
```

**优点：**

- 职责分离清晰：每个 operations 文件只做一件事（tree / file / folder / move / access / object），符合单一职责原则
- 事务安全：`move_raw_folder` 在单个 session 内完成所有文件夹路径更新和 MinIO 对象移动
- Scope 隔离严谨：`business_material_store` 作为门面层，每个操作都先 `ensure_raw_file` / `_ensure_wiki_node` 做权限校验
- URL 重写机制：`scoped_material_urls.py` 用内部占位前缀做 URL 抽象，避免硬编码路径
- 受保护文件夹：`material_folder_scope.py` + `material_taxonomy.py` 定义了清晰的保护路径集合

**问题清单：**

| 级别 | 问题 | 文件 | 说明 |
|------|------|------|------|
| 🟡 P1 | `ensure_raw_file` 全量查询 O(n) | `business_material_store.py:80-88` | 用 `page_size=100000` 全量查询再遍历匹配，应改为直接 DB 查询 |
| 🟡 P1 | `_ensure_wiki_node` 全量遍历 wiki tree | `business_material_store.py:90-95` | 每次 wiki 操作都重建整棵树来验证节点，应改为直接 DB 查询 |
| 🟡 P1 | `delete_wiki_node` 全量加载到内存 | `material_wiki_node_operations.py:111-113` | `all_nodes = (await session.execute(select(WikiNode))).scalars().all()` 对大型 Wiki 是 O(n) 内存开销 |
| 🟢 P2 | `raw_files_operation` 无数据库分页 | `material_raw_file_operations.py:29-62` | SQL 查询无 `LIMIT/OFFSET`，全量加载到 Python 再做内存分页 |
| 🟢 P2 | `_safe_segment` 重复定义 | 3+ 个文件各自定义 | 应提取到共享工具模块 |

### 2.2 素材标签系统

**总体评价：⭐⭐⭐⭐⭐ 优秀**

- `material_tags.py` 的 `normalize_material_tags` 支持数组、JSON 字符串、分隔符文本三种输入
- 去重、截断、空白处理完备
- `material_upload_metadata.py` 和 `material_update_metadata.py` 通过标签统一处理

### 2.3 共用业绩库

**总体评价：⭐⭐⭐⭐ 良好**

- CRUD 完整，支持分页、关键词、客户、标签、标类多维筛选
- 软删除（`review_status = 'disabled'`）而非物理删除
- Word 上传/下载走 MinIO，带大小校验
- `list_match_candidates` 实现了 scope-based 匹配（standard > customer > project）

**问题清单：**

| 级别 | 问题 | 文件 | 说明 |
|------|------|------|------|
| 🔴 P0 | SQL 拼接风格不够防御性 | `performance_library_service.py:44-49` | 虽然参数化了 values，但 `filters` 列表是 f-string 拼接的 `WHERE` 子句内容，当前安全但风格不佳 |
| 🟡 P1 | `_candidate_matches_scope` 运算符优先级可读性差 | `performance_library_service.py:446-448` | `any(customer and customer in item_customer or ...)` 应加括号明确优先级 |
| 🟡 P1 | `update_record` 动态 SQL 拼接字段名 | `performance_library_service.py:98-106` | 字段名来自 `_normalize_payload` 的 keys，无白名单校验 |
| 🟢 P2 | `list_match_candidates` 先全量查再 Python 过滤 | `performance_library_service.py:161-204` | 当业绩记录增多时效率低 |

### 2.4 素材清洗

**总体评价：⭐⭐⭐⭐ 良好**

- 通过 `subprocess` 调用 `driver.py`，隔离了清洗依赖
- 使用 `asyncio.to_thread` 包装同步清洗为异步
- MinIO 上传/下载有正确的临时文件清理

**已知问题（来自设计文档 `商务清洗与Wiki生成-Skill-Review.md`）：**

- 清洗产物取最新 mtime 而非 manifest 精确匹配（应改用 `relativeOutputPath`）
- `.doc` 依赖 LibreOffice，镜像需确认

### 2.5 Wiki 生成

**总体评价：⭐⭐⭐⭐ 良好（功能完善但有冗余）**

- 双路径设计：先尝试 LLM + skill 精修，失败后 fallback 到确定性脚本，容错性好
- OCR 缓存有 signature 校验、版本号、失败缓存，避免重复 OCR
- 蓝图生成从 skill 脚本 re-export，实现确定性骨架

**问题清单：**

| 级别 | 问题 | 文件 | 说明 |
|------|------|------|------|
| 🔴 P0 | 硬编码本地路径 | `wiki_generation.py:37-38` | `DEFAULT_REFERENCE_WIKI_PATH = Path("/Users/anbocheng/Desktop/...")` 不应出现在生产代码中 |
| 🔴 P0 | 存在大量死代码 | `wiki_generation.py` | `_build_wiki_generation_prompt` / `generate_wiki_blueprint_with_trace` / `_build_wiki_tool_prompt` 无调用方 |
| 🟡 P1 | 文件 2000+ 行过于庞大 | `wiki_generation.py` | 应拆分为 inventory profiling、OCR processing、manifest building、skill execution 等子模块 |
| 🟡 P1 | 材料分组纯关键词匹配 | `wiki_generation.py:103-146` | 中文关键词硬编码，覆盖不全面时会误分类 |

---

## 3. 数据模型审阅

**总体评价：⭐⭐⭐⭐⭐ 优秀**

- PostgreSQL + SQLAlchemy，用 JSONB 存 `ext_fields` 实现 schema-flexible 的素材元数据
- `ARRAY(VARCHAR)` 存 `bid_types` / `tags`，适合 PostgreSQL
- `RawFileVersion` 实现版本链，`WikiAttachment` 支持 MinIO 对象关联
- `to_dict()` 方法字段完整，camelCase 命名，前端可直接消费
- `ondelete="CASCADE"` 正确设置了级联删除

---

## 4. API 路由层审阅

**总体评价：⭐⭐⭐⭐ 良好**

- RESTful 风格，路径命名清晰
- 正确使用 FastAPI 参数注入（Query、Body、Depends、File）
- `minio_streaming_response` 统一处理文件下载

**问题：**

| 级别 | 问题 | 说明 |
|------|------|------|
| 🟡 P1 | 部分端点缺少认证 | `business_raw_tree`、`business_raw_files`、`business_wiki_list` 等素材库端点没有 `Depends(current_user)` |
| 🟡 P1 | `performance.py` 重复定义路由 | 与 `business.py` 中已有的业绩 category 路由功能完全一致，可能是迁移遗留 |
| 🟢 P2 | `business_raw_upload` 手动解析 multipart | 代码冗长，FastAPI 的 `Form()` + `File()` 可以简化 |

---

## 5. 前端页面审阅

### 5.1 `BusinessMaterialDB.jsx`（2596 行）

**总体评价：⭐⭐⭐ 中等**

**优点：** 功能完整——树形导航、文件上传（支持文件夹）、拖拽移动、搜索过滤、标签管理、素材切分。

**UI 问题（来自 `materials-ui-review-handoff.md`）：**

| 级别 | 问题 | 说明 |
|------|------|------|
| 🔴 P0-A | 业绩库主表溢出 | `min-w-[1380px]` 在 1280px 视口下操作列不可点 |
| 🔴 P0-B | 全局 shadow 被压平 | `index.css:255-258` 导致所有弹窗无悬浮感 |
| 🟡 P1-G | 文件名被 chip 挤没 | 只剩几十像素 |
| 🟡 P1-H | 核心操作全 hover 才出现 | 触屏不可达 + hover 抖动 |
| 🟡 P1-J | 首屏加载态硬切（CLS） | 整页入场位移 |
| 🟡 P1 | 文件过大（2596 行） | 应拆分为 Tree / FileList / UploadDialog 等组件 |

### 5.2 `BusinessMaterialWiki.jsx`（272 行）

**总体评价：⭐⭐⭐⭐ 良好**

- 结构清晰：左树 + 右内容双栏
- 刷新/重建 Wiki 操作有 confirm 保护

**UI 问题：**

| 级别 | 问题 |
|------|------|
| 🟡 P1-D | 双栏固定高不等（树 720px / 内容 522px），内容区滚动失效 |
| 🟡 P1-E | xl 以下单列时 720px 高树霸占首屏 |
| 🟡 P1-F | 内容面板无头部 + 空态风格不一致 |

---

## 6. Skills 审阅

### 6.1 `bid-material-format-cleaner`

**总体评价：⭐⭐⭐⭐⭐ 优秀**

- SKILL.md 文档详尽（296 行），覆盖环境准备、各分支处理规则、输出状态定义、报告格式
- "AI 编排 + 确定性脚本"的职责划分清晰
- 正确声明了图片不在清洗范围

**已知问题：**

- `driver.py` 缺 `from typing import Any` import（靠 `__future__` 侥幸不崩）
- `.doc` 依赖 LibreOffice（镜像需确认）

### 6.2 `bid-business-wiki-material-builder`

**总体评价：⭐⭐⭐⭐ 良好**

- SKILL.md 已正确反映"脚本产骨架 + LLM 精修"的两阶段架构
- 13 个模板模块清单与脚本 `MODULE_CONFIGS` 对齐
- 铁律："精修只能改判断/描述，不能改事实"

---

## 7. 测试覆盖

### 7.1 `test_business_material_library_rules.py`（1044+ 行）

**质量：⭐⭐⭐⭐⭐ 优秀**

- 覆盖了素材上传元数据、标签规范化、受保护文件夹、raw tree payload、filter/pagination、wiki scope、move metadata、performance CRUD、performance match candidates、business material index 等全场景
- 使用 `_FakePerformanceSession` / `_FakePerformanceResult` mock DB
- 边界测试充分：空值、非法值、scope 隔离、级联保护

### 7.2 `test_wiki_generation.py`（399 行）

**质量：⭐⭐⭐⭐⭐ 优秀**

- 测试了 LLM 路径、确定性 fallback 路径、output file 加载、failure 场景
- 商务标/技术标分路径测试

### 7.3 `test_wikibuild_router.py`（84 行）

**质量：⭐⭐⭐⭐ 良好**

- 测试了路由逻辑：商务标 → business skill，未知 → technical skill

---

## 8. 设计文档

| 文档 | 评价 |
|------|------|
| `materials-ui-review-handoff.md` | ⭐⭐⭐⭐⭐ 66-agent UI 评审交接，P0/P1/P2 问题全部带 file:line |
| `商务清洗与Wiki生成-Skill-Review.md` | ⭐⭐⭐⭐⭐ 架构认知对齐 + 优先修复清单 |
| `20260606-商务标素材库与Wiki字段目录设计.md` | ⭐⭐⭐⭐⭐ 60KB 详细字段设计 |
| `20260603-业绩库项目级拆分与合同附件设计说明.md` | ⭐⭐⭐⭐⭐ 业绩库扩展设计 |
| `20260604-业绩库素材库Wiki标签整合设计计划.md` | ⭐⭐⭐⭐⭐ 标签整合计划 |
| `20260606-业绩库下游使用Handoff.md` | ⭐⭐⭐⭐⭐ 业绩库下游消费交接 |

---

## 9. 风险清单汇总

### 🔴 P0（必须修复）

| # | 问题 | 文件 |
|---|------|------|
| 1 | 硬编码本地路径 `/Users/anbocheng/Desktop/...` | `wiki_generation.py:37` |
| 2 | Wiki LLM prompt 死代码未清理 | `wiki_generation.py` |
| 3 | cleaner `driver.py` 缺 `from typing import Any` | `driver.py` |
| 4 | 业绩库主表 1280px 溢出 | `BusinessPerformanceLibrary.jsx` |
| 5 | 全局 shadow 压平弹窗 | `index.css:255-258` |

### 🟡 P1（应该修复）

| # | 问题 | 文件 |
|---|------|------|
| 6 | `ensure_raw_file` 全量查询 O(n) | `business_material_store.py:80-88` |
| 7 | `_ensure_wiki_node` 全量遍历 | `business_material_store.py:90-95` |
| 8 | `_candidate_matches_scope` 可读性 | `performance_library_service.py:446-448` |
| 9 | `wiki_generation.py` 2000+ 行需拆分 | `wiki_generation.py` |
| 10 | 素材库 API 缺认证 | `business.py` 素材端点 |
| 11 | 清洗产物取 mtime 而非 manifest | `material_cleaning.py:225` |
| 12 | BusinessMaterialDB 2596 行需拆分 | `BusinessMaterialDB.jsx` |
| 13 | Wiki 双栏高度不等 | `BusinessMaterialWiki.jsx` |

### 🟢 P2（建议优化）

| # | 问题 |
|---|------|
| 14 | `raw_files_operation` 内存分页改为 DB 级 LIMIT/OFFSET |
| 15 | `_safe_segment` 重复定义提取到共享工具 |
| 16 | `performance.py` 与 `business.py` 路由重复需清理 |

---

## 10. 总体评价

| 维度 | 评分 | 说明 |
|------|------|------|
| **架构设计** | ⭐⭐⭐⭐⭐ | 三层分离（operations → store → API），Scope 隔离严谨 |
| **代码质量** | ⭐⭐⭐⭐ | 命名规范、防御性编程好，个别超大文件需拆分 |
| **错误处理** | ⭐⭐⭐⭐ | 大部分有完善的错误处理，个别 SQL 拼接不够防御性 |
| **测试覆盖** | ⭐⭐⭐⭐⭐ | 核心规则、元数据构建、scope 过滤全场景有测试 |
| **设计文档** | ⭐⭐⭐⭐⭐ | handoff 文档精确到 file:line，可直接交给下一个 Agent 执行 |
| **前端 UI** | ⭐⭐⭐ | 功能完整但有多个 P0/P1 UI 问题待修复 |

**总结：安博成负责的素材库模块是整个系统的基础层，架构设计优秀，测试覆盖充分。主要改进方向是清除死代码和硬编码路径、性能优化（全量查询改为直接 DB 查询）、前端 UI 修复。**
