# kimi-2 代码审阅报告

> **审阅范围**：素材匹配、处理方式统计、商务事实表、AI填写
> **负责人**：肖雨航（Sean-yh）
> **审阅日期**：2026-06-13
> **文档版本**：v1.0

---

## 1. 审阅范围概览

| 模块类型 | 文件数量 | 核心文件 |
|---------|---------|---------|
| 后端服务 | 14+ | `business_gap_service.py`, `business_gap_planning.py`, `business_gap_domain.py`, `business_gap_fact_table.py`, `business_gap_table_fill.py`, `bid_generation_flow.py`, `bid_document_flow.py` |
| Skills | 3 | `bid-business-gap-planner`, `bid-business-table-fill`, `bid-business-fact-table-builder`（不存在，见说明） |
| 前端页面 | 1 | `BusinessGapRecognition.jsx` |
| 测试 | 2 | `test_business_gap_planner.py`, `test_bid_material_scope_services.py` |

---

## 2. 架构概览

代码实现了清晰的分层架构：

```
API Routes (business.py)
  → BusinessGapService (business_gap_service.py) — 编排层
    → BusinessGapPlanning (business_gap_planning.py) — 计划构建 & Skill 调用
    → BusinessGapDomain (business_gap_domain.py) — 领域逻辑 & 任务状态机
    → BusinessGapFactTable (business_gap_fact_table.py) — 事实表构建
    → BusinessGapTableFill (business_gap_table_fill.py) — AI 表格填写准备
    → BusinessGapState (business_gap_state.py) — 状态管理
    → BusinessGapRepository (business_gap_repository.py) — 持久化门面
    → BusinessGapRefresh (business_gap_refresh.py) — 模板/素材刷新
    → BusinessGapAiDraft (business_gap_ai_draft.py) — AI 草稿文档生成
```

---

## 3. 后端服务层审阅

### 3.1 `business_gap_service.py`（1694 行）

**代码质量：⭐⭐⭐⭐ 良好**

**优点：**

- 清晰的 service 类，每个操作都有对应方法（gaps, facts, update_task, upload_artifact 等）
- 良好的关注点分离：委托给 domain、planning、state、repository 模块
- 完善的输入校验和中文错误消息
- 三种处理方式清晰实现：`fixed_material`（素材选择）、`ai_table_fill`（AI填写）、`manual_upload`（人工补充）

**问题：**

| 级别 | 问题 | 位置 | 说明 |
|------|------|------|------|
| 🟡 P1 | 文件过长（1694 行） | 全文件 | `selectable_materials()` 约 180 行，`material_preview()` 约 95 行，应提取为独立模块 |
| 🟡 P1 | `save_facts()` 静默吞错 | `business_gap_service.py:625` | `store_business_bidder_facts` 失败时 `except Exception: pass`，应至少记录日志 |
| 🟢 P2 | Request 对象耦合 | `gaps()` 方法 | service 层接收 FastAPI `Request` 来提取 URL scope，耦合了 HTTP 关注点 |

### 3.2 `business_gap_planning.py`（1402+ 行）

**代码质量：⭐⭐⭐⭐ 良好**

**优点：**

- 健壮的素材索引：material index、template index、evidence segments、Wiki index
- 良好的多数据源处理：DB Wiki 节点、文件 Wiki、素材库、清洗后 Word 文档
- 丰富的证据段落提取
- 业绩库集成（`performance_library_service` 和 `performance_package_service`）

**问题：**

| 级别 | 问题 | 位置 | 说明 |
|------|------|------|------|
| 🟡 P1 | `_run_async()` 同步转异步反模式 | `line 424, 771, 98` | 如果在已有事件循环的 FastAPI 上下文中调用，会抛出 `RuntimeError: This event loop is already running` |
| 🟢 P2 | 魔法数字 | 多处 | 证据段落上限 2000、卡片 600、映射行 120，应提取为配置常量 |
| 🟢 P2 | 哈希碰撞风险 | `_stable_short_id` | SHA1 截断到 10 hex chars（40 bits），大数据集碰撞概率不可忽略 |
| 🟢 P2 | 未使用的 import | `line 7, 10` | `subprocess` 和 `threading` import 残留 |

### 3.3 `business_gap_domain.py`（556 行）

**代码质量：⭐⭐⭐⭐⭐ 优秀**

- 清晰的领域逻辑，函数命名规范
- 8 种装配模式明确定义：`template_fill_docx`, `table_fill_from_material`, `attach_whole_file`, `embed_scan_or_image`, `extract_and_summarize`, `extract_segment`, `ai_draft`, `manual_upload`
- `recompute_task_after_artifact_change()` 实现了完整的状态机转换
- `task_fill_plan()` 产出结构化的填写计划，包含显式依赖标志
- 防御性编程，多处使用 `isinstance` 检查

**小问题：**

- `material_usage_for_assembly_mode` dict 每次调用都重新分配，应改为模块级常量
- `task_can_ai_draft` 的正则启发式对中文关键词依赖较脆弱

### 3.4 `business_gap_fact_table.py`（931 行）

**代码质量：⭐⭐⭐⭐ 良好**

**字段完整性检查：**

| 类别 | 字段 | 状态 |
|------|------|------|
| **报价 (Pricing)** | 投标报价、币种、总价 | ⚠️ **缺失** — 未在 `BASIC_BUSINESS_FACT_FIELD_SPECS` 中 |
| **资质 (Qualifications)** | 营业执照信息、注册资本、信用代码、类型 | ✅ 存在 |
| **承诺 (Commitments)** | 由解析阶段承诺函处理 | ✅ 设计合理 |
| **附件 (Attachments)** | 存款账户号码、银行、编号 | ✅ 存在 |
| **业绩引用 (Performance)** | 通过 `add_performance_facts_from_parse_text()` 正则提取 | ✅ 存在 |

**优点：**

- 规范的标签规范化：`canonical_fact_label()` 有 60+ 别名
- 多源优先级系统：parse (260) < bidder profile (290) < project identity (320)
- 智能占位符检测：`fact_value_is_placeholder()` 防止存储 label-as-value

**问题：**

| 级别 | 问题 | 位置 | 说明 |
|------|------|------|------|
| 🟡 P1 | **报价字段缺失** | `BASIC_BUSINESS_FACT_FIELD_SPECS` | 投标报价、币种、总价不是标准事实表条目，限制了 AI 填写对报价表格的能力 |
| 🟡 P1 | 单位剥离正则遗漏 | `canonical_fact_label` | 缺少 "万元"、"元/kWh"、"天" 等常见商业标单位 |
| 🟢 P2 | `_now_iso()` 重复定义 | `line 930` | 与 `bid_runtime_state.py` 中的同名函数重复 |

### 3.5 `business_gap_table_fill.py`（145 行）

**代码质量：⭐⭐⭐⭐ 良好**

- 简洁聚焦的模块，三个定义清晰的函数
- 正确的 fallback 机制：从清洗内容到原始内容
- Word/Excel 文件类型校验

**小问题：**

- `run_awaitable_sync()` 同步转异步桥接的同样风险
- 无缓存：每次调用都从 MinIO 重新下载所有素材

### 3.6 `business_gap_repository.py`（39 行）

**代码质量：⭐⭐⭐⭐⭐ 优秀**

- 极简门面，只包装 `workspace_project_access`
- 正确的错误工厂和描述性 code
- 读写访问模式分离清晰

### 3.7 `bid_generation_flow.py`（642 行）

**代码质量：⭐⭐⭐⭐ 良好**

- 10+ 进度阶段的生成流程
- 过期任务检测和恢复（1 小时超时）
- 线程执行 + Redis 队列集成
- 完善的审计日志

**问题：**

| 级别 | 问题 | 位置 | 说明 |
|------|------|------|------|
| 🟡 P1 | `_record_generation_audit_sync` 使用 `asyncio.run()` | `line 193` | 在异步上下文中调用会失败 |

### 3.8 `bid_document_flow.py`（386 行）

**代码质量：⭐⭐⭐⭐ 良好**

- OnlyOffice 集成，文档 key 版本管理
- PDF 转换双策略（OnlyOffice → LibreOffice 回退）
- 回调 token 校验保安全
- 下载 URL 主机白名单

---

## 4. Skills 审阅

### 4.1 `bid-business-gap-planner`

**质量：⭐⭐⭐⭐⭐ 优秀**

- 231 行 SKILL.md，规范清晰
- 6 个模块组明确定义
- 8 种装配模式有文档化语义
- 决策规则、风险标志和来源规则详尽
- 业绩库集成已文档化

### 4.2 `bid-business-table-fill`

**质量：⭐⭐⭐ 一般**

- 40 行，简洁但覆盖基本要素
- 缺少：错误恢复指导、部分填写处理

### 4.3 `bid-business-fact-table-builder`

**状态：❌ 不存在**

事实表构建完全在 `business_gap_fact_table.py` 服务层中处理。这是可接受的——事实表是确定性构建，不需要 LLM 推理。但专用 Skill 可以启用更智能的字段提取。

---

## 5. 前端审阅

### 5.1 `BusinessGapRecognition.jsx`（2221+ 行）

**代码质量：⭐⭐⭐⭐ 良好**

**优点：**

- 完善的弹窗系统：事实表维护、素材选择器、表格填写、生成进度、素材预览
- 三种处理方式可视化正确：
  - `fixed_material` → "固定素材" badge
  - `ai_table_fill` → "AI填写" badge
  - `manual_upload` → "人工补充" badge
- 素材选择器有模板/素材/段落标签和关键词搜索
- 事实表有行内编辑、状态 badge、来源引用

**问题：**

| 级别 | 问题 | 说明 |
|------|------|------|
| 🟡 P1 | 文件过大（2221+ 行） | 应拆分为 FactMaintenanceModal、BusinessMaterialPickerModal、BusinessTableFillModal 等子组件 |
| 🟢 P2 | 无错误边界 | React 错误会导致整个页面崩溃 |
| 🟢 P2 | `asArray` 工具函数内联定义 | 应放在共享工具文件 |
| 🟢 P2 | 多个标签字典内联 | 应提取到共享常量文件 |

---

## 6. 三种处理方式实现评估

| 处理方式 | 实现位置 | 状态 |
|---------|---------|------|
| **固定素材 (Fixed Material)** | 前端 `taskActionMode()` 检测 `fixed_material`；后端 `handlingMode` 字段；`businessMaterialKind=fixed` | ✅ 实现完善 |
| **AI填写 (AI Table Fill)** | `bid-business-table-fill` skill；`business_gap_table_fill.py` 准备；`taskActionMode()` 检测 `ai_table_fill` | ✅ 实现完善 |
| **人工补充 (Manual Supplement)** | `upload_artifact()` 服务方法；`manual_upload` handling mode；base64 解码上传 | ✅ 实现完善 |

---

## 7. 测试覆盖

### 7.1 `test_business_gap_planner.py`（2066+ 行）

**质量：⭐⭐⭐⭐ 良好**

覆盖场景：
- ✅ Gap planner runner 生成 TOC-based 计划
- ✅ Wiki 索引候选和风险
- ✅ 手动素材反馈优先级
- ✅ 评分资产附加
- ✅ 否定规则（业绩素材不用于投标函）
- ✅ 共用业绩库用于业绩任务
- ✅ 业绩包候选
- ✅ 模板候选从 template index
- ✅ API 集成测试（商务 workspace 隔离、手动任务、上传）

### 7.2 `test_bid_material_scope_services.py`（4546+ 行）

**质量：⭐⭐⭐⭐ 良好**

- 主要测试架构边界（business/technical 模块间无交叉导入）
- 验证模块重构完整性
- 测试 OCR 服务元数据注入

### 7.3 测试覆盖缺口

| 缺失测试 | 说明 |
|---------|------|
| `business_gap_fact_table.py` | 规范化标签、源优先级、占位符检测无单元测试 |
| `business_gap_table_fill.py` | 填写源准备逻辑无测试 |
| `business_gap_refresh.py` | 模板候选刷新逻辑无测试 |
| `business_gap_ai_draft.py` | AI 草稿生成无测试 |

---

## 8. 风险清单汇总

### 🔴 P0（必须修复）

无。

### 🟡 P1（应该修复）

| # | 问题 | 文件 |
|---|------|------|
| 1 | **报价事实字段缺失**（投标报价、币种、总价） | `business_gap_fact_table.py` |
| 2 | `_run_async()` 同步转异步在嵌套事件循环中会失败 | `business_gap_planning.py` |
| 3 | `save_facts()` 静默吞错 | `business_gap_service.py:625` |
| 4 | `business_gap_service.py` 1694 行需拆分 | `business_gap_service.py` |
| 5 | `BusinessGapRecognition.jsx` 2221 行需拆分 | `BusinessGapRecognition.jsx` |
| 6 | `bid_generation_flow.py` 在异步上下文中用 `asyncio.run()` | `bid_generation_flow.py:193` |
| 7 | `canonical_fact_label` 单位剥离遗漏 | `business_gap_fact_table.py` |
| 8 | `_now_iso()` 函数重复定义 | `business_gap_fact_table.py` / `bid_runtime_state.py` |

### 🟢 P2（建议优化）

| # | 问题 |
|---|------|
| 9 | `material_usage_for_assembly_mode` dict 每次调用重新分配 |
| 10 | `_stable_short_id` 40-bit 截断碰撞风险 |
| 11 | `business_gap_ai_draft.py` 产出文档过于基础 |
| 12 | 魔法数字（2000 segments、600 cards）应可配置 |
| 13 | 前端无错误边界 |

---

## 9. 总体评价

| 维度 | 评分 | 说明 |
|------|------|------|
| **架构设计** | ⭐⭐⭐⭐⭐ | 清晰分层，关注点分离优秀 |
| **代码质量** | ⭐⭐⭐⭐ | 命名规范、防御性编程好，个别超大文件需拆分 |
| **错误处理** | ⭐⭐⭐ | 部分静默失败需改进，需补充日志 |
| **测试覆盖** | ⭐⭐⭐ | 集成测试扎实，事实表和 AI 草稿的单元测试缺失 |
| **规范合规** | ⭐⭐⭐⭐⭐ | 严格遵循项目规范：标类隔离、Skill 边界、workspace 分离 |
| **功能完整性** | ⭐⭐⭐⭐ | 三种处理方式全部实现；报价事实字段缺失 |

**总结：肖雨航负责的素材匹配和 AI 填写模块是系统的核心业务逻辑层。架构设计优秀，三种处理方式（固定素材、AI填写、人工补充）实现完善。主要改进方向是补充报价事实字段、修复同步转异步桥接问题、补充测试覆盖。**
