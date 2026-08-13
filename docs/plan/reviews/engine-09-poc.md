# engine-09（C3）换内核 PoC 记录：S1 分片链路 × opencode/codex/pi

日期：2026-08-13。环境：本机 macOS，codex CLI 0.147.0、pi 0.73.1、opencode 1.18.2（容器 sewpg_bid_opencode，localhost:4096）。

## 接线方式（本轮落地）

- `parsing._run_technical_shard_session` 改经 `AgentEngineFactory.create(model_config=..., request_slots=_S1_SHARD_REQUEST_SLOTS)` 取引擎，`AGENT_ENGINE=codex|pi` 可切换；默认恒为 `opencode`（factory 默认值不动）。
- 编排走 `AgentOrchestrator.run_tender_parse_shard_with_trace`，该方法重写为**只经协议方法**（create_session / run_session / abort_session / delete_session）驱动引擎；`EarlyCompletionPlan → on_tool_completed` 协议回调适配落在 `base.tool_completed_callback_from_plan`（engine-07 遗留，分片链路 plan 为空，适配器供后续带计划的链路复用）。
- 前置对齐一并完成：
  - engine-03 F5：`OpencodeEngine` 补齐协议形态——`create_session` 返回 str（原 dict）、新增 `run_session`（内部复用 `_send_prompt_with_session_polling`，on_tool_completed 折成最小计划）、`list_messages` 别名；门面旧名（send_prompt / list_session_messages / run_bid_* 等）全部保留。
  - engine-05 P3-2：`json_utils._repair_json_payload` 改走协议方法（create_session/run_session），回收优先 `delete_session_quietly`、缺失回退协议 `delete_session` 且失败只告警——三引擎走 repair 路径均不炸。
- 单测：`tests/test_agent_engine_wiring.py`（18 用例：factory 取引擎/参数转发、plan→回调适配、分片协议路径、opencode run_session、repair 解耦），全部非真实 CLI。

## PoC 样本与方法

同一小样本：6 段落的迷你招标文件 + 真实 `s1parse prepare` 导航索引，跑第一个分片 `selection_supply`（9 行清单），prompt 由生产代码 `parsing._build_technical_shard_prompt` 逐字生成（仅 manifest 绝对路径不同：opencode 在容器卷 `/data/parsed/poc-e09/`，codex/pi 在本机目录；codex/pi 经 PATH 注入 `s1parse` shim 调同一 runner）。每个引擎各建独立 fixture 副本，经 `AGENT_ENGINE` 各跑一次真实分片会话。判据：`reply` 与产物文件（agentic_submissions.json）与 opencode 基线语义等价。

## 结果比对

| | opencode（基线） | codex | pi |
|---|---|---|---|
| 引擎/协议版本 | opencode 1.18.2 HTTP 轮询 | codex CLI 0.147.0 `exec --json` JSONL | pi 0.73.1 stdio RPC |
| 冒烟（echo 探测） | 3.8s 通过 | 27.0s 通过 | 2.9s 通过（修复后，见下） |
| 分片会话 | 69.9s，38 个进度事件 | 136.0s（首轮 208.8s），20 个事件 | 52.8s/62.1s（两跑），2857/4299 个事件（text_delta 逐片推送，量级天然大于快照式轮询） |
| 提交产物 | 9/9 行（found 1 / partial 3 / missing 5） | 9/9 行；行 6 found→partial、行 7 partial→missing，余全同 | 9/9 行，状态分布与基线**完全一致**（两跑一致） |
| reply | submit stdout 小 JSON（bid-tech-agentic-submit-v1 / saved） | 同左（首轮为空——agent_message 键漂移，修复后复跑正常） | 同左 |
| 使用模型 | deepseek-v4-flash（容器 env） | CLI 默认（config.toml，本机为 gpt-5.x） | deepseek-v4-flash（PI_PROVIDER_ID/PI_MODEL_ID 指定） |
| 进程资源 | 容器常驻服务 ~600–626MiB（含模型无关开销） | 单 exec 进程 RSS 85–128MiB，会话结束即回收 | 单 node 常驻 RPC 进程（运行期 1 个，终态必回收；精确 RSS 未采到） |

**等价性结论**：三引擎的产物文件均 9/9 行覆盖、状态合法、结论语义一致（codex 两行判定偏保守，属模型差异而非协议差异——codex 用的是不同模型）；reply 均为 submit stdout 的同构小 JSON。判据通过。

## 命令拼法 / 事件 schema 校准点（实测漂移，已修复）

1. **codex `exec resume` 子命令**（engine-07 遗留）：0.147.0 已移除 `--resume <id>` 选项（报 `unexpected argument`），改为子命令 `codex exec resume <id> [prompt]`；resume 无 `--sandbox` 选项，用 `-c sandbox_mode=` 等价注入。双轮真实会话复验通过（turn2 正确回答基于 turn1 的上下文）。
2. **codex assistant 文本 item 类型改名 `agent_message`**（旧快照 `assistant_message`）：不改会导致 reply_text 永远为空（首轮分片即踩中）。两键都认。
3. **codex stdout 行缓冲**：`create_subprocess_exec` 默认 64KiB，工具完整 `aggregated_output` 单行可超限（readline 抛 ValueError）；加 `limit=8MiB`，与 pi（engine-08 P2-2）对齐。
4. **pi `-n title` 非法选项**（0.73.1 真实 CLI，rpc.md 快照未覆盖）：进程直接退出、握手失败；`--no-session` 下 title 本无持久化意义，已移除（engine-08 P3-3「空 title 退出」同源，随之关闭）。
5. **pi 扩展发现**：用户环境一个坏扩展（~/.vibe-island/pi-extension 缺依赖）会在 RPC 启动时杀掉进程；headless 场景默认加 `--no-extensions`（`PI_NO_EXTENSIONS=0` 可关）。

## provider 切换 / 降级实录

- pi 默认 provider 解析到 gpt-5.4@openai，本机网络请求超时（`Request timed out.`）；`PI_PROVIDER_ID=deepseek PI_MODEL_ID=deepseek-v4-flash` 切换后立即正常——`--provider/--model` 启动参数链路有效。
- codex provider/model 会话级固定（config.toml + 登录态），按请求传入记 warning 忽略（设计内降级，§3 注）。
- opencode 经容器 env 固定 deepseek-v4-flash；按请求 tools/provider 在轮询链路不接（warning 忽略）。

## 超长 / 大输出表现

- 分片会话 53–209s，三引擎 idle/心跳监管正常（有事件即刷新 idle 时钟）；分钟级以上超长会话未压测。
- 大输出收割（>64KiB 的 finalize stdout）未真实压测；codex/pi 的行缓冲上限已预防性对齐 8MiB。
- pi 单分片流式事件达 2857–4299 个（text_delta 级），引擎折叠与进度回执无压力；`session.events` 缓冲只增不减（engine-08 P3-2）在长会话下是内存增长点，仍登记在案。

## 未覆盖 / 遗留

- 多分片并发真实跑（并发预算共享已由单测覆盖，真实并行冒烟需 dev/5090）。
- 带 EarlyCompletionPlan 的链路（三条 finalize）仍只由 OpencodeEngine 驱动；`tool_completed_callback_from_plan` 已备妥但无生产调用方（分片链路 plan 为空）。
- pi `tools` 按请求开关不支持（显式 ValueError）；带 tools 的链路不能切 pi。
- codex/pi 的 trace/消息在引擎进程内存，后端重启即失（codex resume 依赖 CLI 侧 thread 持久化，已验证可用）。
- pi RPC 进程 stderr 被 DEVNULL，握手失败时诊断信息少（本次靠手工复现定位到扩展问题）。

## AGENT_ENGINE 进生产建议

- **接线本身可进生产**：默认 `opencode` 不变，全量测试 2387 passed 0 failed（基线 2368 + 新增 19），opencode 路径行为零变化（表征测试全绿）。
- **codex/pi 定位为实验性引擎**：dev 环境可经 `AGENT_ENGINE` 启用观察；5090 生产切换（只写 `docker-compose.5090.yml`）前需补：多分片并发真实冒烟、大输出/超长会话压测、pi 会话进程长期孤儿观察。
- 候选优先级：**pi > codex**——pi 与 opencode 同模型下产物逐行一致、耗时最低（53s vs 70s），RPC 常驻进程模型最接近 opencode serve；codex 单会话一个 exec 进程、冷启动慢（136–209s）且事件键随 CLI 版本漂移，适合作为备用内核。
