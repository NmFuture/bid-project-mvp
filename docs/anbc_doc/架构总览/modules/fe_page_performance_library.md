# fe_page_performance_library（SharedPerformanceLibrary）

| | |
|---|---|
| 源文件 | `workspaces/shared/pages/SharedPerformanceLibrary.jsx` |
| 层级 | 前端页面 |
| 领域 | 共享 |
| 行数 | 917 |

**职责**: 业绩库页 `/workspace/shared/materials/performance`（两轨共用，各自素材菜单重定向到此）：业绩分类多维检索（场景/功率/机型/年份/标签）、Excel 汇总表导入（preview→import）、分类详情与条目、合同附件上传/下载/OnlyOffice 预览、状态启停。

## 调用链
- **下游**: `performanceAPI`（← route_performance → performance_package/library_service）。

## 中间数据与状态
- 导入预览态；分类过滤器。
