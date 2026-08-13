# engine-02 review 01（A1：on_tool_completed 回调 + 三套 finalize 收敛 + 业务编排上移）

- 审查对象：`task/engine-02` 分支 commit `0cc66c2`（另有 docs 状态 commit `58c5cac`）
- 审查基准：`docs/plan/tasks/engine-02.md`、`docs/20260813-AgentEngine多内核引擎改造方案.md`（§1 诊断、§3 on_tool_completed 设计、§4.1、§6 A1、§7）、`docs/plan/tasks/harness-01.md`、根 `AGENTS.md`
- 审查方式：`git show 0cc66c2` 全量审读 + 与 `0cc66c2^` 旧实现逐点对照（轮询循环、三套 `_wait_for_*_finalize`、terminal 判定、stall 报错）+ 全仓 grep + 与 CI 对齐环境复跑全量测试

## 验证记录（reviewer 复跑）

- 全量 `-m "not integration"`（命令同任务文件/CI）：**2274 passed, 30 deselected, 0 failed**（5m47s）。失败集合为 0，「相对基线不得新增失败」成立。
- +9 口径核对：`test_opencode_engine.py` diff 无任何 `def test` 增删（仅机械适配新内部 API），新文件 `test_agent_engine_finalize_chains.py` 恰好 9 个用例，与开发者「基线 2265 → 2274（+9）」自洽（注：engine-01 review 复跑数为 2167+107 subtests，差异是 subtests 计入口径，见 engine-01-01 F1，非本任务问题）。
- grep 验证：`agent_engine/opencode_engine.py` 中 `s1parse-finalize` / `btplnav-finalize` / `s2outline-finalize` / `factcurate` / `s4gap` / `wikibuild` / `businessassemble` / `businessformat` / `businessgap` / `businesstablefill` / `business-outline` / `s2outline-decision-batch` 全部零命中（含注释）。`TASK_SPECS` 注册表在编排层 `orchestrator.py:298-340`。
- 改动范围恰为任务声明的 6 个文件（4 个 `agent_engine/` + 2 个测试），无超范围改动；`git diff --check` 通过。
- 生产代码无 stub/mock/fake/TODO 残留；旧私有方法（`_find_completed_bash_tool_output` / `_wait_for_*_finalize` / `_raise_*_stalled` / `_stop_s2_outline_session_after_finalize` 等）在 `0cc66c2^` 时就无 engine 外的生产调用方，删除安全；`early_tool_wait_file` 形参在旧实现中本就不被使用，删除无影响。

## 行为零变化逐点核对（结论：成立，除 F1 登记的漂移）

对照旧实现（`0cc66c2^` 的 `opencode_engine.py`）逐点复核：

- **in-loop 收割顺序**：旧「检测终态 stdout → 停会话（带 `finished` 等待）→ 跑 validator → 收割」与新 `_s2_terminal_validator_plan`（`orchestrator.py:449-491`）+ 引擎 `_send_prompt_with_session_polling:447-470` 的顺序完全一致；非终态候选路径同为「先跑 validator 成功后停会话再收割」。
- **stall 文案与异常类型**：`_raise_command_stalled`（`orchestrator.py:235-257`）与旧三个 `_raise_*_stalled` 的消息格式（`opencode incomplete/stalled: sessionId=..., lastTool=..., lastStatus=..., lastInput=...`）、`RuntimeError` 类型、`opencode_trace` 挂载、`command_label`（`s1parse finalize` / `btplnav finalize` / `s2outline finalize`）逐字一致；trace 构建复用引擎 `_build_tool_stalled_trace`（新旧一致）。
- **trace 文案 / completionSource / elapsedSeconds 有无**：in-loop 通用收割（`{cmd} 已完成，后端直接读取脚本产物…`，无 elapsed）、s1 即时收割（中文文案，无 elapsed）、s1 宽限期收割（中文文案，带 elapsed）、post-return 收割（s1 英文 / btplnav 中文 / s2 英文文案，带 elapsed）、s2-validator 的 `s2outline-terminal-validator` 两条文案（「已停止会话并通过终态校验」/「对当前 staging 产物完成确定性 finalize 校验」）、assistant-stop 路径 in-loop 不带 elapsed 而 post-return 带 elapsed——逐项与旧实现一致（`EarlyCompletionPlan` 各字段注入值逐一核对）。
- **factcurate 不提前返回**：`TASK_SPECS["factcurate"].early_return=False`（`orchestrator.py:337`），回调恒返回 False，只保留 idle 监管，与旧 `early_tool_command != "factcurate"` 特判等价；`business-outline` 永不收割特判同样保留（`orchestrator.py:339`）。
- **停会话报错文案**：`_stop_session_after_early_completion`（`opencode_engine.py:309-324`）以 `stop_label="s2outline finalize"` 复现旧「s2outline finalize 后 Opencode worker 未停止（…）」两条文案；`s2outline-decision-batch` 沿用同标签，与旧共用 `_stop_s2_outline_session_after_finalize` 的行为一致。
- **去重相位**：s2 候选去重集合按相位各建一套（in-loop 一套、prompt 返回后一套），与旧实现两个 `validated_finalize_attempts` 集合的作用域一致（引擎 `tool_completed_factory` 每相位各取一个回调，`opencode_engine.py:344-348, 520-524, 647-649`）。
- **命令匹配 / terminal 判定 / manifest 合成兜底**：`_matches_completed_command`、三个 `_*_output_is_terminal`、`_synthesize_tool_response_from_manifest` 逐字迁移到编排层，逻辑零差异。

## Findings

### F1（P3，non-blocking）s2outline 多候选场景 validator 执行次数漂移（开发者自报，复核确认）

- 设计文档位置：无直接提及——§4.1 只要求「三套 finalize 收敛，差异点回调注入」，未约束候选去重的迭代粒度；属「实现合理但设计文档未提及」。
- 代码位置：新 `orchestrator.py:449-471`（`_s2_terminal_validator_plan.make_callback`）；旧 `0cc66c2^:opencode_engine.py` `_latest_completed_s2_outline_finalize_command`（旧文件 `:2191-2219`）与 in-loop `:1284-1308`、post-return `:1821-1841`。
- 现象：旧实现每轮轮询只取**最新一条**非终态 finalize 候选跑 validator；新回调在一轮内按新到旧遍历全部完成事件，最新候选校验失败后会继续对**较旧候选**各跑一次 validator（每候选仍至多一次，去重集合生效）。
- 评估：**可接受**。validator 是对当前 staging 产物的确定性校验，产物与具体候选无关，多跑只是冗余执行，不会错收（任一候选触发成功，收割的都是同一份 validator 产物）；终态 stdout 路径与 assistant-stop 路径完全不受影响。建议后续在该回调处补一行注释说明遍历语义，或补一条多候选用例锁定（见 F3）。

### F2（P3，non-blocking）门面委托方法丢失显式签名

- 设计文档位置：§7「`run_bid_*` 方法名保持不动」；任务文件 `docs/plan/tasks/engine-02.md:38`「方法名与签名保持不动」。
- 代码位置：`opencode_engine.py:222-277`（14 个委托为 `*args, **kwargs`；`generate_outline`/`generate_draft_sections` 保留了显式签名，口径不一）。
- 现象：运行期调用完全兼容（17 处调用方未改即证），但 `inspect.signature`/IDE 层面的参数信息丢失，误传 kwarg 要等到 orchestrator 层才抛 `TypeError`。
- 影响：不改对外行为；建议后续波次把显式签名补齐（纯声明改动），或在任务收尾时确认接受现状。

### F3（P3，non-blocking）表征测试覆盖缺口（两相位/路径无直接锁定）

- 设计文档位置：任务文件 `engine-02.md:39`「先补表征测试锁定三条 finalize 链路的提前完成/超时/stall 行为」。
- 代码位置：`tests/test_agent_engine_finalize_chains.py`（9 用例）。
- 现象：三态覆盖整体达标——s1 覆盖 in-loop 提前完成、prompt 返回后等待、stall；btplnav 覆盖 in-loop 提前完成、stall；s2 覆盖停会话收割、terminal validator、stall；factcurate 不提前返回有用例且断言 `opencodeOutput` 无 `earlyCompletion`。缺口：(a) btplnav 的 prompt 返回后等待相位无直接用例（该路径收敛后与 s1 共用 `_wait_for_early_completion_after_prompt_return`，s1 用例间接覆盖）；(b) s2 多候选去重路径（F1 漂移点）无用例。
- 影响：收敛后的共用实现已有公开面锁定，风险低；建议把 (b) 补成用例以固定 F1 的可接受语义。
- 质量确认：9 个用例全部经公开业务方法（`generate_tender_parse_with_trace` / `extract_business_templates_with_trace` / `generate_outline_with_trace` / `run_bid_tech_fact_curator_with_trace`）驱动，只 mock 最底层 HTTP 原语（`create_session`/`send_prompt`/`list_session_messages`/`abort_session`）；断言锁定 `completionSource`、`failureReason` 中的命令标签、`trace.status/lastTool/lastToolStatus` 等可观测行为，符合表征测试定位。

### F4（P3，non-blocking）graft 模块卡片仍记录旧结构（engine-01 遗留）

- 设计文档位置：`docs/plan/tasks/harness-01.md:48`「拆分后模块卡片与 _data 的 loc/调用链要同步」。
- 代码位置：`code/sewpg-bid-backend/graft/app/services/opencode_client.md`（仍记录旧 2817 行结构、`early_tool_wait_file` 与已删除的三个 `_wait_for_*_finalize`/`_raise_*_stalled` 等，行号基于改名前文件）。
- 说明：engine-01 改名后已过时，非本任务引入；engine-02 的删除进一步拉大偏差。留待索引/文档刷新波次处理（同 engine-01-01 F4 口径），登记备查。

## 审查要点逐项结论

1. **行为零变化**：通过（除 F1 已评估的有限漂移）。三条 finalize 链路的停会话/校验/收割顺序、stall 文案与异常类型、factcurate 特判、trace 文案与 elapsed 语义逐点对齐（明细见上节）。
2. **表征测试质量**：通过。走公开方法、mock 面最小、三态覆盖齐、断言锁定可观测 trace label；缺口见 F3，非阻塞。
3. **引擎侧无业务语义**：通过。业务字面量 grep 零命中；`TASK_SPECS`/`AgentTaskSpec`/terminal 判定/stall 报错全部在编排层；引擎只做「bash 工具完成」事件上报（`base.py:99-128` `iter_completed_bash_tool_events`）与通用监管，符合 §3/§4.1 contract。
4. **对外兼容**：通过（签名细化见 F2）。`run_bid_*` 等方法名不变、调用方零改动；无 stub/mock/fake 残留；改动范围恰为任务声明的 6 个文件。
5. **复跑测试**：通过。2274 passed / 0 failed，失败集合相对基线无新增（基线绿，现全绿）。

## 结论

**pass**。四条 findings 均为 P3 non-blocking：F1 为已自报且经复核确认的有限漂移（冗余 validator 调用，无错收风险），F2/F3/F4 为实现合理但设计文档未提及或历史遗留的登记项。长任务三路真实环境回归按任务文件 verification 留待 dev 环境冒烟（交付说明已标注）。
