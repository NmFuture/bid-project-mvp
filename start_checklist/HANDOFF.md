# 团队一致性预检交接说明

## 主题思想

这套机制要解决的根本问题不是“启动前多跑一个脚本”，而是避免团队在不同代码、不同配置、不同依赖状态下讨论同一个问题。多人协作时，很多问题看起来像业务 bug，实际是本地状态不一致造成的。预检的目标是先把可控变量收敛，再进入开发、测试或 Agent 工作流。

核心原则：

- 先统一会影响行为的基线，再允许个人本地差异。
- 必须一致的内容用脚本阻断，不能只靠口头约定。
- 不必强一致的内容只提醒，避免影响正常个人开发。
- 本地私有信息只留在本机，不进入 Git。

## 当前严格一致边界

启动项目、运行测试或开启新的 Agent 会话前，必须先执行：

```bash
./start_checklist/pre-run-check.sh
```

当前会强制阻断的项目：

| 检查项 | 规则 | 为什么阻断 |
|---|---|---|
| 核心代码版本 | 本地 `HEAD` 必须等于 `pre-run-checklist.yaml` 中的 `target.syncBranch`，当前默认 `origin/main` | 保证大家运行的是同一份代码 |
| 本地 `.env` 配置 | `code/.env` 必须存在，且关键服务配置项必须填入 | 保证服务能按同一套基础连接参数启动 |

代码版本采用严格模式：本地超前、落后、分叉都会阻断运行。原因是这些状态都会让“我这里能跑/你那里不能跑”的讨论失去共同前提。

## 当前只提醒不阻断的项目

| 检查项 | 当前行为 | 原因 |
|---|---|---|
| `code/` 工作区未提交修改 | warn | 允许个人正在开发，但提醒不要把本地修改误当成团队基线 |
| 后端 `.venv` 和 `requirements.txt` | warn | 依赖问题常见但不一定每次都阻断，需要开发者按提示处理 |
| 前端 `node_modules` 和 `package-lock.json` | warn | 同上，锁文件新于安装目录时提醒重新 `npm ci` |
| LLM / OCR 密钥 | warn | 脚本只能判断是否存在疑似 key，不能可靠判断有效期 |
| 素材目录 | warn | `.localdata` 可自动生成，默认不冻结素材版本 |

如果后续发现某一类问题反复影响团队，可以把对应检查项升级为 required，并同步修改脚本为 fail。

## 每个人的日常流程

首次拉取或更新这套机制后，每台机器执行一次：

```bash
./start_checklist/install-git-hooks.sh
```

这个脚本会安装本机 Git hook。Git hook 不会随仓库自动分发，所以每台机器需要执行一次。

每次启动项目前执行：

```bash
./start_checklist/pre-run-check.sh
```

需要强制重新检查时执行：

```bash
./start_checklist/pre-run-check.sh --force
```

只查看当前状态时执行：

```bash
./start_checklist/pre-run-check.sh --status
```

## Git hook 的定位

`post-merge` 和 `post-checkout` hook 会在 `git pull` 或切分支后自动强制预检并显示结果。hook 是 warn-only，不阻断 Git 操作本身。

真正阻断运行的是 `pre-run-check.sh` 的退出码。因此团队应把它放到实际启动入口之前，例如本地启动说明、Agent 会话启动步骤、后续统一启动脚本或 CI 检查中。

## 文件职责

| 文件 | 是否提交 | 职责 |
|---|---|---|
| `pre-run-check.sh` | 是 | 实际执行预检和阻断 |
| `pre-run-checklist.yaml` | 是 | 团队共享的检查清单和目标分支配置 |
| `install-git-hooks.sh` | 是 | 为每台机器安装本地 Git hook |
| `README.md` | 是 | 使用说明 |
| `HANDOFF.md` | 是 | 团队交接和治理说明 |
| `.checked.local.json` | 否 | 本机缓存和打勾状态 |
| `team-bootstrap.local.yaml` | 否 | 本机私有 LLM/OCR 配置和密钥 |

## 例外处理

如果某人确实需要在个人分支上调试，应该明确这是“个人实验状态”，不要把该状态作为团队可复现结论。需要恢复团队一致性时，先让本地 HEAD 回到 `target.syncBranch` 对应提交，再运行预检。

如果团队短期需要把基准从 `origin/main` 切到其他分支，只改 `pre-run-checklist.yaml` 的 `target.syncBranch`，并通过 PR review。不要每个人私下改脚本。

如果 `.env` 的关键配置项发生变化，应同步更新脚本中的配置检查、`.env.example` 和本说明。否则会出现“文档说需要，脚本没检查”或“脚本检查了，样例没给”的漂移。

## 维护规则

- 修改必检项要走 PR review。
- 修改 `pre-run-checklist.yaml` 后要确认脚本实际读取或执行了该规则。
- `.checked.local.json`、`team-bootstrap.local.yaml`、`code/.env` 永远不提交。
- 交付前至少验证：

```bash
bash -n start_checklist/pre-run-check.sh start_checklist/install-git-hooks.sh
git diff --check -- .gitignore start_checklist
./start_checklist/pre-run-check.sh --status
```

## 判断标准

这套机制成功的标志不是“没有 warning”，而是：

- 团队讨论问题时，先确认大家在同一代码基线。
- 必须一致的状态不能被静默跳过。
- 本地私有配置不会误提交。
- 检查规则和文档能被同一套文件维护，减少口头传递。
