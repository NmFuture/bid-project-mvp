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
- [ ] F5: `AgentEngine` 协议与 `OpencodeEngine` 实现结构仍不一致（`run_session` vs `send_prompt`、`create_session -> str` vs `dict`、缺 `delete_session`）；C 波次接新内核前需对齐 → 已排入 engine-09（PoC 接线前置）与 engine-05（delete_session 实现）
- [ ] 并发冒烟（S1 分片并行）需 dev 环境验证，本地未覆盖

## engine-08（review 01 + 复验，2026-08-13，结论 pass）

- [x] ~~P2-1~~ 已修复（8feb7f6）：协议注释校正（终态为 `agent_end`，官方无 `agent_settled`/`willRetry`）
- [x] ~~P2-2~~ 已修复（8feb7f6）：`create_subprocess_exec` 加 `limit=8MiB`（finalize 大 stdout 收割），PoC 需真实大输出复核
- [ ] P3-1: run 中外部 abort 要等 idle 超时才退出（pi_engine.py:469 附近）
- [ ] P3-2: `session.events` 缓冲只增不减
- [ ] P3-3: 空 title 会让真实 pi 退出
- [ ] P3-4: 乱序响应/CRLF 容错等少数路径无测试
- [ ] 未经真实 Pi 验证（协议按 rpc.md 2026-08-13 快照），留 engine-09 PoC 核对事件 schema
- [ ] `tools` 按请求开关 Pi RPC 不支持，`run_session` 收到非 None 抛 ValueError——orchestrator 接入时带 tools 的链路不能切 pi
- [ ] provider/model 未接 DB 系统设置链路；会话绑定创建它的事件循环（编排层需同一线程桥接内 create+run）；`--no-session` 不落盘无 resume
