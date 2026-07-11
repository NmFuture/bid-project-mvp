# 本地运行预检（pre-run check）

## 用途

每次运行项目（`docker compose up`、本地启动、进入新的 agent 会话）之前，
确保**核心代码版本与团队基准严格对齐、依赖和本地配置就绪、密钥/权限无异常**。

设计原则：**会话首检 + 打勾持久化**——只在首次/缓存失效时做一次完整检查，
之后直接静默放行，不会每次烦你。

## 文件结构

```
start_checklist/
├── pre-run-checklist.yaml        # 清单定义（提交到 git，团队共享）
├── pre-run-check.sh              # 校验脚本（提交到 git）
├── install-git-hooks.sh          # 安装本地 post-merge/post-checkout hook
├── .checked.local.json           # 打勾状态（本地私有，已被 .gitignore 覆盖）
├── team-bootstrap.local.yaml     # Agent 私有 LLM/OCR 配置（本地私有，已被 .gitignore 覆盖）
├── README.md                     # 本文件
└── HANDOFF.md                    # 团队一致性治理交接说明
```

## 用法

```bash
# 运行预检 / 读缓存
./start_checklist/pre-run-check.sh

# 忽略缓存，强制重检（换机器、切分支、拿到新代码后想重新对齐）
./start_checklist/pre-run-check.sh --force

# 只看当前打勾状态（不重新校验）
./start_checklist/pre-run-check.sh --status

# 每台机器首次拉取后安装本地 hook（Git hook 不会随仓库自动分发）
./start_checklist/install-git-hooks.sh
```

## 缓存失效（触发重新检查）条件

- 代码版本变更（pull / rebase / checkout 改变 HEAD）
- `code/` 下核心目录文件在 `.checked.local.json` 写入后发生了修改
- `code/.env` 内容变化
- 距离上次 check 超过上限（默认 7 天，可在 yaml 中 `target.maxStaleDays` 调整）

## 检查项一览

| 项 | 类型 | 说明 |
|---|---|---|
| 核心代码版本对齐 | **必检** | 本地 `HEAD` 必须与 `origin/main`（或设定分支）一致；超前、落后、分叉都阻断 |
| code/ 工作区状态 | 推荐 | 是否有未提交的本地修改（如有请确认是有意保留） |
| 后端 Python 依赖 | 推荐 | `.venv` 存在，且 `requirements.txt` 未新于 `.venv` |
| 前端 Node 依赖 | 推荐 | `package-lock.json` + `node_modules` 就绪，且锁文件未新于安装目录 |
| 本地 .env 配置完整 | **必检** | 关键服务配置项已填入 |
| LLM / OCR 密钥 | 推荐 | 提醒确认未过期、未误提交 |
| 素材目录就绪 | 推荐 | `.localdata` 可自动生成 |

**必检项（required）** 不通过则脚本退出码为 1，必须先解决再运行项目；
**推荐项（recommended）** 不通过只警告、不阻断。

当前脚本的严格一致性边界是：代码提交与基准分支一致、关键 `.env` 项存在。
依赖安装目录、未提交本地修改、密钥有效期和素材目录只做本地提醒；如果这些也要强阻断，
需要把对应检查项升级为 required，并在脚本里按 fail 处理。

## Git hook

仓库提供 `install-git-hooks.sh`，用于在本机 `.git/hooks/post-merge` 和
`.git/hooks/post-checkout` 中接入预检。Git hook 是本地文件，不会随仓库自动分发；
每台机器首次拉取后需要执行一次安装脚本。

hook 采用 warn-only：`git pull` / `git checkout` 后会强制重检并显示结果，
但不阻断 Git 操作本身。真正阻断运行的是启动前手动或统一启动脚本调用
`pre-run-check.sh` 的退出码。

## 关于 team-bootstrap.local.yaml

该文件是 Agent（Claude Code / Codex）的私有本地配置入口，
指导 Agent 把 LLM / OCR 模型与密钥落到仓库的本地配置里。
预检清单的 `secrets` 项只做"是否过期/是否误提交"提示，不校验密钥本身有效期。
