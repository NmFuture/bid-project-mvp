---
id: engine-10
scope: AgentEngine / 部署安全
status: done
depends-on: []
---

# engine-10（波次 D1，对应 harness-05）：opencode 端口鉴权与资源限额

## objective

堵住「4096 映射宿主机 + 客户端无鉴权 + 容器内 bash allow + 无资源限额」的内网任意执行面。

## context

- `docs/20260813-AgentEngine多内核引擎改造方案.md` §6 波次 D1
- `docs/plan/tasks/harness-05.md`（现状证据与文件清单以其为准）
- `docs/20260718-安全体检与R01遗留修复-handoff.md` S3（同一问题的安全视角，可合并实施）
- harness-10（auth.json 载体与文档）是配套，可同批做

## path

- `code/docker-compose.yml`（:322-323 端口映射、:294 `OPENCODE_SERVER_PASSWORD`）
- `code/sewpg-bid-backend/app/services/agent_engine/opencode_engine.py`（请求构造处加鉴权头）
- `code/opencode-auth/`（auth.json 挂载）
- `code/docker-compose.5090.yml`（如 5090 需不同取值）

## 现状

- `docker-compose.yml:322-323` 仍 `"${OPENCODE_HOST_PORT:-4096}:4096"` 对宿主发布；客户端请求无鉴权；容器无 `deploy.resources` 限额。

## 改造方案

1. 端口收回内网（仅 compose 网络内可达）或加鉴权。
2. 客户端请求带鉴权头，配置走环境变量。
3. compose 补 `deploy.resources` 限额（默认值本地安全，5090 取值只写 5090 层）。

## verification

- 服务可启动、健康检查通过；无鉴权请求被拒绝的验证记录。
