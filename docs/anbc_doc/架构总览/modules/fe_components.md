# fe_components（components/ 五个子目录汇总）

| | |
|---|---|
| 源文件 | `code/sewpg-bid-frontend/src/components/{layout,modals,shared,states,ui}` |
| 层级 | 前端组件 |
| 领域 | 共享 |
| 行数 | 24 个文件 |

**职责与清单**:

| 目录 | 组件 | 说明 |
|---|---|---|
| layout | AppShell | 全局壳：侧边导航（按角色显示工作区）、顶栏、内容区 |
| modals | AuditDetailModal | 审计详情弹窗（两轨审计页共用） |
| states | PageState（PageLoading/PageError） | 页面级加载/错误态 |
| shared | **OnlyOfficeEmbed / OnlyOfficeWorkspace**（文档编辑器嵌入，共创与预览的核心）、StageProgress / StageBreadcrumb（阶段进度）、DataCard、FilterBar、PageHeader、Pagination、StatusBadge、RoleChip、Toast、Skeleton、EmptyState、MarkdownLite、MaterialMatchProgressModal | 页面骨架与业务通用件 |
| ui | Button、IconButton、Badge、Dialog、FileButton、Toolbar、utils | 基础 UI 原子件 |

## 调用链
- **上游**: 全部页面。
- **下游**: `config/onlyoffice`（编辑器组件）、react-router。

## 中间数据与状态
- OnlyOffice 组件持有编辑器实例生命周期（documentKey 变化即重建会话）。
