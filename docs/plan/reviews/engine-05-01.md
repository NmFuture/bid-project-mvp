# engine-05 review 01

- 任务：docs/plan/tasks/engine-05.md（B3 会话生命周期回收 + opencode_data 卷清理）
- 产出：commit a281b43（7 文件 +609/-208）
- 复跑：`APP_STORE_BACKEND=memory ... pytest -m "not integration"` → **2337 passed, 0 failed, 30 deselected**（188s）。
  与开发者声称「2351 passed」数字略有出入（推测其统计口径含 deselected 或运行时点不同），但 0 failed 属实，全绿。

## Findings

### P1（blocking）

无。

### P2（blocking）

无。

### P3（non-blocking）

1. **delete 与被遗弃 worker 的竞态（低危，可接受）**
   位置：`opencode_engine.py:629`（idle 超时未停下）、`:507`（提前收割 stop 超时）、`:437`（PollReconnectExhaustedError）。
   这三条错误路径会把异常直接抛出，此时发送 prompt 的 `worker_task` 未 cancel/await 就被遗弃；编排层 finally 随即
   `_recycle_session`，DELETE 与仍在飞的 POST `/session/{id}/message` 并发。影响有限：worker 自身 catch 全部异常
   进 `error_holder`（无未消费异常告警），服务端对 in-flight 请求与 DELETE 的竞态由 opencode 自行处理，且这些路径
   本来就已经是失败终态。worker 遗弃是 B3 之前就有的形态，本 commit 只是在其后追加了 delete。建议后续 B/C 波次
   在引擎层统一「错误出口先收割 worker」的骨架，不阻塞本任务。

2. **json_utils 回收对 OpencodeEngine 的隐性耦合**
   位置：`json_utils.py:183`（finally 调 `self.delete_session_quietly`）。
   该文件 docstring 声称「引擎无关，三引擎复用」，但 `delete_session_quietly` 只有 OpencodeEngine 实现
   （codex_engine/pi_engine 只有 `delete_session`）。当前只有 OpencodeEngine 绑定了 `_repair_json_payload`
   （opencode_engine.py:78），且 codex/pi 的 `create_session` 返回 str（repair 里的 `session.get("id")` 本来就
   不兼容），所以今天不会炸；但后续把 repair 接到 codex/pi 时会以 finally 里的 AttributeError 掩盖业务结果。
   建议后续在 base.Protocol 补 `delete_session_quietly` 或把回收改为 `getattr` 兜底，本波次不动。

3. **技术标共创对话的失败首试会话泄漏（已被兜底策略覆盖）**
   位置：`technical_chat_service.py:131` + `opencode_engine.py:294-296`。
   `keep_session=True` 时 finally 整体跳过回收：若首试 send_text_prompt 抛错（如模型不可用走 fallback），新建
   的会话从未绑定到项目状态、也不会被删，只能等卷清理。属 commit message 明示的「残留由卷清理兜底」范围，
   例外判断本身成立（见下「核查结论」）。

4. **清理脚本 dry-run 掩盖 find 错误**
   位置：`cleanup-opencode-data.sh:66`（`find ... 2>/dev/null | awk`）。
   DATA_DIR 拼错或权限异常时 dry-run 会报「待清理：0 个文件」而非报错（`--apply` 路径无 `2>/dev/null`，会显式
   失败，所以实际删除侧是安全的）。建议 dry-run 去掉 `2>/dev/null` 或对 find 退出码显式报错。非阻塞。

5. **测试覆盖小缺口**
   `tests/test_opencode_engine.py` 新增 13 用例质量良好：delete 路径（URL/404 幂等/5xx 显式抛/quietly 告警）、
   send_text_prompt 默认回收/失败回收/keep_session 跳过、_run_traced_session 成功/失败/取消三终态、
   「回收失败不掩盖业务结果」、决策会话逐 attempt、接力+finalize 全量回收均有断言。
   未直接覆盖：两个 business review（orchestrator.py:1009/1027，同一 try/finally 模式）与 json_utils 修复会话
   的回收（仅经 test_technical_report_contract.py 的 fake 连带更新间接验证）。无 stub 残留、无超范围改动。

## 核查结论（针对 review 要点）

1. **回收误删**：成立，无误删。编排层 7 个 `create_session` 点（orchestrator.py:531/631/677/733/974/1009/1027）
   全部 try/finally 覆盖；`create_session` 本身在 try 外，失败无需回收。`_build_output_trace`（trace.py:13）是纯
   函数、只读 response，不调服务端；留痕在 finally 删会话之前完成，持久化侧（bid_parse_service 落库 trace、
   cancel_parse 读持久化 trace）均不依赖服务端会话存活。跨请求复用会话只有 technical_chat_service
   （`_existing_session_prompt_result` 按项目绑定 sessionId 续跑），两处 `keep_session=True` 判断成立；
   business_document_service 等其余 send_text_prompt 调用方均为一次性（多轮上下文靠 prompt 内 history 文本，
   返回的 sessionId 仅留痕），默认即删正确。
2. **并发竞态**：`raise_if_cancelled` 路径先 cancel+await worker 再抛，delete 在其后，无竞态；
   `cancel_parse` 只 abort 不 delete 的说明成立——delete 由在跑的编排任务 finally 兜底，abort 对已删会话返回
   False 不炸（opencode_engine.py:455），对僵死任务的残留由卷清理兜底。仅上面 P3-1 的遗弃 worker 路径存在
   理论竞态。
3. **失败语义**：`delete_session` 404 幂等、5xx 及其余 4xx 显式 RuntimeError，语义正确；`_recycle_session` /
   `delete_session_quietly` 均 catch-all 只告警，finally 中不会掩盖主异常（有对应用例
   `test_recycle_failure_does_not_mask_business_result`）。
4. **清理脚本**：opencode 镜像为 `node:22-bookworm`（GNU findutils，`-printf`/`-xdev`/`-delete` 可用）；
   DATA_DIR 与 compose 卷挂载点一致（docker-compose.yml:353）；路径无外部输入、RETENTION_DAYS 数字校验、
   默认 dry-run、`-xdev` 不跨挂载，无误删挂载外路径风险。「进行中会话 mtime 持续刷新不误删」在 7 天保守窗口下
   合理；超窗多轮会话被清后有 `TechnicalChatSessionExpiredError` → 前端「会话已失效」降级路径承接。
   compose 未动，与声称一致。

## 结论

**pass**。无 P1/P2 blocking findings；5 条 P3 均为后续波次可消化的改进项，不阻塞合入。
