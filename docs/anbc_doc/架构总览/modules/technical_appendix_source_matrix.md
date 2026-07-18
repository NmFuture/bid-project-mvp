# technical_appendix_source_matrix

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/technical_appendix_source_matrix.py` |
| 层级 | 服务层 |
| 领域 | 技术标 |
| 行数 | 256 |

**职责**: 附表来源矩阵加载器：读运营维护的 Excel（默认 `technical_appendix_source_matrix.xlsx`，可用环境变量 `TECHNICAL_APPENDIX_SOURCE_MATRIX_PATH` 覆盖），把「附表编码 → 素材来源规则（项目定制/标准文件/其他）」解析成结构化路由表。

## Input（输入）
- 来源矩阵 xlsx（openpyxl）；附表编码正则（支持「附表 A.1」「附表 D.1~D.3」区间展开）；来源关键词组（project/项目定制、standard/标准文件、other/其他）。

## Output（输出）
- `load_appendix_source_matrix_for_project(project)`：附表编码归一（如 `A.1`）→ 来源规则清单（供 gap planner 给每张附表路由素材来源）。

## 调用链
- **上游**: `technical_gap_planner`。
- **下游**: openpyxl、`core.config`。

## 中间数据与状态
- 矩阵文件本身是运营配置（对账文件《技术标表格填写文件来源.xlsx》与现网一致，见 20260708 全链路梳理）；无 DB 状态。
