# identity

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/identity.py` |
| 层级 | 服务层 |
| 领域 | 权限与审计 |
| 行数 | 418 |

**职责**: 身份与归属的中心定义：客户静态注册表 `CUSTOMER_REGISTRY`（华能/大唐/国家能源/上海电气，含别名归一）、素材路径身份分类（tier 别名映射）、项目身份构建（`build_project_identity`：客户 id/规范名推导）、项目素材空间 `build_project_material_scope`、客户/项目匹配判定。

## Input / Output
- `canonical_customer(name)`：别名→规范客户；`classify_material_path(path)`：路径→{tier, 客户, 项目}；`customer_matches/project_matches`（素材过滤用）；`material_identity`。

## 调用链
- **上游**: `route_auth`（key-accounts）、`bid_project_state/service`、`material_folder_scope`、`material_raw_file_filter`、`material_upload_metadata`、两轨 gap/wiki 域。
- **下游**: `bid_type`。

## 中间数据与状态
- 客户注册表常量（当前静态维护）；tier 别名 `ROOT_TIER_ALIASES`。
