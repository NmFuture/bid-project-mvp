# doc 目录说明

> 用途：统一说明当前哪些文档是背景资料，哪些文档是当前开发应直接遵循的口径。

## 当前开发以这 8 份为准

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

5. [12-数据存储与素材库数据说明.md](/Users/wlb/Agent/bid-project/doc/12-数据存储与素材库数据说明.md)
- 当前项目状态、文件目录、MinIO、素材库和 S7 拼装工作目录的数据落点

6. [13-S7技术标正文拼装与S8素材校验说明.md](/Users/wlb/Agent/bid-project/doc/13-S7技术标正文拼装与S8素材校验说明.md)
- 当前 S7/S8 的真实实现口径
- S2 JSON、Wiki、素材库和 `bid-tech-assembler` 的衔接方式

7. [14-甲方新增需求待办.md](/Users/wlb/Agent/bid-project/doc/14-甲方新增需求待办.md)
- 当前甲方新增需求、技术标/商务标后续能力和现存 mock 清理待办
- 用作下一阶段开发排期和拆任务的统一待办池

8. [15-技术标与商务标需求整理.md](/Users/wlb/Agent/bid-project/doc/15-技术标与商务标需求整理.md)
- 从技术标/商务标 Word 需求整理出的产品与实现口径
- 用作 `14-甲方新增需求待办.md` 的需求来源和讨论依据

## 当前协作与推进口径

- [09-二阶段分工与第一周里程碑.md](/Users/wlb/Agent/bid-project/doc/09-二阶段分工与第一周里程碑.md)
  - 当前 5 人团队的负责人、目标、边界与交付物

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
- 当前已被 `05-08`、`12-13` 覆盖
