# bid_project_service

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/bid_project_service.py` |
| 层级 | 服务层 |
| 领域 | 项目与状态流 |
| 行数 | 中型 |

**职责**: 项目 CRUD 的标类中性类 `BidProjectService`，实例化为 `business_project_service` / `technical_project_service` 两个门面：列表过滤、创建（payload 强制注入本轨 bidType）、更新、删除、阶段推进、模板回退配置、解析进度。

## Input（输入）
- 构造差异化参数：bid_type、404/400 文案、`clear_turbine_model`（商务轨清空机型字段）、`sync_business_parse_assets`（商务轨同步解析资产）。
- 各方法：project_id、前端请求体、列表过滤参数（status/reviewDecision/dateRange/分页）。

## Output（输出）
- 项目结构（详情/列表/阶段数组）；`ensure_project` 校验失败抛 HTTPException（404 不存在 / 400 标类不符）。

## 调用链
- **上游**: `routes/business.py`、`routes/technical.py` 项目端点组；`bid_parse_service`、各 flow。
- **下游**: `workspace_project_access`（真正读写）、`identity.build_project_material_scope`（项目素材空间）、`template_store`（模板回退）、`business_parse_assets`（商务资产同步）。

## 中间数据与状态
- 项目字段含 `bidType`、`reviewDecision`（participate 过滤口径）、阶段 stage 1-6、机型明细（技术轨）。
