# kb_schema

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/kb_schema.py` |
| 层级 | 服务层 |
| 领域 | 基础设施与通用 |
| 行数 | 105 |

**职责**: 知识卡片 schema 定义：`KnowledgeCard`（field/value + 来源）与 `KnowledgeSource`（doc/quote/confidence/location）、锁定状态枚举（locked_by_user / system_high_conf / unconfirmed / conflict）。

## 调用链
- **上游**: 未在 app/ 内被 import（供 Skill/知识库方向消费，运行期挂载点未在代码中确认）。
- **下游**: 无。

## 中间数据与状态
- dataclass schema；置信度 clamp。
