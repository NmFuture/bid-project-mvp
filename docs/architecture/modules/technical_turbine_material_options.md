# technical_turbine_material_options

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/technical_turbine_material_options.py` |
| 层级 | 服务层 |
| 领域 | 技术标 |
| 行数 | 136 |

**职责**: 风机机型下拉选项的动态提取：扫描技术标/通用素材，识别「机型参数表」类 xlsx 并解析出机型选项；素材名兜底推断作为提示。

## Input / Output
- Input: DB 全量 RawFile（过滤 bidType ∈ 技术标/通用）；参数表识别启发（名称/目录）。
- Output: `list_technical_turbine_model_options()` → 机型选项（含来源文件 id/名/目录）+ fallback hints；单文件解析失败记日志不阻断。

## 调用链
- **上游**: `technical_material_store.turbine_model_options`（`GET /api/technical/materials/turbine-model-options`）。
- **下游**: DB `RawFile`、`minio_client`（下载 xlsx）、`turbine_models`（xlsx 解析/名称推断）、`identity`。

## 中间数据与状态
- 无持久状态；每次实时扫描。
