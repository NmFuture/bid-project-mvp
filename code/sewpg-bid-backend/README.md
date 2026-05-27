# sewpg-bid-backend

当前正式后端目录。

## 目录

```text
sewpg-bid-backend/
  app/                # 正式 FastAPI 运行时代码
    api/              # 路由层
    core/             # 配置与基础设施
    services/         # 当前服务层与项目状态 store
  onlyoffice/         # OnlyOffice Document Server entrypoint
  opencode/           # opencode 镜像、配置与 skill 相关资产
  .localdata/         # 本机联调数据目录
```

## 当前约定

- 前端最终只调这里提供的 FastAPI
- 当前业务入口按 `/api/technical/...` 与 `/api/business/...` 双轨注册
- `onlyoffice/` 和 `opencode/` 只保留当前 compose 与主链路需要的运行资产
- 当前主链路按产品口径理解为：智能解析、投标判断、建项目、目录、素材匹配、正文生成、在线共创、格式处理、导出。
- 项目列表接口支持 `reviewDecision` 过滤；项目总览只展示已确认参与投标的项目，解析阶段临时承载记录由解析页恢复和处理。
- 旧阶段号仅作为部分内部文件名或历史兼容保留，不再作为产品文档口径。
- 旧 `/api/projects...`、`/api/materials...`、`/api/audit...` 不再作为真实业务入口注册，只在防回退测试和内部 URL 兼容替换中出现

## 当前代码分层

- `app/api/routes`
  - 当前业务 route 收口在 `business.py`、`business_gaps.py`、`technical.py`
  - 系统类 route 保留 `auth / dashboard / settings / system`
- `app/services/store.py`
  - 底层项目持久化门面；双轨业务规则、运行态默认值、阶段、解析、目录、正文、文档、review、覆盖率等规则正持续迁出
- `app/services/bid_runtime_state.py`
  - 运行态时间戳、事件、解析/目录/正文/文档默认状态和恢复规则；`now_iso` 的唯一归属
- `app/services/outline_generation.py`
  - 准备 `S1 模板与目录` 的目录 manifest，并由 FastAPI 本地规则引擎或 Skill 生成目录 JSON；`s2_toc_workdir` 是历史内部目录名
- `app/services/bid_directory_flow.py` / `bid_generation_flow.py` / `bid_document_flow.py`
  - 目录、正文生成和文档/OnlyOffice 中性底座；business/technical service 再包装各自业务入口
- `app/services/business_*`
  - 商务标项目、解析、目录、缺口、事实表、AI 草稿、表格填充、文档和素材/Wiki 专属逻辑
- `app/services/technical_*`
  - 技术标项目、目录、缺口、review、覆盖率、交付、文档格式、素材/Wiki 和投标机型专属逻辑
- `app/services/tech_assembly.py`
  - 准备目录 JSON、缺口计划、Wiki、素材库导出，并调用 `bid-tech-assembler` 拼装 `S4` 正文
- `app/services/wiki_generation.py`
  - 按项目标类选择技术标/商务标素材库 facade 导入生成的 Wiki 蓝图
- `app/services/peripheral.py`
  - 外围模块的轻量状态承接与 fixture 数据
- `app/core/config.py`
  - 环境变量与本地目录配置

## 下一步

后续不要再按旧单线 route 或旧三条独立拆任务推进。当前以 `/Users/wlb/Agent/bid-project/doc/需求梳理.md`、`/Users/wlb/Agent/bid-project/doc/研发计划.md` 和 `/Users/wlb/Agent/bid-project/code/progress.md` 为准，先跑通商务标端到端。
