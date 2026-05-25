# 当前开发计划

> 历史 MVP 联调计划已经完成并从当前工作树正文中移除。当前计划以双轨独立化为准。
> 更新日期：2026-05-25

## 当前目标

把技术标和商务标拆成两条独立业务链路：

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

1. 继续拆底层 `store` 中仍按 `bidType` 分支承载的业务逻辑。
2. 继续拆底层 `material_store` 中仍依赖通用持久化结构的业务 URL 和权限边界。
3. 继续统一 README、接口说明和协作文档中的双轨口径，避免误导后续 AI。
4. 在后端回归稳定后，跑前端 `npm run check` 和必要的页面冒烟。
