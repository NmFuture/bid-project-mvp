# doc 目录说明

> 用途：让新会话和新同事能在 5 分钟内知道“当前该看什么、历史资料在哪里”。
> 更新日期：2026-05-02

## 先看这 3 份

1. [14-甲方新增需求待办.md](/Users/wlb/Agent/bid-project/doc/14-甲方新增需求待办.md)
- 当前唯一的下一阶段待办池
- 按实施难度升序排列
- 每条待办都有“完成情况”
- 完成或推进一项后，同步记录到 `/Users/wlb/Agent/bid-project/code/progress.md`

2. [15-技术标与商务标需求整理.md](/Users/wlb/Agent/bid-project/doc/15-技术标与商务标需求整理.md)
- 技术标、商务标 Word 需求整理结果
- 用作待办来源和讨论依据

3. [README.md](/Users/wlb/Agent/bid-project/README.md)
- 当前 MVP 运行、部署、健康检查和验收入口
- 新人先按这里把系统跑起来

## 做待办时的协作规则

- 用户准备开始按待办清单推进，每个待办会尽量开一个新会话。
- 新会话先读 `doc/14-甲方新增需求待办.md`、`code/progress.md` 和 `code/AGENT.md`。
- 一次会话尽量只处理一个待办，避免把多个需求混在一个大改动里。
- 完成后必须做两件事：
  - 把 `doc/14-甲方新增需求待办.md` 对应待办的“完成情况”改为 `[x]`
  - 在 `code/progress.md` 写清楚改动目标、变更文件和验证结果
  - 重新部署相关服务给用户检查；前端展示改动至少重建并重启 compose 的 `web` 服务
  - 为本项待办创建一次 git commit，避免多项需求混在同一个提交里

## 当前运行与实现基线

> 2026-05-02 口径：技术标工作流主进度已经收敛为 6 个节点：模板与目录、审核目录、缺口处理、生成标书、共创、导出。内部仍保留 S1-S10 状态号和若干兼容接口名，但用户主路径不再依赖独立目录生成页、补料页、审核备料页或独立 S8 页面。若下列旧文档仍出现 S4/S5/S6/S8 作为独立主流程，以 `14-甲方新增需求待办.md` 和 `code/progress.md` 的最新记录为准。

- [05-MVP主链路说明.md](/Users/wlb/Agent/bid-project/doc/05-MVP主链路说明.md)
  - 主链路口径；已补充 6 节点当前口径，历史 S0-S10 描述仅作为内部兼容背景

- [06-MVP接口文档.md](/Users/wlb/Agent/bid-project/doc/06-MVP接口文档.md)
  - 当前 `Web -> FastAPI` 接口基线；接口名保留 S 段兼容，页面主路径按 6 节点理解

- [08-MVP部署说明.md](/Users/wlb/Agent/bid-project/doc/08-MVP部署说明.md)
  - Docker Compose 部署口径和环境变量说明

- [11-内网离线部署说明.md](/Users/wlb/Agent/bid-project/doc/11-内网离线部署说明.md)
  - 内网离线交付、镜像打包和现场部署步骤

- [12-数据存储与素材库数据说明.md](/Users/wlb/Agent/bid-project/doc/12-数据存储与素材库数据说明.md)
  - PostgreSQL、MinIO、本地文件目录和素材库数据落点；缺口处理产物已进入项目级真实文件状态，是否沉淀为全局可复用素材库仍需单独设计

- [13-S7技术标正文拼装与S8素材校验说明.md](/Users/wlb/Agent/bid-project/doc/13-S7技术标正文拼装与S8素材校验说明.md)
  - 生成标书与覆盖诊断实现口径；S8 覆盖页保留为诊断/导出检查能力，不再是主进度节点

## 协作与对外资料

- [GIT_WORKFLOW.md](/Users/wlb/Agent/bid-project/doc/GIT_WORKFLOW.md)
  - 分支、PR、合并和质量门禁约定

- [10-甲方技术细议草案-合同预期最终交付版.md](/Users/wlb/Agent/bid-project/doc/10-甲方技术细议草案-合同预期最终交付版.md)
  - 合同沟通和最终交付范围口径

## 已归档

早期设计、路线讨论、迁移方案和阶段分工资料已经移入 [archive/](/Users/wlb/Agent/bid-project/doc/archive/README.md)。

归档原因：

- 它们对理解历史有价值，但不是当前开发入口。
- 部分内容早于 8 服务 Docker Compose、真实 S7/S8、`doc/14` 待办池等当前口径。
- 后续实现若与归档资料冲突，以当前根 README、`doc/14`、`doc/15` 和本文件列出的运行基线为准。
