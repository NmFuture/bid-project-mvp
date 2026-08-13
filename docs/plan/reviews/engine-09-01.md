# engine-09 review 01（2026-08-14）

- 任务：`docs/plan/tasks/engine-09.md`（C3：Codex/Pi 换内核 PoC，S1 分片链路）
- 产出：commit `cd0d0f7`（17 文件，+853/-136）
- 判据：`docs/20260813-AgentEngine多内核引擎改造方案.md` §3 / §6 C3 / §8 PoC 判据；根 AGENTS.md
- 复跑：`APP_STORE_BACKEND=memory DATABASE_URL=... python -m pytest -m "not integration"` → **2387 passed / 0 failed**（220s，与 commit message 声称一致；基线 2368 + 18 wiring + 1 codex `agent_message` 新增）

## 核对记录（通过项）

1. **默认路径零行为变化（核心）**
   - `create_session` dict→str：app/ 全量 grep 核对，所有调用点（orchestrator 7 处、`send_text_prompt`、`json_utils._repair_json_payload`）均已适配为 str，无遗漏；缺 id 时显式 RuntimeError（原先是带空 id 走到 send_prompt 才炸，更隐晦）。
   - `parsing._run_technical_shard_session` 经 `AgentEngineFactory.create(model_config=..., request_slots=_S1_SHARD_REQUEST_SLOTS)`：缺省 `AGENT_ENGINE` 时工厂返回 `OpencodeEngine`，两个参数透传与原直造等价；`AgentOrchestrator(engine)` 与引擎内建 `self._orchestrator` 同类同参。
   - 分片 trace 形状不变：`run_session` 内部仍走 `_send_prompt_with_session_polling`（同 stream_callback/cancel_check）+ `_build_output_trace` 同一函数；`session_ready_callback` 的 provider/model 经 getattr 取值，opencode 下与原先 `engine.provider_id/model_id` 相同。
   - 门面旧名全部保留：`send_prompt` / `list_session_messages` / `delete_session_quietly` / `run_bid_*` / `run_tender_parse_shard_with_trace`（opencode_engine.py:203/457/570/409-443）。
2. **协议对齐质量**
   - `tool_completed_callback_from_plan`（base.py:80-103）：判 False 不改写 stdout、判 True 以 `plan.harvest_payload` 回填（含 produce_payload 终态校验产物）、工厂只取一次——收割判定与产物语义保持，5 个单测锁定。
   - opencode `run_session` 的 on_tool_completed 最小计划折法正确：`stop_on_early_complete=True` + 无 produce_payload（harvest 落回 event.stdout，回调改写口径与 codex/pi 一致）；info.error 显式抛错与协议引擎「失败即抛」同口径；3 个单测锁定。
   - `json_utils` repair 兜底顺序正确：协议方法驱动（create_session/run_session），回收优先门面旧名 `delete_session_quietly`、缺失回退协议 `delete_session`、失败只告警不掩盖业务结果；orchestrator `_parse_with_repair` 优先引擎绑定、缺失时回退 `json_utils._repair_json_payload(engine, ...)`，两条路径汇聚同一函数；3 个单测锁定。
3. **codex 校准有单测锁定**：`exec resume <id>` 子命令拼法 + `--sandbox`→`-c sandbox_mode=` 注入（test_codex_engine.py:248-253）、`agent_message` 双键兼容（新增 test_agent_message_item_type_alias_maps_to_reply）。
4. **PoC 文档覆盖 §8 判据完整**：事件协议版本（三引擎版本表）、等价性比对（9/9 行、状态分布、reply 同构 JSON、codex 两行偏保守归因模型差异）、资源占用（opencode/codex RSS，pi 未采到已如实标注）、超长/大输出表现与未压测项、provider 切换降级实录、进生产建议（接线可进生产、codex/pi 实验性、pi > codex 优先级）。「未覆盖/遗留」节如实登记，无夸大。
5. **测试质量**：18 例新 wiring 覆盖 factory 切换/参数转发/未知引擎拒绝、plan→回调全分支、分片协议路径（成功/取消/失败均回收会话）、run_session 三态、repair 解耦三态；既有测试适配只改绑定形态（`{"id":...}`→str、`send_prompt`→`run_session` mock），断言语义未改；无 stub 残留；改动范围限定任务声明的 17 文件，backlog 勾选与事实一致（F5/P3-2/P3-3/codex/pi 真实验证均已闭环）。

## Findings

### P2（non-blocking）

- **P2-1：pi 两处校准与 codex 行缓冲上限无单测锁定。** ~~codex 的 resume 拼法与 `agent_message` 键已有测试，但：pi 的 `-n title` 移除与默认 `--no-extensions`（`pi_engine.py:170-181`）在 `test_pi_engine.py:160-169` 只断言 `argv[:3]` 与 provider/model，不锁定新 argv 形态（也不锁 `PI_NO_EXTENSIONS=0` 的关闭分支）；codex 的 `limit=8MiB`（`codex_engine.py:104,187`）无任何断言。~~ **已处理（94daf29，复验通过）**：pi argv 改全量精确断言（含 `--no-extensions` 默认在、`assertNotIn("-n")`），新增 `PI_NO_EXTENSIONS=0` 关闭分支用例；codex 新增 `create_subprocess_exec` 的 `limit` 传参断言（harness 记录 kwargs，断言实测值 == 常量且常量 ≥ 8MiB，删掉 `limit=` 即红，非自证式）。

### P3（non-blocking）

- **P3-1：PoC 文档测试计数笔误。** ~~`docs/plan/reviews/engine-09-poc.md`「进生产建议」写「2386 passed（基线 2368 + 新增 18）」，commit message 与本地复跑均为 **2387**。~~ **已处理（94daf29）**：文档改为「2387 passed（基线 2368 + 新增 19）」，与实测一致。
- **P3-2：默认路径错误语义有一处有意的行为变化，记录备查。** 分片会话 opencode 路径现在 `info.error` 即抛 RuntimeError（`opencode_engine.py:373-375`），接线前是把错误文本留在 trace 里返回「succeeded」、靠 silent-shard 检测兜底。新行为汇入 `parsing.py:6520` 既有 failed→重试路径，且更符合根 AGENTS.md「失败要显式暴露」，判为改进而非回归；边缘情形：已 submit 成功后才 info.error 的分片会被判 failed 重跑（重提交幂等，影响可忽略）。
- **P3-3：run_session 每次结束多一次 `_best_effort_messages` GET**（`opencode_engine.py:376-378`），分片与 repair 路径都会多打一次 opencode HTTP；best-effort 吞错、开销可忽略，仅登记。
- **P3-4：适配器收割顺序与 opencode 轮询不一致（当前无触发方）。** `tool_completed_callback_from_plan` 在回调内即 harvest（base.py:97-101），而 opencode 轮询 in-loop 是先停会话再 `harvest_payload`（opencode_engine.py:741-750）；带 produce_payload 的 s2 链路若未来切协议引擎，「停→校验」顺序会反转成「校验→停」。docstring 已声明相位不映射，分片链路 plan 为空、无生产调用方，登记为未来接线时的检查点。
- **P3-5：`_run_protocol_session(early_tool_command=...)` 暂无传非空值的调用方**（orchestrator.py:1010），是为后续带计划链路预留的参数，plan→回调端到端（经 `_run_protocol_session`）无集成用例。非 stub，PoC 文档已如实登记「适配器已备妥但无生产调用方」。

## 结论

**pass**。默认路径（AGENT_ENGINE 缺省 = opencode）分片链路逐步核对等价，唯一行为差异（P3-2）是有意的显式失败改进；协议对齐语义保持且有测试锁定；codex/pi 真实 CLI 校准与 PoC 记录完整覆盖 §8 判据；全量复跑 2387 passed / 0 failed 与声称一致。

## 复验（94daf29，2026-08-14）

- 改动为纯测试 + 文档笔误（3 文件，+33/-8），与 P2-1/P3-1 的处理建议一一对应，无超范围改动。
- 断言有效性核对：pi argv 精确全量等值断言 + `assertNotIn("-n")`（引擎改回旧拼法即红）；opt-in 用例经 `patch.dict` 在构造期注入 `PI_NO_EXTENSIONS=0`，`_engine()` 不传 `disable_extensions`，env 分支被真实走到；codex limit 断言取 harness 记录的实测 kwargs，删掉引擎侧 `limit=` 即 None != 常量而红——均非自证式。
- 抽查复跑 `test_pi_engine.py`（26）+ `test_codex_engine.py`（29）+ `test_agent_engine_wiring.py`（18）：**73 passed / 0 failed**；新增 2 例与「2389 = 2387 + 2」的声称一致。
- P2-1、P3-1 均已在上方标注已处理；其余 P3（P3-2~P3-5）为登记项，无需处理。

**最终结论：pass**，无未关闭 blocking/P2 项。
