# business_gap_ai_draft

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/business_gap_ai_draft.py` |
| 层级 | 服务层 |
| 领域 | 商务标 |
| 行数 | 93 |

**职责**: 商务标 AI 草拟 docx 的确定性写盘器：按任务标题（承诺函/报价/供货范围类）+ 项目事实表生成规范化响应文件（致招标人、正文、项目名称/招标编号、按标题条件补报价/机型段、落款）。

## Input（输入）
- `write_business_ai_draft_docx(output_path, project, task, facts, data)`：任务标题（去「格式/函格式」后缀归一）、事实表值（招标人/投标人/项目名称/招标编号/投标报价/投标机型等）。

## Output（输出）
- python-docx 生成的响应文件 docx；缺失事实以 `[待填写：xxx]` 占位（可验证、不编造）。

## 调用链
- **上游**: `business_gap_service.ai_draft`。
- **下游**: python-docx；无其他服务依赖。

## 中间数据与状态
- 输出文件由调用方指定路径（gap 产物目录）。
