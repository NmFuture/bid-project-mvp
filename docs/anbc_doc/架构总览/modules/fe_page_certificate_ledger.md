# fe_page_certificate_ledger（TechnicalCertificateLedger）

| | |
|---|---|
| 源文件 | `workspaces/technical/pages/TechnicalCertificateLedger.jsx` |
| 层级 | 前端页面 |
| 领域 | 技术标 |
| 行数 | 1170 |

**职责**: 证书台账页 `/workspace/tech/materials/certificates`（技术标特有）：证书素材清单与有效期展示（临期高亮）、单条 AI 识别（recognize）、增量批量扫描、适用范围维护（scopes/suggestions）、条目编辑与批量删除。

## 调用链
- **下游**: `technicalMaterialsAPI` certificates 端点组（← `material_certificate_time`）。

## 中间数据与状态
- 台账过滤与识别进行中状态。
