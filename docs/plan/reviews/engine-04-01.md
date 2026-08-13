---
task: engine-04
commit: da4b3b3
reviewer: review-01
verdict: pass
---

# engine-04 review 01：send_prompt 中途重试与轮询断线恢复（B2）

## 复验结论

- 复跑：worktree 内 `pytest -m "not integration"`，**2285 passed / 0 failed / 30 deselected，185s**（基线 2276+9，与开发者声称一致）。
- `git diff --check` 干净；worktree `git status` 干净；改动 4 文件全部在任务 path 内，无超范围改动。
- 设计约束对齐：harness-03 第 3 条「send_prompt 重发先确认幂等性；opencode 不支持同会话 message 去重则策略从重发收敛」——产出采用「仅确认未送达才重发 + 送达不确定显式报错」的保守策略，与该约束一致。

## Findings

### P1

无。

### P2

无。

### P3（non-blocking）

1. **4xx 确定性错误也被归入 `PromptDeliveryUncertainError`，文案略不准**（`opencode_engine.py:241`）。
   收到 4xx 响应证明请求已送达且被服务端明确拒绝（如 404 session 不存在），此时「送达状态不确定」的文案不成立。类型仍是 RuntimeError 子类、不重发，行为正确，仅报错指引对 4xx 场景有轻微误导。可后续按 `HTTPStatusError` 区分确定性拒绝与送达不确定。
2. **断线计时未覆盖首次失败请求自身的等待**（`opencode_engine.py:400`）。
   `disconnected_started` 在首次 `list_session_messages` 抛错之后才开始计时，首次失败请求的等待（connect timeout 最长 5s）仍计入 idle。idle_timeout 为分钟级，影响可忽略；重连循环内后续失败请求的耗时均已计入。
3. **`PollReconnectExhaustedError` 抛出路径不取消在飞的 worker task**（`opencode_engine.py:329` 抛出点、`:542` 主循环）。
   预算耗尽后主协程直接抛错退出轮询，`send_prompt` 的 worker task 继续跑到自然结束。这是刻意设计（错误文案明示「会话可能仍在服务端运行，由上层决策」），且与既有 `_raise_session_error_if_present` 抛出路径一致；worker 自收异常入 error_holder，不产生未消费异常告警。同 loop `asyncio.run` 桥接下 loop 关闭即回收，无泄漏风险。

## 逐项核对记录

### 1. send_prompt 幂等性边界（声称成立）

- 「连接未建立才重发」的判定覆盖完整：`send_prompt` 每次尝试（含重试）都新建 `httpx.AsyncClient`（`opencode_engine.py:199`），无连接池复用，「池化旧连接写出后才报 ConnectError」的场景在此不存在。
- 已核对 venv 内 httpcore 1.0.9 源码：`_connect` 对 `connect_tcp` 与 `start_tls` 使用同一个 connect 超时（`_async/connection.py:104`），anyio 后端把 TLS 握手的超时/失败分别映射为 `ConnectTimeout`/`ConnectError`（`_backends/anyio.py:55-68`）。两者均发生在 HTTP 请求字节写出之前，归入 pre-delivery 重发安全。
- `ReadTimeout`/`RemoteProtocolError`/5xx/空响应/非 JSON 均不重发；后两者本就不是 httpx 异常，直接抛 RuntimeError 语义不变。
- `PromptDeliveryUncertainError` 上下文足够上层决策：含 session_id、底层错误摘要、「未自动重发、先检查会话状态」的显式指引。
- `ConnectTimeout` 是 `TimeoutException` 子类而非 `ConnectError` 子类，代码并列判断正确。

### 2. 轮询重连对齐（无遗漏路径）

- 主轮询循环 4 处 `_poll_session_messages`（`:545/:604/:629/:646`）全部 `apply_disconnect`；grace 循环（`:707`）加回 `stalled_until`；`_wait_for_early_completion_after_prompt_return`（`:828`）加回 `deadline/last_activity/last_heartbeat`。`:677` 首次 fetch 忽略 disconnected 无影响（worker 已结束，grace 时钟在其后由 `time.monotonic()` 重建）。
- 重连窗口内 0.5s 切片 sleep + `cancel_check`（`:406-412`），取消延迟 ≤0.5s，与 docstring 声称一致；主循环/ finalize 的取消在循环顶兜底。
- 空消息不会误刷新活动时钟：snapshot signature 为 None 时两个分支都保持 `last_signature` 不变，不重置 idle 计时。

### 3. idle 语义回归（双向覆盖，有界）

- 双向测试都在：`test_poll_disconnect_time_does_not_count_toward_idle`（真实时钟，断线 ~2s > idle 1.2s 不误判 stall）与 `test_poll_reconnect_then_stall_still_detected`（断线恢复后假死仍 abort + idle timeout）。
- 「真死多等」有界：每段断线最多加回一个重连窗口（默认 ~23s），预算耗尽即抛 `PollReconnectExhaustedError` 显式断线，不会无限延长。

### 4. `list_session_messages` 吞错语义迁移（无遗漏）

- 生产代码中全部调用点都在 `opencode_engine.py` 内部且已迁移：监管链路走 `_poll_session_messages`，留痕/收尾取证走 `_best_effort_messages`（保留旧吞错语义）。仓内其余引用（orchestrator/flows/其它测试文件）均为测试 patch，无生产调用方依赖旧的吞错返回 []。
- 两个新异常均为 `RuntimeError` 子类；既有调用方（orchestrator 各相位、technical_chat_service、business_document_service 等）全部按 RuntimeError 级处理，零适配声称成立。

### 5. 测试质量

- 9 个新单测覆盖分类表各分支：未送达重发（ConnectError→ConnectTimeout→成功）、预算耗尽、读超时/502 不重发、断连重连续跑、重连耗尽显式断线、断线不计 idle（真实时钟）、重连后假死仍判 stall、分类表参数化断言。`assertRaisesRegex(RuntimeError, "连接未建立.*ses-1.*已重发 2 次")` 等断言精确到预算次数。
- 无 stub 残留；退避用 patch settings 归零而非 patch 全局 `asyncio.sleep`（避免误加速 worker），处理得当；`test_poll_reconnect_budget_exhausted_*` 用 `threading.Event` 释放 worker 并收尾，不留孤儿 task。

## 结论

**pass**。3 条 P3 均为 non-blocking 的文案/边角问题，可入 backlog，不阻断合入。
