# Backlog

verify 产出的 non-blocking findings 登记处（按任务追加）。

## engine-01（review 01，2026-08-13，结论 pass）

- [ ] F1: commit message 测试口径（2265 passed）与复跑（2167 passed + 30 deselected）不一致，后续 commit 统一用复跑口径
- [ ] F2: A0 阶段 `OpencodeEngine` 尚不满足 `AgentEngine` 协议（`create_session` 返回 dict、缺 `run_session`/`list_messages`/`delete_session`），`factory.create() -> AgentEngine` 为名义标注；对齐排期 engine-02/03
- [ ] F3: 调用方口径 17 个 service 文件 + `scripts/technical_wiki_preview.py`（engine-01 任务清单原文写 16 处，遗漏 scripts 一处）
- [ ] F4: 遗留旧名引用：`graft/` 索引、架构总览其它文档（00/04/05、_data/business.json、common.json、两个 html）、archive/历史文档；`_data` 卡片名保留 `opencode_client`（downstream 引用自洽）
- [ ] F5: `AgentEngineFactory` 在 A0 无生产调用方，待后续波次接线（符合 §6 规划，登记备查）

## engine-02（review 01，2026-08-13，结论 pass）

- [ ] F1: s2outline 同会话多候选且最新校验失败时，新回调会对所有未见过候选各跑一次 validator（旧实现每轮只验最新候选）；validator 与候选无关、结果等价，仅冗余调用，评估可接受
- [ ] F2: `OpencodeEngine` 门面委托用 `*args/**kwargs`（opencode_engine.py:222-277），丢失显式签名信息；两个方法保留显式签名、口径不一
- [ ] F3: 表征测试覆盖缺口：btplnav 的 prompt 返回后等待相位、s2 多候选去重路径无直接用例
- [ ] F4: graft 模块卡片（graft/app/services/opencode_client.md）仍指向旧模块，engine-01 改名遗留；docs/anbc_doc 模块卡片描述旧结构，待后续任务统一同步

## engine-03（review 01 + 复验，2026-08-13，结论 pass）

- [x] ~~F1 (blocking)~~ 已修复（486d16e）：`_request_slot` 非阻塞轮询，取消不再泄漏信号量许可，附 2 个回归测试
- [ ] F2: 一个 stalled 测试改由 prompt 返回后 grace 等待路径抛出（原主循环 idle 路径），异常类型与 trace 结构一致，review 判语义等价
- [x] ~~F5~~ 已闭环（engine-09）：`OpencodeEngine` 对齐协议形态（`create_session -> str`、新增 `run_session`/`list_messages`，门面旧名保留），S1 分片链路编排层只经协议方法驱动引擎
- [ ] 并发冒烟（S1 分片并行）需 dev 环境验证，本地未覆盖

## engine-08（review 01 + 复验，2026-08-13，结论 pass）

- [x] ~~P2-1~~ 已修复（8feb7f6）：协议注释校正（终态为 `agent_end`，官方无 `agent_settled`/`willRetry`）
- [x] ~~P2-2~~ 已修复（8feb7f6）：`create_subprocess_exec` 加 `limit=8MiB`（finalize 大 stdout 收割），PoC 需真实大输出复核
- [ ] P3-1: run 中外部 abort 要等 idle 超时才退出（pi_engine.py:469 附近）
- [ ] P3-2: `session.events` 缓冲只增不减
- [x] ~~P3-3~~ 已闭环（engine-09）：根因是 `-n title` 在 pi 0.73.1 为非法选项（进程直接退出），title 已不入 CLI；headless 默认 `--no-extensions`
- [ ] P3-4: 乱序响应/CRLF 容错等少数路径无测试
- [x] ~~未经真实 Pi 验证~~ 已闭环（engine-09 PoC）：pi 0.73.1 真实跑通分片链路，事件 schema 与快照一致；校准点（`-n`、扩展发现）见 reviews/engine-09-poc.md
- [ ] `tools` 按请求开关 Pi RPC 不支持，`run_session` 收到非 None 抛 ValueError——orchestrator 接入时带 tools 的链路不能切 pi
- [ ] provider/model 未接 DB 系统设置链路；会话绑定创建它的事件循环（编排层需同一线程桥接内 create+run）；`--no-session` 不落盘无 resume

## engine-07（review 01 + 复验，2026-08-13，结论 pass）

- [x] ~~F1 (P1 blocking)~~ 已修复（2d9f4a8）：EOF 后先 `_reap_process`（wait）再读 returncode，附真实时序回归用例
- [x] ~~F2 (P2)~~ 已修复（2d9f4a8）：stderr 伴随 drain task（有界尾部 8KB），防管道缓冲写满假停滞
- [x] ~~F3/F4~~ 顺手修复（2d9f4a8）：ERROR_PATTERNS 词边界；未配 model 时按请求 model_id 也记 warning
- [ ] F5: 同会话并发 run 无防护（state.process 覆盖）；prompt 未加 `--` 分隔——当前编排层串行不触发
- [ ] F6: heartbeat/idle 与 opencode_engine 是第二份内联拷贝，待 §5 SessionMonitor 收敛
- [x] ~~未做真实 CLI 联通验证~~ 已闭环（engine-09 PoC）：codex 0.147.0 真实跑通；`exec resume` 子命令拼法与 `agent_message` 事件键按实测校准，双轮 resume 复验通过
- [ ] 消息日志与 trace 在引擎进程内存，后端重启即失；resume 只依赖 codex 侧 thread 持久化
- [x] ~~orchestrator 的 EarlyCompletionPlan 链路只接 OpencodeEngine~~ 已闭环（engine-09）：`base.tool_completed_callback_from_plan` 落地 plan→协议回调适配，S1 分片链路只经协议方法驱动（带轮询相位的三条 finalize 链路仍由 OpencodeEngine 驱动）

## engine-04（review 01，2026-08-13，结论 pass）

- [ ] P3-1: 4xx 确定性错误也归入 `PromptDeliveryUncertainError`，文案对 4xx 场景轻微误导（行为正确，可按 HTTPStatusError 区分确定性拒绝）
- [ ] P3-2: 断线计时未覆盖首次失败请求自身的等待（最长 5s 计入 idle，分钟级 idle 下影响可忽略）
- [ ] P3-3: `PollReconnectExhaustedError` 抛出路径不取消在飞 worker（刻意设计，与既有 session-error 路径一致，无泄漏）
- [ ] 断线重连预算约 23s/次：opencode 重启超窗会显式失败（非 stall），需要更长容忍在 5090 配置层调 `OPENCODE_POLL_RECONNECT_*`
- [ ] worker 内 POST 读超时终结本轮（PromptDeliveryUncertainError），会话可能服务端跑完但产物无人回收；「投递不确定 → 转纯轮询等终态」补齐建议单独立项

## engine-05（review 01，2026-08-13，结论 pass）

- [ ] P3-1: delete 与被遗弃 worker 的理论竞态（idle 超时/收割超时/轮询断连三条错误路径 worker_task 未收割，finally DELETE 与在飞 POST 并发；worker 遗弃是 B3 前既有形态）
- [x] ~~P3-2~~ 已闭环（engine-09）：`_repair_json_payload` 改走协议方法（create_session/run_session），回收优先 `delete_session_quietly`、缺失回退协议 `delete_session` 且失败只告警，三引擎 repair 路径不炸
- [ ] P3-3: 技术标对话首试失败时新建会话不绑定也不删，靠卷清理兜底
- [ ] P3-4: 清理脚本 dry-run 的 `2>/dev/null` 掩盖 find 错误，误报「0 个文件」
- [ ] P3-5: 两个 business review 与 JSON repair 回收路径无直接用例
- [ ] 清理脚本 `cleanup-opencode-data.sh` 未实机 dry-run 过，建议起栈后验证一次

## engine-06（review 01 + 复验，2026-08-14，结论 pass）

- [x] ~~P2-1 (blocking)~~ 已修复（dd321ab）：pi create_session 握手窗口 CancelledError 穿 except Exception 致预算许可+进程双泄漏；改 BaseException + run_session 同类兜底，附 4 用例
- [ ] P2-2: 部署行为变化需晋级 PR 显式告知——既有部署 .env 的 `OPENCODE_MAX_CONCURRENCY` 静默失效（由 `AGENT_CONCURRENCY_BUDGET` 取代，默认 8）；5090 有效并发 1→8，`docker-compose.5090.yml` 取值归发布负责人确认
- [ ] P3-3: 架构总览文档（05-Harness基建.md 等）仍描述旧三池，漂移待统一更新
- [ ] Pi 会话创建后永不 terminate/delete 时许可与进程同生命周期滞留（即进程泄漏本身，孤儿回收归 engine-09/后续）
- [ ] 并发冒烟（S1 分片真实并行观察峰值 ≤ 预算）需 dev/5090 环境

## engine-09（review 01 + 复验，2026-08-14，结论 pass；PoC 记录留存 docs/plan/reviews/engine-09-poc.md）

- [x] ~~engine-03 F5 / engine-05 P3-2 / engine-07 接线遗留 / engine-08 校准项~~ 已随本任务关闭（协议对齐 + plan→回调适配 + repair 协议兜底 + 真实 CLI 校准）
- [x] ~~P2-1~~ 已修复（94daf29）：pi argv 形态/codex 8MiB limit 测试锁定；P3-1 PoC 文档笔误已修
- [ ] P3-2: 默认路径有意行为变化——分片会话 info.error 即抛 RuntimeError（原留 trace 靠 silent-shard 兜底），汇入既有 failed→重试路径，判为改进，备查
- [ ] P3-3: run_session 每次多一次 best-effort GET，开销可忽略
- [ ] P3-4: 适配器在回调内即 harvest，与 opencode 轮询「先停会话再 harvest」顺序相反；当前无带 produce_payload 的协议链路触发，未来检查点
- [ ] P3-5: `_run_protocol_session(early_tool_command=...)` 暂无传非空值的调用方
- [ ] 三条 finalize 链路（带轮询相位）仍只由 opencode 驱动；codex/pi 只接了 S1 分片
- [ ] 多分片真实并发冒烟、大输出/超长会话压测需 dev/5090（5090 切引擎前必做）
- [ ] PoC 结论：语义等价通过；候选优先级 pi > codex；AGENT_ENGINE 默认恒 opencode 不变
