# AI 协作规则

本文件是本仓库 AI agent 与团队成员共用的行为约定。任何 agent 新增或修改指令、配置、Skill 或代码前，应先遵守这里的边界。

## 指令与配置布局

- 根 `AGENTS.md` 是多 AI 工具共用的团队规则唯一事实来源。
- 根 `CLAUDE.md` 只作为 Claude Code 入口，应通过 `@AGENTS.md` 导入本文件；不要同时维护另一套团队规则。
- 需要拆分的团队规则放到 `.claude/rules/`，一个主题一个文件；只对特定路径成立时使用 `paths` frontmatter。
- 只对某个模块成立的局部规则，放在对应目录的 `CLAUDE.md`，内容必须短、具体、只描述该目录的差异。
- 个人本地偏好放 `CLAUDE.local.md`、`.claude/settings.local.json` 或主目录下的个人配置，永不提交。
- 必须强制执行的规则放 CI、hooks、managed settings 或权限配置，不只写在指令文件里。

## 提交边界

- 团队共享规则可以提交：`AGENTS.md`、`CLAUDE.md`、`.claude/rules/**`、模块内 `CLAUDE.md`。
- 个人本地配置禁止提交：`CLAUDE.local.md`、`.claude/settings.local.json`、`.env.local`、`.env.*.local`、真实凭证、个人 sandbox 地址和临时调试记录。
- 修改团队共享规则要走 PR review，像代码变更一样审查。
- 不要把冲刺计划、临时待办、会议流水和调试日志写进指令文件。
- 已有 README、架构说明或长流程材料时，优先按需读取或引用，不把大段内容复制进根指令。

## 开发规范

- 优先遵循现有代码结构、命名、接口和工具链，不另起一套实现风格。
- 改动前先读相关上下文，确认数据流、调用链和已有约定。
- 保持改动小而清晰，只解决当前目标，不顺手重构无关代码。
- 除非用户主动要求，不新增文档；确需记录时优先更新已有规则或相邻说明。
- 文档、注释和 Skill 说明默认使用中文，表达要短、准、可执行。
- 失败要显式暴露，保留错误信息和已完成状态，不要静默吞掉异常。
- 提交前验证核心链路，能跑测试就跑测试，不能跑要说明原因。
- 提交前先看 `git status`，只提交自己负责的文件。

## 项目边界

- 本项目代码主入口在 `code/`。
- 前端位于 `code/sewpg-bid-frontend/`，后端位于 `code/sewpg-bid-backend/`。
- 技术标任务默认只改技术标页面、API、service、Skill、素材/Wiki 和测试。
- 商务标任务默认只改商务标页面、API、service、Skill、素材/Wiki 和测试。
- 确实需要改共享底座时，要确认另一条线行为不被破坏。
- 技术标入口使用 `/api/technical/...` 和 `/workspace/tech/...`。
- 商务标入口使用 `/api/business/...` 和 `/workspace/business/...`。
- 解析页入口使用 `/parse/technical` 和 `/parse/business`；上传解析所需的临时承载是实现细节，不要在前端表达成“先新建项目”。
- 机型后的中文布局或配置后缀（如“上置”“下置”）只用于系统内部选型和素材过滤；正式投标材料只写前面的英数字型号编码，不把省略这类中文后缀判为错误。
- 表格数值填写以目标表格字段或单位列标注的单位为准：从素材读取数值和来源单位，按同量纲换算系数调整数量级后只填数值，不在响应单元格重复写单位。
- 不提交真实标书、密钥、数据库文件、上传临时文件和本地日志。

## 发布分工与改动边界

本仓库有两条线：`Dev` 是开发主线，`main` 只保存已在 5090 验证过的稳定版本，由发布负责人合入。判断一处改动该在哪条线上做，标准只有一个：**它要靠什么环境才能验证**。

### 归发布负责人：在 `Dev → main` 晋级 PR 里改，合入后立即回流 `Dev`

只有 5090 实机能验证的部署适配：

- Compose、Dockerfile、部署脚本中与 GPU 绑定、镜像平台、CUDA 构建相关的部分。
- 本地模型服务（vLLM/OCR）的启动参数与资源配额。
- 性能与资源参数的**取值**：并发度、渲染 DPI、显存占比、批量上限。取值只写进 5090 专属配置层，见下节。
- 5090 现场发现、只影响部署形态且不改变业务行为的修复。

### 归模块负责人：在 `Dev` 改，随正常开发流程晋级

在本地或 Dev 环境就能验证的应用层改动：

- 业务逻辑、接口、任务编排、并发结构、错误处理、数据落库策略。
- 把上述性能参数**做成可配置项**（环境变量或配置文件）并给出安全默认值。
- 前端页面、API、service、Skill、测试。

### 接缝：逻辑归 `Dev`，取值只落在 5090 专属配置层

需要 GPU 或真实素材才能调优的功能，不等于"没有 5090 就改不了"，而是要拆开：模块负责人在 `Dev` 把参数做成可配置项并给出本地安全默认值，发布负责人在 5090 实测出取值。

取值往哪写决定了会不会影响别人。配置分三层，回流安全性完全不同：

| 层 | 例子 | 回流到 `Dev` | 对其他人本地是否生效 |
| --- | --- | --- | --- |
| 代码里的默认值 | `int(os.getenv("X_CONCURRENCY", "2"))` | 会 | **会**——所以必须是本地安全值 |
| `code/docker-compose.5090.yml` | `X_CONCURRENCY: "8"` | 会 | **不会**，只有 `up-5090.sh` 叠加这一层 |
| `code/.env` | 机密、机器特定路径 | 不会（已在 `.gitignore`） | 不会 |

**规则：5090 实测出来的取值只写进 `docker-compose.5090.yml`，不动代码里的默认值。**

举例：5090 上实测证书 OCR 并发可以从 1 开到 8，正确做法是在 `docker-compose.5090.yml` 对应服务下加 `CERT_OCR_CONCURRENCY: "8"`，代码里的默认值保持 `2`。回流后其他人拉 `Dev`，本地仍是 2，只有 5090 是 8。
反例：直接把代码里的默认值改成 8 再回流，所有人本地默认并发 8，会打爆没有本地模型服务的开发环境。

并发正确性、锁是否生效、断点能否续跑，用 mock 或任意后端在 `Dev` 都能验证，与有没有 GPU 无关。

### 硬性约束

- `main` 不接收业务逻辑改动。功能实现只走 `Dev`；在 `main` 上写业务代码会让同一处适配在每次晋级时重复冲突。
- 每次合入 `main` 后立即开 `main → Dev` 回流 PR，否则下一次冻结的 `Dev` SHA 会把适配和安全补丁覆盖回旧版本。
- 5090 上发现的应用层问题，写成带定位证据和实测数据的反馈交给模块负责人，不在 `main` 上就地修复。
- 5090 的工作副本是单分支 clone，只接收已批准的 `main`，任何时候保持 `git status` 干净。要试参数就用仓库目录之外的临时 override 文件追加到 `docker compose -f` 链末尾，试完跑 `code/scripts/up-5090.sh` 恢复；不热改工作树内的受控文件，否则下次 `git checkout main` 冲突且改动无法追溯。
- 覆盖 `docker-compose.5090.yml` 里的服务参数时注意：Compose 的 `command` 是整体替换，不能部分覆盖，改 vLLM 之类的启动参数必须把整条 `command` 列表重写一遍。
- 本地模型只使用 GPU 0；Compose 必须显式绑定 GPU 0，禁止 `gpus: all`，GPU 1 保留给其他任务，本项目不得占用。

## Skill 规范

- 复杂能力优先沉淀为可复用 Skill 或模块，避免为单个 case 写死逻辑。
- Skill 位于 `code/sewpg-bid-backend/opencode/skills/<skill-name>/`，命名按 `bid-tech-*`、`bid-business-*`、`bid-material-*` 管理。
- 开发某个 Skill 时，默认只改对应 Skill 目录；发现输入、接口或调用链问题时，先记录并单独提出代码改动。
- `SKILL.md` 建议控制在 100~200 行，原则上不要超过 500 行；详细说明、示例和长流程拆到 `references/`。
- frontmatter：`description` 用中文、触发条件式，只回答「何时用本 skill」，不写策略与用法（范例见 `bid-tech-tag-importer`）；`allowed-tools` 必填并按最小权限收敛。
- 阶段命名、命令别名与历史工作目录的对应关系统一引用 `opencode/skills/STAGES.md`，不要在各 SKILL.md 里各自解释。
- AI/Skill 输出必须可验证，关键结论要保留来源、证据或可追踪中间结果。
- 不能按单个样本硬编码文件名、字段值或答案。判断边界：业主固定模板的**结构特征**（列名、附表编号、章节框架、同义词典）可以硬编码，但须在代码处注明模板来源；单个项目的**内容值**（数值、日期、项目名）不可以。

## 本地运行预检（必须）

每次进入新的运行会话（启动项目、运行测试、运行 agent 工作流）之前，
**必须先执行本地预检脚本**，确保核心代码版本与团队基准对齐、依赖与配置就绪。

```bash
./start_checklist/pre-run-check.sh        # 首次/缓存失效时做完整检查；命中缓存时静默放行
./start_checklist/pre-run-check.sh --force   # 强制重检
./start_checklist/pre-run-check.sh --status  # 查看打勾状态
```

设计见 `start_checklist/README.md`。

**执行规范（人 + Agent 都适用）：**

- 缓存命中且未过期 → 直接放行，不要重复输出清单。
- 缓存未命中 → 列出各项结果，必检项（代码版本、.env 配置）未通过时先解决再运行；推荐项仅警告、不阻断。
- 把预检结果作为本次会话的起点状态报告挂出来，不要默默吞掉警告。
- 修改 `pre-run-checklist.yaml` 里的检查项要走 PR review；`.checked.local.json` 是本地私有文件，不要提交。

hook 级联动：仓库的 `.git/hooks/post-merge` / `post-checkout` 已接入该脚本（warn-only），
每次 `git pull` / 切分支后若代码或 .env 真正变更，脚本会自动重新触发。

## 验证建议

### 后端测试跑在与 CI 对齐的环境里

不要用系统 Python 或 conda 全局环境跑后端测试。全局环境的依赖与 `requirements.txt`
不一致时会产生大量与改动无关的失败（实测缺一个 `aiosqlite` 就导致 10 个用例报
`ModuleNotFoundError`），这些噪声会淹没真实问题，也会让「与基线对比」得出错误结论。

首次准备与 CI 同版本的环境（Python 3.12，`.venv` 已在 `.gitignore` 中）：

```bash
cd code/sewpg-bid-backend
uv venv --python 3.12 .venv
uv pip install --python .venv -r requirements.txt pytest
```

跑测试用与 CI 一致的命令与环境变量，三者缺一不可：

```bash
cd code/sewpg-bid-backend
APP_STORE_BACKEND=memory \
DATABASE_URL="postgresql+asyncpg://biduser:bidpass@localhost:5432/bidplatform" \
.venv/bin/python -m pytest -m "not integration" <相关测试文件>
```

- `-m "not integration"`：不加会连带跑需要 MinIO/Redis 的集成用例（CI 由独立
  job 覆盖，本地缺服务必失败）。
- `APP_STORE_BACKEND=memory`：CI 的 backend job 用内存后端。
- `DATABASE_URL`：指向本地 Compose 已映射的 `localhost:5432`。

集成用例按 CI 的 `backend-integration` job 单独跑，需先起依赖服务：

```bash
cd code && docker compose up -d --wait postgres minio redis opencode
cd sewpg-bid-backend && BID_RUN_INTEGRATION=1 APP_STORE_BACKEND=postgres \
  .venv/bin/python -m pytest -m integration
```

判断改动是否引入新失败时，基线与当前分支必须用**同一个**上述环境跑**同一组**用例，
比对失败集合而非失败总数；失败原因不同也算不同问题，不能只看用例名是否重合。
CI 的结论优先于本地：本地红而 CI 绿时先怀疑本地环境，不要据此改代码或改断言。

### 其他

- 前端页面或路由改动至少做构建或页面冒烟。
- Docker 或部署改动需要在 `code/` 下确认服务可启动，并验证健康检查。
- 所有代码变更提交前运行：

```bash
git diff --check
```
