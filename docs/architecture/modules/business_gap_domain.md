# business_gap_domain

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/business_gap_domain.py` |
| 层级 | 服务层 |
| 领域 | 商务标 |
| 行数 | 556 |

**职责**: 商务缺口计划的领域规则纯函数库：任务/目录引用/产物查找、产物变更后任务状态重算、装配模式与素材用途映射、上传内容解码、toc 引用状态同步。

## Input / Output
- `find_task/find_toc_ref/find_artifact_in_task`：按 id 查找（KeyError→404）。
- `recompute_task_after_artifact_change(task)`：产物增删后重算 decision/status（终审的任务级实现）。
- `update_toc_ref_statuses(plan)`：目录节点状态 = 其绑定任务状态聚合。
- `assembly_mode_for_artifact` / `material_usage_for_assembly_mode`：产物→装配模式→素材用途（section_merge/section_fill 类）。
- `decode_upload_content`：base64/data-URL 上传解码；`unique_path`/`safe_filename` 落盘防冲突。

## 调用链
- **上游**: `business_gap_service`、`business_gap_state`、`business_gap_refresh`。
- **下游**: `bid_type`、`file_utils`、`material_folder_scope`。

## 中间数据与状态
- 计划结构（tasks[].resolvedArtifacts/decision/status、tocRefs[].taskIds）；无 IO。
