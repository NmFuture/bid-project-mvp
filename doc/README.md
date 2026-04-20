# doc 目录说明

> 用途：统一说明当前哪些文档是背景资料，哪些文档是当前开发应直接遵循的口径。

## 当前开发以这 4 份为准

1. [05-MVP主链路说明.md](/Users/wlb/Agent/bid-project/doc/05-MVP主链路说明.md)
- 讲清楚成品思路和当前 MVP 落地方式

2. [06-MVP接口文档.md](/Users/wlb/Agent/bid-project/doc/06-MVP接口文档.md)
- 当前 `Web -> FastAPI` 正式接口口径

3. [07-FastAPI承接与前端改造.md](/Users/wlb/Agent/bid-project/doc/07-FastAPI承接与前端改造.md)
- FastAPI 如何统一承接 `/api`
- 哪些阶段真实执行，哪些先 mock

4. [08-MVP部署说明.md](/Users/wlb/Agent/bid-project/doc/08-MVP部署说明.md)
- 当前 MVP 的部署口径
- Docker Compose 组成
- 客户内网使用方式

## 协作约定

- [GIT_WORKFLOW.md](/Users/wlb/Agent/bid-project/doc/GIT_WORKFLOW.md)
  - 当前仓库多人协作的分支、PR、review、合并约定

## 背景资料

下面几份保留作为背景和设计参考，不直接作为当前开发实现基线：

- [01-需求与目标.md](/Users/wlb/Agent/bid-project/doc/01-需求与目标.md)
- [02-技术选型与架构.md](/Users/wlb/Agent/bid-project/doc/02-技术选型与架构.md)
- [03-UI设计.md](/Users/wlb/Agent/bid-project/doc/03-UI设计.md)
- [04-路线备选与功能盘点.md](/Users/wlb/Agent/bid-project/doc/04-路线备选与功能盘点.md)

说明：

- 这些文档保留了较完整的产品设想和讨论过程
- 其中部分技术表述早于当前实现决策
- 真正开发时，若与 `05-08` 冲突，以 `05-08` 为准

## 已删除

- 早期“两天联调计划”文档

删除原因：

- 这是早期两天联调计划
- 已包含较多旧口径，例如旧接口名、旧前端技术假设、旧阶段实现方式
- 当前已被 `05-08` 覆盖
