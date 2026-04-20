# Git 协作约定

适用范围：`/Users/wlb/Agent/bid-project`

目标：多人并行加功能时，保证 `main` 始终可集成、可演示、可继续往前推进。

## 1. 基本原则

- `main` 是唯一主干分支
- 所有人都从最新 `main` 拉自己的工作分支
- 不直接向 `main` 推送代码
- 所有变更通过 PR 合入 `main`

当前仓库已经开启 `main` 保护，规则如下：

- 禁止直接 push 到 `main`
- 禁止 force push
- 至少需要 `1` 个 approval
- 必须通过 `frontend`、`backend` 两个检查
- 管理员同样受保护规则约束

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

先同步最新主干：

```bash
git checkout main
git pull origin main
```

### 开新分支

```bash
git checkout -b feature/your-change
```

例如：

```bash
git checkout -b feature/s9-toolbar
git checkout -b fix/s2-timeout-fallback
git checkout -b docs/git-workflow
```

### 开发并提交

提交信息尽量使用 Conventional Commits：

```bash
git add <files>
git commit -m "feat(s9): add toolbar actions"
git commit -m "fix(s2): handle opencode timeout fallback"
git commit -m "docs(repo): add git workflow guide"
```

### 推到远端

```bash
git push -u origin feature/your-change
```

### 提 PR

目标分支统一为 `main`。

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

## 5. 同步主干

如果你的分支落后 `main` 较多，先同步再继续提 PR。

简单做法：

```bash
git fetch origin
git rebase origin/main
```

如果你不熟悉 `rebase`，也可以用：

```bash
git fetch origin
git merge origin/main
```

团队里如果没有统一要求，优先选择自己更不容易出错的方式。

## 6. 紧急修复

线上或演示链路出现紧急问题时：

- 仍然从最新 `main` 拉分支
- 分支名建议用 `hotfix/...` 或 `fix/...`
- 修完后尽快提 PR 合回 `main`

示例：

```bash
git checkout main
git pull origin main
git checkout -b hotfix/s9-editor-blank
```

即使是紧急修复，也不要绕过 `main` 保护直接推送。

## 7. 不建议的做法

- 在本地 `main` 上直接开发
- 多个人共用同一个功能分支
- 一个 PR 同时塞功能、重构、格式化、文档和杂项修复
- 明知会冲突还长时间不同步 `main`
- 为了图快，临时关闭 `main` 保护规则

## 8. 当前仓库的最小共识

这套仓库现在不需要再引入 `develop`。

当前最简单、最稳的协作方式就是：

1. 所有人基于 `main` 开分支
2. 各自在分支上开发
3. 提 PR 回 `main`
4. 过 review 和 CI 后再合并

先把这条主线跑顺，比设计更复杂的 Git 流程更重要。
