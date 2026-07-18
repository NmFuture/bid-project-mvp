# business_template_extractor

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/business_template_extractor.py` |
| 层级 | 服务层 |
| 领域 | 商务标 |
| 行数 | 253 |

**职责**: 商务标模板抽取的 Skill 桥接：构建 manifest（仅收 docx），调用 Skill `bid-business-template-extractor`（schema `bid-business-template-extractor-v1`）从招标文件中抽取投标文件格式模板（受 `BUSINESS_TEMPLATE_EXTRACTOR_ENABLED` 开关控制）。

## Input（输入）
- `build_business_template_extractor_manifest(project_id, documents, output_dir, stage, fallback_mode)`：解析后的 docx 文档清单（sourcePath/textPath）。

## Output（输出）
- 抽取出的模板附表清单（`convert_extractor_appendices` 供 `bid_parse_service` 转换消费）；LLM 阶段超时 300s。

## 调用链
- **上游**: `parsing`、`bid_parse_service`。
- **下游**: Skill `bid-business-template-extractor`（subprocess run_from_manifest.py）、`opencode_client`。

## 中间数据与状态
- manifest 与抽取产物在解析工作目录；schema 版本常量。
