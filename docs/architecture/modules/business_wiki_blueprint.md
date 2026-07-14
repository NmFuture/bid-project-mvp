# business_wiki_blueprint

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/business_wiki_blueprint.py` |
| 层级 | 服务层 |
| 领域 | 商务标 |
| 行数 | 30 |

**职责**: 桥接模块：用 importlib 动态加载 Skill `bid-business-wiki-material-builder/scripts/business_wiki_blueprint.py`，把 Skill 内的 `build_business_wiki_blueprint` / `load_json` 暴露给后端——保证后端与 Skill 用同一份蓝图逻辑（单一事实源）。

## Input / Output
- 透传 Skill 脚本函数；Skill 脚本不存在时启动即 RuntimeError（显式失败）。

## 调用链
- **上游**: `business_wiki_generation`。
- **下游**: Skill 脚本 `opencode/skills/bid-business-wiki-material-builder/scripts/business_wiki_blueprint.py`。

## 中间数据与状态
- 无；模块加载注册为 `business_wiki_blueprint_skill`。
