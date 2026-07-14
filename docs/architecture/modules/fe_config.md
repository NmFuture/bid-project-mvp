# fe_config

| | |
|---|---|
| 源文件 | `code/sewpg-bid-frontend/src/config/{env.js, onlyoffice.js}` |
| 层级 | 前端逻辑 |
| 领域 | 共享 |
| 行数 | ~180 |

**职责**: 环境配置收口（`ENV`：API_BASE_URL 默认 /api、超时/重试/trace 开关、OnlyOffice 服务地址默认 /ds）与 OnlyOffice 编辑器配置工厂（脚本按需加载、documentKey/fileUrl/callbackUrl 组装、按扩展名选 documentType、搜索插件 GUID）。

## 调用链
- **上游**: `fe_api`、`OnlyOfficeEmbed/Workspace` 组件。
- **下游**: Vite `import.meta.env`（构建期注入，见 docker-compose web 构建参数）。

## 中间数据与状态
- window.DocsAPI 脚本单例加载。
