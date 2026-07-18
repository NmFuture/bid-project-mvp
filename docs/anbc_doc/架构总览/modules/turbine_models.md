# turbine_models

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/turbine_models.py` |
| 层级 | 服务层 |
| 领域 | 基础设施与通用 |
| 行数 | 328 |

**职责**: 风机机型识别与归一化中心：机型正则（EW/SE 系列，容忍「上置/下置/海外版/碳叶片」等布局后缀）、噪声过滤（证书号/标准号误匹配）、项目机型明细归一、素材名推断机型、机型参数表 xlsx 选项抽取、素材-机型匹配度 `material_model_fit`。

## Input / Output
- `normalize_project_turbine_model(s)`、`project_turbine_model(project)`、`turbine_model_from_material_name`、`extract_turbine_model_options_from_xlsx_bytes`。
- 布局后缀词（上置/下置）只用于内部选型与素材过滤（AGENTS.md 规约：正式材料只写英数字型号编码）。

## 调用链
- **上游**: `bid_project_state`、`project_stage_flow`、`technical_gap_planner/ai_fill/fact_table`、`tech_assembly`、`material_upload_metadata`、`technical_turbine_material_options`、`business_gap_planning`、`business_document_service`。
- **下游**: openpyxl。

## 中间数据与状态
- 机型正则与噪声正则常量。
