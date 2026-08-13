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
