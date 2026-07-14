# business_parse_assets

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/business_parse_assets.py` |
| 层级 | 服务层 |
| 领域 | 商务标 |
| 行数 | 580 |

**职责**: 商务标 S1 解析资产（附表/承诺函/商务评分）的确认与同步：物化 docx、单项/全量 approve、确认后按固定目录归档进商务素材库（schema `business-parse-assets-v1`）。

## Input（输入）
- 项目 dict + 资产 id + approve 请求；物化源自 `parsing.materialize_parse_*_docx_assets`。

## Output（输出）
- 资产确认状态（写回 parse 结果）；确认件入库素材库固定目录：附表/承诺函 →「资格审查与商务响应成册」，商务评分 →「项目过程稿与澄清文件」；错误以 `BusinessParseAssetError(status_code, detail)` 显式抛出。

## 调用链
- **上游**: `bid_parse_service`（approve 端点组）、`bid_project_service`（`sync_business_parse_assets` 开关）。
- **下游**: `parsing`（物化）、`business_material_store`（入库）、`bid_parse_state`、`identity`、`material_folder_scope`、`workspace_artifacts`（parse 目录）。

## 中间数据与状态
- workspace parse 目录内物化 docx；素材库归档目录常量；资产 schema 版本。
