# technical_coverage

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/technical_coverage.py` |
| 层级 | 服务层 |
| 领域 | 技术标 |
| 行数 | 150 |

**职责**: 技术标覆盖率计算：优先取装配产出的 coverage，否则按目录树 × 各章 generationMode 推导三色覆盖（full/partial/no），加权计算总百分比。

## Input / Output
- Input: 项目 dict（fill_state.coverage / outline_state.nodes / fill_state.sections）。
- Output: `{percentage: (full + 0.5*partial)/total, fullCover, partialCover, noCover, tree, partialItems, noCoverItems}`；无目录时返回 100%。

## 调用链
- **上游**: `technical_delivery_service`（coverage 端点与导出前检查）。
- **下游**: 无服务依赖（纯函数）。

## 中间数据与状态
- 无持久状态；generationMode → 覆盖状态映射。
