---
id: deadcode-04
scope: 后端 / API 路由层
status: pending
depends-on: [deadcode-03]
---

# deadcode-04：后端孤儿端点清理

## objective

清理「前端永不调用、也无其他消费方」的后端端点；对有消费方或属有意保留的端点，加注释说明并保留。

## context

- `docs/anbc_doc/架构总览/04-技术标操作串讲.md` §7
- `code/sewpg-bid-frontend/src/workspaces/README.md:15`（coverage/export 页面属「有意不接」的架构决策）
- 总 plan：`docs/plan/analysis/20260812-系统性重构.md` §5 决策点

## path

- `code/sewpg-bid-backend/app/api/routes/technical.py`
- 对应的 service 实现（若端点删除后 service 函数也变孤儿，一并处理）
- `code/sewpg-bid-backend/opencode/skills/`（确认是否直调，只读）

## 现状（2026-08-12 复核证据，行号为复核时值）

技术轨候选孤儿端点：

- `technical.py:412` submit-review、`:490` gaps/recheck（前端有封装但零调用，deadcode-03 删封装后即成孤儿）
- `technical.py:534` coverage（前端连封装都没有，覆盖率由页面本地计算）
- `technical.py:572` document/force-save、`:629` export/check、`:634` export
- Wiki 节点 CRUD 端点（Wiki 页只读）
- tag-import/preview|commit（**疑似被 Skill 直调**，是保留候选）

## 改造方案

1. **先确认消费方再动手**：对每个候选端点 grep `opencode/skills/`（Skill 脚本可能直调后端）、`code/scripts/`、测试；tag-import 若被 Skill 直调则保留并加注释。
2. coverage/export 系列：`workspaces/README.md:15` 明确不接前端页面，需拍板端点去留；倾向「保留端点 + 注释说明有意不接线」，除非确认无任何消费方。
3. 确认无消费方的端点删除；连带 service 函数若变孤儿一并删。
4. 商务轨同名端点（若有）同样过一遍。

## verification

- 后端测试：`tests/` 中相关路由测试随之调整或删除；跑受影响测试文件。
- 防回退测试注意：旧 `/api/projects...` 等已不注册端点的测试模式可参照。
