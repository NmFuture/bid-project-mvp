# material_certificate_time

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_certificate_time.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 675 |

**职责**: 证书有效期台账引擎（技术标证书台账页的实现）：识别证书类素材（关键词：证书/认证/型式/检测/CNAS/CQC/CE/IEC 等），从 pdf/docx/图片抽取「发证日期/有效期至」类日期（正则 + OCR 兜底），台账登记与适用范围维护，支持批量与增量扫描。

## Input（输入）
- 素材文件（`SUPPORTED_SUFFIXES`={pdf,docx,图片}）；日期抽取：`FIELD_DATE_RE`（标签:日期）+ `DATE_TOKEN_RE`；范围配置 JSON（`technical_certificate_time_config.json`，documents 卷 `_runtime/materials/`）。

## Output（输出）
- 台账记录（挂素材 ext 字段）：发证/到期日期、识别候选、确认状态；范围建议 `suggest_certificate_time_scopes`；批量/增量运行结果。

## 调用链
- **上游**: `technical_material_store`（证书台账全部端点）。
- **下游**: `parsing.extract_docx_text/extract_pdf_text`、`ocr_service`（图片/扫描件）、`minio_client`、DB `raw_files/raw_folders`、`bid_runtime_state`（配置原子读写）。

## 中间数据与状态
- 范围配置 JSON 文件；素材 ext 内证书时间字段；证书关键词与日期正则常量。
