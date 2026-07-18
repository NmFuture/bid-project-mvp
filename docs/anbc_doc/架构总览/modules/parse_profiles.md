# parse_profiles

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/parse_profiles.py` |
| 层级 | 服务层 |
| 领域 | 解析与AI引擎 |
| 行数 | 69 |

**职责**: S1 解析的双轨画像常量 `ParseProfile`：绑定每轨的解析 Skill、schema 版本、workspace 目录名与解析目标类目。

## Input / Output
- `resolve_parse_profile(bid_type)` → TECHNICAL / BUSINESS 画像。
- 技术标：Skill `bid-tech-tender-structured-parser`、schema `bid-tender-structured-v1`、目录 `technical-workspace`，targets 含评分细则/项目基础信息/风机核心参数/性能保证指标/环境适应性/专题方案/附表和供货范围/考核条款/投标相关日期。
- 商务标：Skill `bid-business-tender-structured-parser`、schema `bid-business-tender-structured-v1`、目录 `business-workspace`。

## 调用链
- **上游**: `parsing`、`bid_parse_service`、`business_parse_assets`、`business_gap_planning`、`workspace_artifacts`。
- **下游**: `bid_type`。

## 中间数据与状态
- 纯常量，无状态。workspace 目录名决定解析产物在数据卷内的落点。
