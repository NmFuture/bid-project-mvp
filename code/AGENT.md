# 项目执行说明

这份文件给后续参与 `code/` 目录开发的同学和智能体使用。当前项目文档已经收口，历史文档只做追溯，不再作为当前开发基线。

## 1. 开工先读

当前只以仓库根目录 `doc/` 下 3 个文档为准：

- `/Users/wlb/Agent/bid-project/doc/代码结构梳理.md`
- `/Users/wlb/Agent/bid-project/doc/需求梳理.md`
- `/Users/wlb/Agent/bid-project/doc/研发计划.md`

历史文档已经归档到：

```text
/Users/wlb/Agent/bid-project/doc/archive/2026-05-26-old-docs/
```

归档文档只用于查历史，不要把其中的旧阶段号、旧接口、旧路由、旧验收记录当成当前事实。

## 2. 当前代码结构

```text
code/
  docker-compose.yml
  sewpg-bid-frontend/   # React + Vite 前端
  sewpg-bid-backend/    # FastAPI、服务层、队列、OnlyOffice、OpenCode/Skill
  sewpg-bid-api/        # 接口说明目录，不是运行时代码
  AGENT.md
  plan.md
  progress.md
```

本地启动入口：

```bash
cd /Users/wlb/Agent/bid-project/code
docker compose up -d --build
```

## 3. 当前产品口径

项目是 AI 数智化投标平台，支持技术标和商务标两条链路。技术标和商务标共享登录、部署、数据库、对象存储、基础组件，但业务入口、页面、API、service、Skill、素材/Wiki、文档生成和审计要按标类隔离。

当前研发先跑通商务标端到端；技术标质量提升后续单独梳理。

当前主流程按产品视角理解为：

```text
招标文件导入
-> 智能解析
-> 目录与模板
-> 素材匹配与缺口处理
-> 标书生成
-> 在线共创
-> 格式处理
-> Word/PDF 导出
```

技术标入口使用 `/api/technical/...` 和 `/workspace/tech/...`。

商务标入口使用 `/api/business/...` 和 `/workspace/business/...`。

旧 `/api/projects...`、旧根项目路由、旧单线阶段号和旧 mock 网关不再作为当前基线。

## 4. 当前开发规则

- 技术标任务默认只改技术标页面、API、service、Skill、素材/Wiki 和测试。
- 商务标任务默认只改商务标页面、API、service、Skill、素材/Wiki 和测试。
- 确实需要动共享底座时，要确认另一条线行为不被破坏。
- OpenCode/Skill 的真实位置是 `sewpg-bid-backend/opencode/skill/`，命名按 `bid-tech-*`、`bid-business-*`、`bid-material-*` 管理。
- Skill 开发只能改对应 `sewpg-bid-backend/opencode/skill/<skill-name>/` 目录；发现输入、接口或调用链问题时，先记录并单独提出代码改动。
- 素材库按 `技术标/商务标 + 通用素材/客户素材/项目素材` 隔离。
- 权限不能说过头：前端 workspace guard 已有，但后端角色、工作区、项目类型强授权仍是生产加固项。
- 重大代码变更后同步 `code/progress.md`，计划变化同步 `code/plan.md`，不要把逐次调试流水写进最终 3 份文档。
- 每个人在自己的任务分支开发，不直接改公共分支；小功能完成后及时提交、每天 push、任务完成后发 PR。
- 提交前先看 `git status`，只提交自己负责的文件；不提交真实标书、密钥、数据库文件、上传临时文件和本地日志。

## 5. 验证建议

后端相关改动优先在 `/Users/wlb/Agent/bid-project/code/sewpg-bid-backend` 下运行聚焦测试，再按风险扩大：

```bash
PYTHONPATH=. pytest <相关测试文件>
git diff --check
```

前端页面或路由改动至少做构建或页面冒烟；Docker/部署改动需要确认 `docker compose up -d --build` 后健康检查可用。
