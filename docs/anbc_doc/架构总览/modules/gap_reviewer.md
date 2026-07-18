# gap_reviewer

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/gap_reviewer.py` |
| 层级 | 服务层 |
| 领域 | 解析与AI引擎 |
| 行数 | 115 |

**职责**: 填写指令的确定性质检器：对 AI 填写指令做一致性（关键事实字段多值冲突）、交叉引用、T5 合理性、数值闭合（总装机=单机×台数类）四类检查。

## Input（输入）
- `review_fill_instructions(instructions)`：填写指令列表（field/value/locator）。
- 关键事实字段：项目名称/招标编号/招标人/投标机型/单机容量/机组台数/总装机容量。

## Output（输出）
- `{schemaVersion: "bid-tech-gap-review-v1", status: passed|needs_review, issueCount, issues[{check, severity, ...}]}`。

## 调用链
- **上游**: 未在 app/ 内被 import（由 Skill 侧/测试消费，未在代码中确认运行期挂载点）。
- **下游**: `derive_rules.check_numeric_closure`。

## 中间数据与状态
- 无持久状态；纯函数质检。
