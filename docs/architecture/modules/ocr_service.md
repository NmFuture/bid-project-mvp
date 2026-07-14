# ocr_service

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/ocr_service.py` |
| 层级 | 服务层 |
| 领域 | 解析与AI引擎 |
| 行数 | 421 |

**职责**: OCR 引擎服务：调用外部 OCR 模型（默认 DeepSeek-OCR，配置来自系统设置）识别图片/扫描件，抽取「字段：值」候选，任务与候选落 DB 供人工逐条确认。

## Input（输入）
- `run_ocr(project_id, file_name, content, mime_type, user, audit_metadata)`：图片 bytes（`IMAGE_SUFFIXES`：png/jpg/jpeg/webp/bmp/tif/tiff）。
- OCR 端点/模型从 `system_settings_service` 读（Settings 页可改，`unlimited-ocr` 标记跳过限制）。

## Output（输出）
- OCR 任务与候选记录（`_extract_candidates_from_text` 按「：/:」切字段名≤40字+值）；确认候选后写回项目状态；审计记录。

## 调用链
- **上游**: `bid_ocr_service`（两轨路由入口）、`parsing`（解析中图片兜底）、`material_certificate_time`（证书识别）、`business_wiki_generation`、`technical_wiki_generation`。
- **下游**: DB 表 `OcrTask`/`OcrCandidate`（models.materials，经 async_session）、httpx（OCR API）、`system_settings`、`audit_service`、`workspace_project_access`、`material_runtime_tables`。

## 中间数据与状态
- 表 `ocr_tasks`/`ocr_candidates`（任务状态、候选确认状态）；base64 图片上送。
