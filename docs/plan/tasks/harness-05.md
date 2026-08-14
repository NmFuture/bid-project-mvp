---
id: harness-05
scope: Harness / 部署安全
status: done
depends-on: []
---

# harness-05：opencode 端口鉴权与资源限额（短板 5）

> 已由 engine-10（波次 D1）接管，以 engine-* 为准；本文件保留现状证据。

## objective

堵住「4096 映射宿主机 + 客户端无鉴权 + 容器内 bash allow + 无资源限额」的内网任意执行面。

## context

- `docs/anbc_doc/架构总览/05-Harness基建.md` §4、§5 短板 5
- `docs/20260718-安全体检与R01遗留修复-handoff.md` S3（同一问题的安全视角，可合并实施）
- harness-10（auth.json 载体与文档）是本任务的前置配套，可同批做
- 总 plan：`docs/plan/analysis/20260812-系统性重构.md`

## path

- `code/docker-compose.yml`（:322-323 端口映射、:294 `OPENCODE_SERVER_PASSWORD`）
- `code/sewpg-bid-backend/app/services/opencode_client.py`（客户端请求构造处，加鉴权头）
- `code/opencode-auth/`（auth.json 挂载，配 harness-10）
- `code/docker-compose.5090.yml`（如 5090 需要不同取值）

## 现状（2026-08-12 复核证据）

- `docker-compose.yml:322-323` 仍 `"${OPENCODE_HOST_PORT:-4096}:4096"` 对宿主发布。
- compose 有 `OPENCODE_SERVER_PASSWORD`（:294）但客户端全文无 `Authorization`/auth 字样，从不发送。
- 全 compose 无 `deploy.resources` 资源限制。

## 改造方案

1. **首选**：删除宿主机端口映射，opencode 只走 compose 内部网络（fastapi/worker 同网络可达）；本地调试需要时文档化 `docker compose port` 或临时 override 的做法。
2. 同时启用服务端密码：`OPENCODE_SERVER_PASSWORD` 强制非空（生产 fail-fast），`opencode_client` 请求统一带鉴权头。
3. 给 opencode 服务加 `deploy.resources` 限额（取值按配置分层规则：compose 主层给保守默认，5090 层覆盖）。

## 连带注意

- 确认没有任何宿主机/外部消费方直连 4096（前端不直连，web 反代无 4096 路由——动手前再核一遍 nginx 配置）。
- 与 harness-01 客户端拆分有文件重叠，若波次 2 已启动需协调合入顺序。

## verification

- compose up 后：宿主机 `curl localhost:4096` 不通（或 401）；fastapi/worker 链路 AI 调用正常；健康检查通过。
