# sewpg-bid-backend

当前正式后端目录。

## 目录

```text
sewpg-bid-backend/
  app/                # 正式 FastAPI 运行时代码
    api/              # 路由层
    core/             # 配置与基础设施
    services/         # 当前服务层与内存态 store
  onlyoffice/         # OnlyOffice 接入参考与独立验证资产
  opencode/           # opencode 接入参考与 skill 相关资产
  .localdata/         # 本机联调数据目录
```

## 当前约定

- 前端最终只调这里提供的 FastAPI
- 主链路真实接口与外围承接接口都放在这里
- `onlyoffice/` 和 `opencode/` 目前先保留为后端侧参考资产
- 当前主链路真实阶段：`S0 / S1 / S2 / S3 / S7 / S9 / S10`
- 当前 mock 阶段：`S4 / S5 / S6 / S8`
- 外围模块当前已由正式 FastAPI 承接：`materials / audit / settings / export`

## 当前代码分层

- `app/api/routes`
  - 按接口域拆分路由
  - 当前包含：主链路路由 + 外围模块路由
- `app/services/store.py`
  - 主链路状态、解析、目录、初稿、覆盖、文档状态
- `app/services/peripheral.py`
  - 外围模块的轻量状态承接与 fixture 数据
- `app/core/config.py`
  - 环境变量与本地目录配置

## 下一步

1. 把当前本机运行方式进一步收敛到完整 `docker compose`
2. 继续把外围模块的 fixture 语义替换成真实业务持久化
3. 逐步拆分 `store.py`，把主链路状态与基础设施继续解耦
