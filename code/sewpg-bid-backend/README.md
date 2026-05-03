# sewpg-bid-backend

当前正式后端目录。

## 目录

```text
sewpg-bid-backend/
  app/                # 正式 FastAPI 运行时代码
    api/              # 路由层
    core/             # 配置与基础设施
    services/         # 当前服务层与内存态 store
  onlyoffice/         # OnlyOffice Document Server entrypoint
  opencode/           # opencode 镜像、配置与 skill 相关资产
  .localdata/         # 本机联调数据目录
```

## 当前约定

- 前端最终只调这里提供的 FastAPI
- 主链路真实接口与外围承接接口都放在这里
- `onlyoffice/` 和 `opencode/` 只保留当前 compose 与主链路需要的运行资产
- 当前主链路真实阶段：`S0 解析 / S1 模板与目录 / S2 审核目录 / S3 缺口处理 / S4 生成标书 / S5 共创 / S6 导出`
- 项目阶段条只展示 `S1-S6`；`S0` 是全局解析/审核模块
- 旧 `S7/S8/S9/S10` 仅作为历史请求兼容或内部文件名保留，不再作为当前阶段口径
- 外围模块当前已由正式 FastAPI 承接：`materials / audit / settings / export`

## 当前代码分层

- `app/api/routes`
  - 按接口域拆分路由
  - 当前包含：主链路路由 + 外围模块路由
- `app/services/store.py`
  - 主链路状态、解析、目录、正文拼装、覆盖、文档状态
- `app/services/outline_generation.py`
  - 准备 `S1 模板与目录` 的目录 manifest，并由 FastAPI 本地规则引擎或 Skill 生成目录 JSON；`s2_toc_workdir` 是历史内部目录名
- `app/services/tech_assembly.py`
  - 准备目录 JSON、缺口计划、Wiki、素材库导出，并调用 `bid-tech-assembler` 拼装 `S4` 正文
- `app/services/draft_generation.py`
  - 兼容旧 `fill-generation` 服务名，实际转发到 `S4 生成标书` 服务
- `app/services/peripheral.py`
  - 外围模块的轻量状态承接与 fixture 数据
- `app/core/config.py`
  - 环境变量与本地目录配置

## 下一步

后续不要再按这里的旧三条独立拆任务，统一以 `/Users/wlb/Agent/bid-project/doc/14-甲方新增需求待办.md` 为下一阶段待办池。完成或推进一项后，同步更新待办“完成情况”和 `/Users/wlb/Agent/bid-project/code/progress.md`。
