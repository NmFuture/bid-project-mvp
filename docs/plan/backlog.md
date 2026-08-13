# Backlog

verify 产出的 non-blocking findings 登记处（按任务追加）。

## engine-01（review 01，2026-08-13，结论 pass）

- [ ] F1: commit message 测试口径（2265 passed）与复跑（2167 passed + 30 deselected）不一致，后续 commit 统一用复跑口径
- [ ] F2: A0 阶段 `OpencodeEngine` 尚不满足 `AgentEngine` 协议（`create_session` 返回 dict、缺 `run_session`/`list_messages`/`delete_session`），`factory.create() -> AgentEngine` 为名义标注；对齐排期 engine-02/03
- [ ] F3: 调用方口径 17 个 service 文件 + `scripts/technical_wiki_preview.py`（engine-01 任务清单原文写 16 处，遗漏 scripts 一处）
- [ ] F4: 遗留旧名引用：`graft/` 索引、架构总览其它文档（00/04/05、_data/business.json、common.json、两个 html）、archive/历史文档；`_data` 卡片名保留 `opencode_client`（downstream 引用自洽）
- [ ] F5: `AgentEngineFactory` 在 A0 无生产调用方，待后续波次接线（符合 §6 规划，登记备查）
