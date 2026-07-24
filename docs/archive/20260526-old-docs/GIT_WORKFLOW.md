# Git 协作约定

适用范围：`/Users/wlb/Agent/bid-project`

目标：多人并行加功能时，保证个人开发、测试集成和生产主干边界清楚。

## 1. 基本原则

- `wlb` 是当前个人开发分支，日常开发和本机验证默认在这里完成
- `Dev` 是测试集成分支，阶段性验证通过后再进入 `Dev`
- `main` 是生产/稳定主干，只接收已经在 `Dev` 验证过的内容
- 不直接向 `main` 推送代码
- 合入 `main` 通过 PR 完成

当前 `main` 已开启 Branch Protection，规则如下：

- 合并只能通过 PR，禁止直接 push 到 `main`
- 禁止 force push，禁止删除 `main`
- 合并前必须通过 `MVP Quality Gate / frontend`、`MVP Quality Gate / backend` 两个检查
- 合并前分支需同步到最新 `main`（Require branches to be up to date）
- 至少需要 `1` 个 approval
- 管理员同样受保护规则约束，不能绕过

## 2. 分支命名

建议统一使用下面几类：

- `feature/...`
  - 新功能，例如 `feature/s7-stream-progress`
- `fix/...`
  - 缺陷修复，例如 `fix/onlyoffice-callback`
- `docs/...`
  - 文档更新，例如 `docs/git-workflow`
- `chore/...`
  - 杂项维护，例如 `chore/cleanup-env-example`

如果想统一 Codex 自动分支前缀，也可以使用：

- `codex/...`

核心原则只有一个：分支名一眼能看出这次改什么。

## 3. 日常开发流程

### 开工前

先确认当前工作树和分支：

```bash
git status --short --branch
```

当前本机日常开发默认在 `wlb` 分支。如果要从远端测试分支同步：

```bash
git fetch origin
git switch wlb
git pull --ff-only origin wlb
```

### 可选：开主题分支

如果改动较大，可以从 `wlb` 再开 `feature/...`、`fix/...`、`docs/...` 或 `codex/...` 主题分支；小的阶段性修正也可以直接在 `wlb` 提交。

### 开发并提交

提交信息尽量使用 Conventional Commits：

```bash
git add <files>
git commit -m "feat(materials): add model filter"
git commit -m "fix(onlyoffice): handle callback url"
git commit -m "docs(repo): add git workflow guide"
```

### 推到远端

当前个人分支：

```bash
git push origin wlb
```

主题分支：

```bash
git push -u origin feature/your-change
```

### 进入测试和主干

常规顺序：

1. 本地 `wlb` 完成并验证。
2. 推送 `wlb`，必要时合入 `Dev` 做测试验证。
3. `Dev` 验证通过后再提 PR 或合并到 `main`。

PR 里至少说明：

- 改了什么
- 为什么改
- 会影响哪里
- 你怎么验证的

## 4. PR 合并要求

每个 PR 尽量做到：

- 一次只解决一个相对清晰的问题
- 不把无关改动混进去
- 标题直接说明目的
- 描述里写清验证方式

当前合并前必须满足：

- 至少 `1` 个同事 approval
- GitHub Actions 中 `frontend`、`backend` 通过

建议：

- 小步快跑，PR 不要过大
- 有争议的改动先对齐方案，再开工
- 如果只是临时试验，不要直接往共享分支堆积
- 进入 `main` 的 PR base 写 `main`，不要把 PR 的 base 指向其他人的个人分支；功能之间有依赖时，先等前置内容进入 `Dev` 或 `main` 后再继续

## 5. 同步主干

如果你的分支落后远端较多，先同步再继续提 PR。

简单做法：

```bash
git fetch origin
git pull --ff-only origin wlb
```

如果正在主题分支上，可以按团队习惯选择 rebase 或 merge 到最新 `wlb` / `Dev`。

示例：

```bash
git fetch origin
git rebase origin/wlb
```

团队里如果没有统一要求，优先选择自己更不容易出错的方式。

## 6. 紧急修复

线上或演示链路出现紧急问题时：

- 仍然从最新稳定分支拉修复分支
- 分支名建议用 `hotfix/...` 或 `fix/...`
- 修完后尽快提 PR 合回 `main`

示例：

```bash
git checkout wlb
git pull --ff-only origin wlb
git checkout -b hotfix/s9-editor-blank
```

即使是紧急修复，也不要绕过 `main` 保护直接推送。

## 7. 不建议的做法

- 在本地 `main` 上直接开发
- 把没有在 `Dev` 验证过的大改动直接推向 `main`
- 多个人共用同一个功能分支
- 一个 PR 同时塞功能、重构、格式化、文档和杂项修复
- 明知会冲突还长时间不同步 `main`
- 为了图快，临时关闭 `main` 保护规则
- 在前置 PR 还没合入 `main` 之前，就把 base 指向它去提栈式 PR

## 8. 当前仓库的最小共识

这套仓库当前已经使用 `Dev` 作为测试集成分支，不再另行引入小写 `develop`。

当前最简单、最稳的协作方式就是：

1. 个人开发先落在 `wlb` 或主题分支
2. 阶段性验证后进入 `Dev`
3. `Dev` 验证通过后再进 `main`
4. `main` 保持可演示、可交付

先把这条主线跑顺，比设计更复杂的 Git 流程更重要。
