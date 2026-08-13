# docs/plan 使用约定

本目录承载「计划 → 任务 → 评审」的交付流，与 `docs/` 根目录的专题方案文档（按日期命名）互补：根目录存设计结论，这里存可执行的任务拆分与交付状态。

```text
docs/plan/
├─ README.md            ← 本文件
├─ analysis/            ← 总 plan / 任务拆分分析（编排用，不直接派发给开发）
│  └─ 20260812-系统性重构.md
├─ tasks/               ← 最小独立可交付任务（handoff），一个任务一个文件
│  └─ {area}-{seq}.md   ← area: deadcode / harness / frontend
└─ reviews/             ← verify 产出的评审记录（按需创建）
```

## 任务文件格式

```yaml
id: {area}-{seq}
scope: 所属模块/能力域
status: pending | ready | in-progress | done | blocked
depends-on: [task-id, ...]
```

必备小节：`objective`、`context`（要先读的设计/架构文档）、`path`（本任务触碰的文件）、`现状`（代码证据）、`改造方案`、`verification`。

状态机：`pending ── 依赖全部 done ──► ready ──► in-progress ──► done / blocked`。

## 执行约定（继承根 AGENTS.md）

- 所有任务在 `Dev` 分支上以 `task/{id}` 隔离分支开发；提 PR 前先合最新目标分支。
- 性能参数取值只写 `code/docker-compose.5090.yml`，代码默认值必须保持本地安全。
- 后端验证用与 CI 对齐的环境（见根 AGENTS.md「验证建议」）；前端改动至少做构建冒烟。
- 提交前 `git status` 只提交本任务文件，`git diff --check` 必过。
