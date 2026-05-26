# 当前开发计划

> 历史 MVP 联调计划已经完成并从当前工作树正文中移除。当前计划以双轨独立化后的收口验收为准。
> 更新日期：2026-05-26

## 当前目标

技术标和商务标已经完成第一轮双轨独立化，当前目标是把两条链路按生产验收继续收稳：

- 独立前端入口和页面
- 独立 API
- 独立后端 service
- 独立 Skill
- 独立素材库和 Wiki
- 独立文档生成、编辑和导出逻辑

## 权威入口

- `/Users/wlb/Agent/bid-project/doc/31-技术标与商务标双轨独立化实施计划.md`
- `/Users/wlb/Agent/bid-project/doc/README.md`
- `/Users/wlb/Agent/bid-project/code/progress.md`

## 下一批工作

1. 用真实技术标、商务标样本分别跑端到端验收：解析、目录、素材匹配、正文生成、共创、Word/PDF 下载。
2. 继续复扫 `store.py` / `material_store.py`，防止业务规则重新回流到底层持久化门面。
3. 继续统一 README、接口说明和协作文档中的双轨口径，避免误导后续 AI。
4. 生产级权限边界另开专项：前端 workspace guard 只做体验约束，后端 route/service 才是强授权边界。
