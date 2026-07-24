# API 目录说明

这个目录用于存放当前项目的接口契约资产，不放运行时代码。

建议后续放这些内容：

- OpenAPI / Swagger / YAML
- Apifox 导出文件
- 字段级接口说明
- 接口变更记录

当前正式口径以这些文件为准：

- `./当前API接口核心版.md`
- `../../AGENTS.md`
- `../sewpg-bid-backend/app/api/routes/technical.py`
- `../sewpg-bid-backend/app/api/routes/business.py`
- `../sewpg-bid-backend/app/api/routes/business_gaps.py`
- `../sewpg-bid-frontend/src/api/index.js`

历史 FastAPI 迁移方案和旧单线接口不再作为下一阶段开发入口。

后续如果把契约正式收进 `code`，建议优先落到这里，而不是继续散落在前端目录或项目根目录。
