# 项目代码审阅汇总

> **审阅日期**：2026-06-13
> **项目**：AI 数智化投标平台（bid-project-mvp）
> **审阅范围**：商务标端到端全链路

---

## 审阅文档索引

| 文档 | tmux 名称 | 负责人 | 审阅范围 |
|------|----------|--------|---------|
| [kimi-1-review.md](./kimi-1-review.md) | kimi-1 | 安博成（Whisper） | 素材库、素材标签、共用业绩库、素材清洗、商务 Wiki |
| [kimi-2-review.md](./kimi-2-review.md) | kimi-2 | 肖雨航（Sean-yh） | 素材匹配、处理方式统计、商务事实表、AI 填写 |
| [kimi-3-review.md](./kimi-3-review.md) | kimi-3 | 彭维锋（pengweifeng） | 智能解析、目录生成、正文生成、格式处理、导出 |

---

## 整体评分概览

| 维度 | kimi-1 (安博成) | kimi-2 (肖雨航) | kimi-3 (彭维锋) | 整体 |
|------|----------------|----------------|----------------|------|
| 架构设计 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| 代码质量 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| 错误处理 | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| 测试覆盖 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| 规范合规 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |

---

## 跨模块 P0 风险汇总

| # | 模块 | 问题 | 文件 | 修复建议 |
|---|------|------|------|---------|
| 1 | kimi-1 | 硬编码本地路径 | `wiki_generation.py:37` | 删除或改为配置项 |
| 2 | kimi-1 | 全局 shadow 压平弹窗 | `index.css:255-258` | 用白名单覆盖 |
| 3 | kimi-1 | 业绩库主表 1280px 溢出 | `BusinessPerformanceLibrary.jsx` | 响应式表格 |

---

## 跨模块 P1 风险汇总

| # | 模块 | 问题 | 修复建议 |
|---|------|------|---------|
| 1 | kimi-1 | `ensure_raw_file` / `_ensure_wiki_node` 全量查询 O(n) | 改为直接 DB 查询 |
| 2 | kimi-1 | `wiki_generation.py` 2000+ 行 | 拆分子模块 |
| 3 | kimi-1 | 素材库 API 缺认证 | 加 `Depends(current_user)` |
| 4 | kimi-2 | **报价事实字段缺失** | 在 `BASIC_BUSINESS_FACT_FIELD_SPECS` 补充 |
| 5 | kimi-2 | `_run_async()` 同步转异步反模式 | 改用 `asyncio.create_task` 或结构调整 |
| 6 | kimi-2 | `save_facts()` 静默吞错 | 添加日志记录 |
| 7 | kimi-2 | `business_gap_service.py` 1694 行 | 拆分子模块 |
| 8 | kimi-3 | `parsing.py` 5,660 行 | 拆分为 3-4 个模块 |
| 9 | kimi-3 | `opencode_client.py` 1,570 行 | 拆分或重构为 async |
| 10 | kimi-3 | 评分权重无文档 | 添加注释说明设计意图 |
| 11 | kimi-3 | 线程模型高负载风险 | 考虑 async 模式 |

---

## 共性问题

### 1. 超大文件

这是三个模块共同的最突出问题：

| 文件 | 行数 | 建议目标 |
|------|------|---------|
| `parsing.py` | 5,660 | 拆分为 text_extraction、field_scoring、section_tree、ocr_bridge |
| `BusinessMaterialDB.jsx` | 2,596 | 拆分为 Tree / FileList / UploadDialog / TagManager |
| `test_business_parse_skill_script.py` | 4,742 | 按功能域拆分 |
| `BusinessGapRecognition.jsx` | 2,221 | 拆分为 FactModal / MaterialPicker / TableFill 等 |
| `wiki_generation.py` | 2,000+ | 拆分为 inventory / ocr / manifest / skill_execution |
| `BusinessTenderReview.jsx` | 1,878 | 拆分为 8+ 表格组件 |
| `opencode_client.py` | 1,570 | 按 skill 类型拆分方法组 |
| `business_gap_service.py` | 1,694 | 按操作域拆分 |

### 2. 同步转异步桥接

多处使用 `_run_async()` 或 `asyncio.run()` 从同步上下文调用异步代码，在 FastAPI 嵌套事件循环中可能失败：

- `business_gap_planning.py`
- `business_gap_table_fill.py`
- `bid_generation_flow.py`

**建议：** 统一使用 `asyncio.create_task()` 或 `loop.run_in_executor()`。

### 3. 测试覆盖缺口

| 模块 | 缺失测试 |
|------|---------|
| kimi-2 | `business_gap_fact_table.py`（规范化标签、源优先级） |
| kimi-2 | `business_gap_table_fill.py`（填写源准备） |
| kimi-2 | `business_gap_refresh.py`（模板刷新） |
| kimi-2 | `business_gap_ai_draft.py`（AI 草稿生成） |

---

## 流水线连通性

```
S1 解析 (kimi-3) → S2 目录 (kimi-3) → S3 匹配 (kimi-2) → S4 装配 (kimi-3) → 格式 (kimi-3) → 导出 (kimi-3)
                              ↕                    ↕
                    素材库/标签/Wiki (kimi-1)    事实表 (kimi-2)
                              ↕
                    共用业绩库 (kimi-1)
```

**连接评估：**

| 连接点 | 质量 | 说明 |
|--------|------|------|
| S1 → S2 | ⭐⭐⭐⭐⭐ | S1 交接契约生产级 |
| S2 → S3 | ⭐⭐⭐⭐ | 目录 → 匹配连接清晰 |
| kimi-1 → S3 | ⭐⭐⭐⭐ | 素材库/标签/业绩库可被匹配读取 |
| S3 → S4 | ⭐⭐⭐⭐ | manifest 契约定义完善 |
| S4 → 格式 | ⭐⭐⭐⭐ | 大纲感知匹配 |

---

## 建议优先修复顺序

1. **立即修复**（P0）：硬编码路径、UI 溢出、shadow 压平
2. **本周修复**（P1）：报价事实字段缺失、sync-to-async 桥接、静默吞错、API 认证
3. **下阶段**（P1-P2）：超大文件拆分、评分权重文档化、测试覆盖补充
4. **持续优化**（P2）：性能优化、死代码清理、配置集中化

---

*审阅由 AI Agent (kimi-1/kimi-2/kimi-3) 自动完成，基于代码静态分析和文档审阅。*
