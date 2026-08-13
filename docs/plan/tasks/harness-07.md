---
id: harness-07
scope: Harness / 配置治理
status: ready
depends-on: []
---

# harness-07：超时配置统一（短板 7）

## objective

消除 `OPENCODE_TIMEOUT_SEC`（1800s）与系统设置 timeoutMs（30s）双轨并存、靠 `max()` 临时缝合的状态，建立单一超时事实源。

## context

- `docs/anbc_doc/架构总览/05-Harness基建.md` §5 短板 7
- 总 plan：`docs/plan/analysis/20260812-系统性重构.md`

## path

- `code/sewpg-bid-backend/app/core/config.py`（:244 `OPENCODE_TIMEOUT_SEC` 默认 1800）
- `code/sewpg-bid-backend/app/services/system_settings.py`（:145/:223/:324 timeoutMs 默认 30000）
- `code/sewpg-bid-backend/app/services/opencode_client.py`（:57-58 与 :1104-1107 的缝合逻辑）

## 现状（2026-08-12 复核证据）

- 两套超时并存：环境变量 1800s vs 系统设置页 timeoutMs 默认 30s。
- 实际生效值靠 `:57-58`（`raw_timeout_ms or opencode_timeout_sec*1000`）和 `:1104-1107`（`max(configured_read, idle_timeout + 60.0)`）缝合，语义不直观，调超时的人无法预期结果。

## 改造方案

1. 明确一个事实源：建议系统设置页 timeoutMs 为唯一入口（用户可改），`OPENCODE_TIMEOUT_SEC` 只作未配置时的回退默认；或反之——实施时二选一并写进配置注释。
2. read 超时、idle 超时、总超时三个概念在代码里命名分离、各自有注释；`max(configured_read, idle+60)` 这类隐式缝合改为显式推导并注释公式。
3. 系统设置页/健康检查展示「当前生效超时」，避免配置与运行态不一致（呼应 20260718 handoff B10-05 的口径）。

## verification

- 后端测试覆盖超时常量推导；设置页改 timeoutMs 后实际请求超时随之变化（可用短超时 + 慢 mock 验证）。
