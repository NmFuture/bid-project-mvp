---
id: engine-02
scope: AgentEngine / early completion 泛化与业务编排上移
status: done
depends-on: [engine-01]
---

# engine-02（波次 A1）：on_tool_completed 回调机制 + 三套 finalize 收敛 + 业务编排层上移

## objective

消灭「业务命令字符串写死在通用轮询循环里」：early completion 从命令字符串特判改为「事件 + 判定回调」，三套 `_wait_for_*_finalize` 收敛为一套通用逻辑，业务编排（14 个 `run_bid_*`、`_extract_*_json`、stall 报错）上移到 `AgentOrchestrator`。完成后：新增一类 agent 任务 = 注册 `early_command + 判定函数`，不再改引擎。

## context

- `docs/20260813-AgentEngine多内核引擎改造方案.md` §1 诊断（三个实锤问题）、§3 on_tool_completed 设计、§4.1、§6 波次 A1、§7「业务编排层放哪」
- `docs/plan/tasks/harness-01.md`（本任务完成其「early_tool_command 注册机制」部分）
- engine-01 的产出（`agent_engine/` 包结构）

## path

- `code/sewpg-bid-backend/app/services/agent_engine/opencode_engine.py`（删业务 if、finalize 收敛）
- 新建 `code/sewpg-bid-backend/app/services/agent_engine/orchestrator.py`（业务编排层）
- 业务命令注册方：`parsing.py`、`outline_generation.py`、`technical_fact_curator.py`、`business_*` 等
- 相关测试

## 现状（代码证据，行号基于 engine-01 前的 opencode_client.py）

- 通用轮询循环 `_send_prompt_with_session_polling` 内写死业务分支：`:1179-1192` 对 `s1parse-finalize` / `btplnav-finalize` / `s2outline-finalize` 的 if；`:1217-1221` factcurate「不提前返回」特判；`:1486`/`:1499`/`:2072-2074` 按命令名分发 stalled trace 与校验。
- 三套近乎重复的 finalize 等待：`_wait_for_s1_finalize_after_prompt_return:1528`、`_wait_for_template_finalize_after_prompt_return:1627`、`_wait_for_s2_outline_finalize_after_prompt_return:1727`，逻辑同构、细节漂移。
- 业务判定/报错长在客户端：`_s1_finalize_output_is_terminal:2079`、`_btplnav_finalize_output_is_terminal:2091`、`_s2_outline_finalize_output_is_terminal:2103`；`_raise_s1/template/s2_outline_*_stalled:2356~2406`；14 个 `_extract_*_json:863~1030`；14 个 `run_bid_*`/`generate_*_with_trace`（`:283~`:820）。

## 改造方案

1. **on_tool_completed 机制**：`run_session` 的 `early_tool_command: str` 参数替换为 `on_tool_completed: Callable[[ToolCompletedEvent], bool]`（返回 True = 提前收割）。引擎只做通用能力：检测「某个 bash 工具完成」→ 上报 `ToolCompletedEvent{command, stdout}`（`_find_completed_bash_tool_output` 改为构造事件）。删除轮询循环里的全部业务 `if`。
2. **finalize 收敛**：三套 `_wait_for_*_finalize` 合成一套通用「等命令完成」逻辑，差异点（terminal 判定、stall trace 文案、stalled 异常）以回调/参数注入。
3. **业务编排层**：新建 `orchestrator.py`，迁入 14 个 `run_bid_*` / `generate_*_with_trace`、14 个 `_extract_*_json`、terminal 判定与 stall 报错。每类任务以注册表条目声明：`{命令名: {提前完成判定, stall 策略, 结果校验}}`，业务模块在自己代码里注册（或集中在 orchestrator 注册表，实施时按耦合度取舍，但引擎侧不得出现业务命令字符串）。
4. **对外兼容**：`run_bid_*` 方法名与签名保持不动——`OpencodeEngine`（或薄门面）保留同名委托方法，16 处调用方本任务不改。
5. **行为零变化底线**：先补表征测试锁定三条 finalize 链路的提前完成/超时/stall 行为，再动刀。

## verification

- 表征测试 + 与 CI 对齐的后端测试全绿（命令同 engine-01），失败集合与基线比对不得新增。
- grep 验证：`agent_engine/opencode_engine.py` 中不再出现 `s1parse-finalize` / `btplnav-finalize` / `s2outline-finalize` 字面量。
- 长任务回归（S1 解析、S2 目录、事实表三路）需真实环境，本地跑不通则在交付说明中标注，留待 dev 环境冒烟。
- 提交前 `git diff --check`。
