# business_wiki_generation

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/business_wiki_generation.py` |
| 层级 | 服务层 |
| 领域 | 商务标 |
| 行数 | 1564 |

**职责**: 商务标 Wiki 生成（与技术标三级目录镜像链路完全解耦）：LLM 精修主路径 + 多级确定性回退——opencode wikibuild 产骨架并语义精修 → 失败回退 subprocess 跑 Skill `bid-business-wiki-material-builder` 确定性骨架 → 显式允许时再回退内联确定性蓝图。

## Input（输入）
- `generate_business_wiki(reference_path, mode=create, fallback_to_deterministic)`；素材清单摘要（`_summarize_material_inventory`：DB RawFile + 身份/分类/标签归一）、docx 剖析（`wiki_blueprint_common.extract_docx_profile`，同步上限 `MAX_SYNC_DOCX_BYTES`）、图片走 OCR。

## Output（输出）
- 商务 Wiki 蓝图（节点树）→ 经 `business_material_store` 导入为 Wiki 节点；生成过程含卡片摘录（`MAX_CARD_EXCERPT_PARAGRAPHS` 上限）。

## 调用链
- **上游**: `routes/business.py` `wiki/bootstrap` 端点。
- **下游**: `business_wiki_blueprint`（Skill 蓝图函数桥接）、`wiki_blueprint_common`、`business_material_store`、`opencode_client`、`ocr_service`、`minio_client`、DB `RawFile`、`identity`/`material_taxonomy`/`material_tags`。

## 中间数据与状态
- Wiki 节点表（经 material_store 导入）；临时工作目录；回退层级决定生成质量与耗时。
