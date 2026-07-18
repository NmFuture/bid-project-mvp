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

- 后端相关改动优先在 `code/sewpg-bid-backend/` 下运行聚焦测试，再按风险扩大：

```bash
PYTHONPATH=. pytest <相关测试文件>
```

- 前端页面或路由改动至少做构建或页面冒烟。
- Docker 或部署改动需要在 `code/` 下确认服务可启动，并验证健康检查。
- 所有代码变更提交前运行：

```bash
git diff --check
```
