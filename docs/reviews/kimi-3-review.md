# kimi-3 代码审阅报告

> **审阅范围**：智能解析、目录生成、正文生成、格式处理、导出
> **负责人**：彭维锋（pengweifeng）
> **审阅日期**：2026-06-13
> **文档版本**：v1.0

---

## 1. 审阅范围概览

| 模块类型 | 文件数量 | 核心文件 |
|---------|---------|---------|
| 后端服务 | 10 | `parsing.py`, `business_document_service.py`, `business_document_editing.py`, `business_parse_assets.py`, `business_template_extractor.py`, `bid_directory_flow.py`, `bid_document_flow.py`, `onlyoffice_documents.py`, `opencode_client.py` |
| Skills | 4 | `bid-business-tender-structured-parser`, `bid-business-outline-generator`, `bid-business-assembler`, `bid-business-format-cleaner` |
| 前端页面 | 2 | `BusinessTenderReview.jsx`, `BusinessOutlineReview.jsx` |
| 测试 | 6 | `test_s1parse_router.py`, `test_parse_pipeline.py`, `test_business_parse_skill_script.py`, `test_directory_generation.py`, `test_outline_quality_gate.py`, `test_business_format_cleaner.py` |
| 交接契约 | 1 | `doc/商务标S1阶段交接件契约.md` |

---

## 2. S1 交接契约审阅

**质量：⭐⭐⭐⭐⭐ 优秀**

`doc/商务标S1阶段交接件契约.md` 是一份生产级的阶段交接规范：

- 11 节规范，清晰的生命周期状态（`running → readyForReview → published → abandoned`）
- 存储布局、消费规则完备
- camelCase（API）与 snake_case（磁盘 JSON）命名映射规则
- 10 点验收清单
- 向后兼容 §7 的 4 级 fallback 路径读取务实但可能积累技术债

---

## 3. 后端服务层审阅

### 3.1 `parsing.py`（5,660 行）— 核心解析服务

**代码质量：⭐⭐⭐⭐ 良好，有隐患**

**优点：**

- 丰富的领域模型：`ParseCategory`、`FieldSpec` 和 15+ 字段组元组定义了清晰的商务词汇
- 多格式支持：DOCX（zip XML）、PDF（pypdf）、OCR 回退（异步/线程桥接）
- 确定性评分：`_business_core_field_score()` 实现了透明的规则评分系统（段落邻近、引用检测、日期规范化）
- 投标截止时间规范化：区分"递交截止时间"与"开标时间"的多层校验逻辑

**问题：**

| 级别 | 问题 | 位置 | 说明 |
|------|------|------|------|
| 🟡 P1 | **文件过长（5,660 行）** | 全文件 | 混合了解析、字段提取、文档文本提取、OCR 桥接、商务模板处理、承诺分析、目录树构建，应拆分为 3-4 个模块 |
| 🟡 P1 | 评分权重为魔数 | `_business_core_field_score()` | +40、+25、+90、+80、-220、+120、-180、-260 等硬编码评分值无文档说明，调优脆弱 |
| 🟢 P2 | 重复正则模式 | `DATE_PATTERN` / `BID_DEADLINE_DATE_PATTERN` | 两者几乎相同，后者只多了时/分组，可合并 |
| 🟢 P2 | OCR 失败静默返回空文本 | `_ocr_fallback_text` | 生产环境应有指标/告警机制 |
| 🟢 P2 | `sys.path` 操作 | `lines 36-42` | 模块级注入 `parser_core` 路径，依赖目录结构，脆弱 |

### 3.2 `business_document_service.py`（299 行）

**代码质量：⭐⭐⭐⭐ 良好**

- 干净的 OOP：继承 `BidDocumentService`，添加商务专用的 chat、rewrite suggestion、format application
- 模型回退：`_send_business_chat_prompt()` 实现了两层模型回退策略
- JSON 提取健壮：`_extract_rewrite_suggestion()` 同时处理 code-fenced JSON 和原始 JSON

**小问题：**

- 每次调用都创建新的 `OpencodeClient`（无缓存）
- Chat prompt 模板硬编码在方法体内

### 3.3 `business_document_editing.py`（178 行）

**代码质量：⭐⭐⭐⭐⭐ 优秀**

- 精准的外科手术式重写，带唯一匹配强制
- 变更前创建带时间戳的备份到 `s4_ai_rewrite_backups/`，附 JSONL 审计
- `exact_paragraph` 和 `literal_substring` 两种匹配模式提供适当灵活性

### 3.4 `business_parse_assets.py`（580 行）

**代码质量：⭐⭐⭐⭐ 良好**

- 完整的审批工作流：附件、评分标准、承诺函的 approve/reject
- `sync_approved_business_parse_assets()` 处理批量上传，逐条成功/失败跟踪

**小问题：**

- `_mark_appendix_synced` 和 `_mark_letter_synced` 几乎相同，应合并
- `BUSINESS_APPENDIX_MATERIAL_FOLDER` 和 `BUSINESS_COMMITMENT_MATERIAL_FOLDER` 值相同，可能是有意但值得确认

### 3.5 `business_directory_service.py`（11 行）

**代码质量：⭐⭐⭐⭐⭐ 优秀**

- 完美委托给 `BidDirectoryService`，零代码重复，正确使用继承

### 3.6 `business_template_extractor.py`（511 行）

**代码质量：⭐⭐⭐⭐ 良好**

- 两阶段提取：`prepare`（脚本候选检测）→ `boundary`（AI agent 决策）→ `finalize`
- 弹性 boundary agent：最多 3 次重试，带 trace 记录
- `btplbound` CLI 集成：干净的子进程编排

**问题：**

| 级别 | 问题 | 位置 | 说明 |
|------|------|------|------|
| 🟢 P2 | `_save_extraction_trace()` 覆盖警告模式可疑 | `lines 358-366` | 先追加警告，然后立即覆盖最后一条警告的消息，可能是 bug 或至少令人困惑 |
| 🟢 P2 | `TEMPLATE_BOUNDARY_AGENT_MAX_ATTEMPTS = 3` 硬编码 | 全文件 | 应可配置 |

### 3.7 `bid_directory_flow.py`（489 行）

**代码质量：⭐⭐⭐⭐ 良好**

- SSE 流式实时进度更新
- 任务队列集成 + 线程回退
- OnlyOffice 集成用于招标文件预览

**小问题：**

- `_directory_tasks()` 返回硬编码的 3 步任务列表，不适用于 business vs technical 的差异
- daemon 线程在服务器重启时可能成为孤儿

### 3.8 `bid_document_flow.py`（386 行）

**代码质量：⭐⭐⭐⭐ 良好**

- 干净的 PDF 转换双策略：OnlyOffice → LibreOffice 回退
- 版本感知的 OnlyOffice 回调，带过期文档检测
- 安全：`_validate_download_url()` 主机白名单 + 凭证剥离

### 3.9 `onlyoffice_documents.py`（155 行）

**代码质量：⭐⭐⭐⭐⭐ 优秀**

- 极简聚焦模块：文档 key 生成（hash-based session keys）、MinIO 同步、有界大小下载 + 临时文件原子性

### 3.10 `opencode_client.py`（1,570 行）

**代码质量：⭐⭐⭐⭐ 良好，有复杂度隐患**

**优点：**

- 15+ 专用方法覆盖不同 Skill 调用（outline、assembly、format、gap planning、table fill、S1 parse 等）
- 早期工具完成：`_send_prompt_with_session_polling` 在 LLM 完成前检测工具输出——对长时间运行的 Skill 至关重要
- 空闲超时检测，带渐进式 stall 检查

**问题：**

| 级别 | 问题 | 位置 | 说明 |
|------|------|------|------|
| 🟡 P1 | 文件过长（1,570 行） | 全文件 | `_send_prompt_with_session_polling` 单独约 200 行，深度嵌套控制流 |
| 🟡 P1 | 线程模型 | 全文件 | 每个请求创建 `threading.Thread` + `threading.Event`，0.5s 轮询间隔。高负载下可能耗尽线程池 |
| 🟢 P2 | 死代码 | `line 984` | `return None` 在 `raise RuntimeError` 之后，不可达代码 |

---

## 4. Skills 审阅

### 4.1 `bid-business-tender-structured-parser`（SKILL.md: 183 行）

**质量：⭐⭐⭐⭐⭐ 优秀**

- 4 层模型（structure → AI review → validation → synthesis）设计优秀
- 确定性优先：项目基本信息、投标人须知、清晰评分表都是确定性提取；AI 只处理语义边界情况
- CLI 边界：`s1parse` 命令强制工具排序，防止捷径
- 证据契约：每个候选都携带 `evidenceIds` 和 `sourceText` 实现全链路追溯

### 4.2 `bid-business-outline-generator`（SKILL.md: 494 行）

**质量：⭐⭐⭐⭐⭐ 优秀（最详尽的 Skill）**

- 494 行 SKILL.md，32 点质量清单、证据状态矩阵、编号学习规则、`source_text` 查找优先级
- 历史优先原则：历史标书目录是主要继承来源；招标文件用于匹配/证据，不用于重组
- 质量门：`outline_quality_gate.py`、`check_source_text.py`、`validate_outline.py` 形成多层验证管线
- 辅助分离：`outline_authoring_helper.py` 是唯一允许写入最终 `outline.json` 的脚本

**小顾虑：** Skill 文档过长（494 行），新开发者吸收成本高。建议分层文档。

### 4.3 `bid-business-assembler`（SKILL.md: 115 行）

**质量：⭐⭐⭐⭐ 良好**

- 清晰范围：仅 S4，不与技术标交叉污染
- 装配模式：`extract_and_summarize`、`extract_segment`、直接装配
- 失败策略：优雅降级（占位符 + 审核列表）而非硬失败

**小问题：** 实际脚本实现细节偏少——大部分逻辑在 `run_from_manifest.py` 中委托给 opencode。

### 4.4 `bid-business-format-cleaner`（SKILL.md: 93 行 + 测试 1,168 行）

**质量：⭐⭐⭐⭐ 良好**

- 规范清晰：标题样式匹配、分页清理、目录插入、章节边界处理
- 测试 fixtures：`minimal_business_bid.docx` 和 `minimal_outline.json` 支持可复现测试
- 1,168 行测试文件表示覆盖充分

**小问题：** 样式配置分散在 `business_heading_style.json`、`business_toc_style.json`、`business_style_spec.md` 三个文件，可合并。

---

## 5. 前端审阅

### 5.1 `BusinessTenderReview.jsx`（1,878 行）

**代码质量：⭐⭐⭐⭐ 良好**

**优点：**

- 功能全面：上传、解析进度轮询、结构化结果展示、附件/承诺预览、评分标准、资格要求、投标人须知、商务废标条款
- 健壮的轮询：`shouldPollParseProgress` 带超时恢复
- OnlyOffice 集成用于附件预览

**问题：**

| 级别 | 问题 | 说明 |
|------|------|------|
| 🟡 P1 | 文件过大（1,878 行） | 包含 8+ 表格组件（`ProjectBasicsTable`、`QualificationRequirementsTable`、`BidderInstructionsTable` 等），应拆分为独立文件 |
| 🟡 P1 | 状态爆炸 | 30+ `useState` hooks，应使用 `useReducer` 或状态机 |
| 🟢 P2 | 硬编码常量 | `MAX_FILE_SIZE = 500 * 1024 * 1024`、`MAX_BATCH_FILES = 5` 应来自 API 或配置 |

### 5.2 `BusinessOutlineReview.jsx`（800 行）

**代码质量：⭐⭐⭐⭐ 良好**

- 树操作：拖拽重排、添加/删除节点、行内标题编辑
- OnlyOffice 搜索桥接：`sendOnlyOfficeSearch` 通过 `BroadcastChannel` + `localStorage` 实现跨 iframe 通信
- 大纲自动折叠（>180 节点）

**小问题：**

- `renumberOutlineNodes` 通过深克隆修改树——大开销
- `chineseNumber` 函数只处理到 100
- `window.confirm` 用于删除——应使用模态组件

---

## 6. 流水线连通性评估

### 解析 → 目录 → 装配 → 格式 → 导出 链路

| 阶段 | 输入 | 输出 | 连接质量 |
|------|------|------|---------|
| **S1 解析** | 上传文件 | `s1_structured_result.json` + `business_section_tree.json` | ⭐⭐⭐⭐⭐ 定义完善的交接契约 |
| **S2 目录** | 解析结果 + 模板文件 | `outline.json` (business_bid_outline.v1) | ⭐⭐⭐⭐ 良好，但模板文件路径解析复杂 |
| **S3 匹配** | 目录 + 解析结果 | Gap 计划 + 素材匹配 | ⭐⭐⭐ 不在 kimi-3 范围，但目录 → 匹配连接清晰 |
| **S4 装配** | 目录 + gap 计划 + 素材 + 事实表 | Word 文档 | ⭐⭐⭐⭐ 定义完善的 manifest 契约 |
| **格式** | 原始 Word + outline.json | 带样式 + 目录的 Word | ⭐⭐⭐⭐ 大纲感知的匹配 |
| **导出** | 清洗后 Word | PDF（OnlyOffice 或 LibreOffice） | ⭐⭐⭐⭐ 双策略转换 |

**关键连接优势：**

- S1 交接契约（`stageArtifacts.s1`）生产级品质，带版本管理、状态生命周期和路径校验
- S2 目录保留 `source_refs` 用于证据追溯到 S1 解析结果
- S4 装配器从 S3 产物读取 `assemblyMode` 来确定每章节的装配策略

**关键连接风险：**

- `business_section_tree.json` 在 S1 早期产出并被结构化解析器消费——如果目录树有误，所有下游解析都受影响
- 商务目录生成器严重依赖历史标书模板文件的质量
- 格式清理器通过文本匹配标题——如果装配期间标题被修改会失败

---

## 7. 测试覆盖

### 7.1 `test_s1parse_router.py`（405 行）

**质量：⭐⭐⭐⭐⭐ 优秀**

- 测试所有路由排列：business/technical 标类、parseProfile 覆盖、stage 参数、task helpers
- 验证 Docker/入口配置（`.dockerignore`、`opencode.json` 权限、`docker-entrypoint.sh`）
- 测试运行时配置合并脚本

### 7.2 `test_parse_pipeline.py`（3,576 行）

**质量：⭐⭐⭐⭐⭐ 优秀（最全面的测试文件）**

- 端到端管线测试覆盖：上传、文本提取、结构化解析、商务目录树、模板提取器集成、承诺函、评分标准
- 正确 mock 了 opencode skill 调用
- 测试向后兼容：skill 结果权威性高于本地转换
- 边界场景：非 DOCX 输入（Markdown、图片 OCR）、合并表格、多级模板集群

### 7.3 `test_business_parse_skill_script.py`（4,742 行）

**质量：⭐⭐⭐⭐⭐ 优秀**

- 通过 subprocess 测试实际 skill 脚本（不是 mock）
- 资格要求提取，带段落过滤和范围检测
- 投标截止时间 AI 决策测试
- 模板提取器附件保留
- Prepare vs. finalize 工作流阶段

### 7.4 `test_directory_generation.py`（1,472 行）

**质量：⭐⭐⭐⭐ 良好**

- 测试技术和商务目录生成
- 商务目录测试验证：workspace 隔离、outline.json 优先于模型结果、编号保留、schema 校验、超时行为、workspace 归档

### 7.5 `test_outline_quality_gate.py`（154 行）

**质量：⭐⭐⭐⭐ 良好**

- 用真实 outline/tender 数据测试质量门
- 覆盖证据比例和 fallback 检测的通过/失败场景

### 7.6 `test_business_format_cleaner.py`（1,168 行）

**质量：⭐⭐⭐⭐ 良好**

- 测试标题匹配、分页清理、目录插入、章节边界处理
- 使用真实 DOCX fixtures 做集成测试

---

## 8. 风险清单汇总

### 🔴 P0（必须修复）

无。

### 🟡 P1（应该修复）

| # | 问题 | 文件 |
|---|------|------|
| 1 | `parsing.py` 5,660 行需拆分 | `parsing.py` |
| 2 | `opencode_client.py` 1,570 行需拆分 | `opencode_client.py` |
| 3 | `BusinessTenderReview.jsx` 1,878 行需拆分 | `BusinessTenderReview.jsx` |
| 4 | 评分权重为无文档魔数 | `parsing.py` `_business_core_field_score()` |
| 5 | 线程模型高负载下可能耗尽线程池 | `opencode_client.py` |
| 6 | 30+ useState hooks 状态爆炸 | `BusinessTenderReview.jsx` |

### 🟢 P2（建议优化）

| # | 问题 | 文件 |
|---|------|------|
| 7 | 重复正则模式（DATE_PATTERN / BID_DEADLINE_DATE_PATTERN） | `parsing.py` |
| 8 | OCR 失败静默返回空文本 | `parsing.py` |
| 9 | sys.path 模块级注入 | `parsing.py` |
| 10 | `_save_extraction_trace()` 覆盖警告可疑 | `business_template_extractor.py` |
| 11 | 死代码 `return None` after `raise` | `opencode_client.py:984` |
| 12 | `_mark_appendix_synced` / `_mark_letter_synced` 重复 | `business_parse_assets.py` |
| 13 | 样式配置分散在 3 个文件 | `bid-business-format-cleaner` |
| 14 | `chineseNumber` 只处理到 100 | `BusinessOutlineReview.jsx` |

---

## 9. 总体评价

| 维度 | 评分 | 说明 |
|------|------|------|
| **架构设计** | ⭐⭐⭐⭐⭐ | 契约优先设计，S1 交接契约、Skill manifest、schema 版本管理提供优秀的阶段间稳定性 |
| **代码质量** | ⭐⭐⭐⭐ | 多层验证（确定性提取 → AI 审核 → 脚本校验 → 质量门），个别超大文件需拆分 |
| **测试覆盖** | ⭐⭐⭐⭐⭐ | 10,000+ 行测试覆盖 6 个文件，subprocess-based skill 测试特别有价值 |
| **Skill 架构** | ⭐⭐⭐⭐⭐ | 后端编排与 Skill 执行通过 manifest 驱动 CLI 工具实现干净分离 |
| **规范合规** | ⭐⭐⭐⭐⭐ | 严格遵循项目规范 |

**总结：彭维锋负责的解析/目录/装配/格式/导出模块是系统的入口和出口链路。契约优先设计和测试覆盖是突出亮点。主要改进方向是拆分超大文件（parsing.py、opencode_client.py）、为评分权重添加文档、优化线程模型。**

---

## 10. 关键亮点

1. **契约优先设计**：S1 交接契约、Skill manifest 契约和 schema 版本管理提供了优秀的阶段间稳定性
2. **纵深防御**：多层验证（确定性提取 → AI 审核 → 脚本校验 → 质量门）
3. **测试覆盖**：10,000+ 行测试，subprocess-based skill 测试特别有价值
4. **Skill 架构**：后端编排与 Skill 执行通过 manifest 驱动 CLI 工具实现干净分离
