# material_tag_import_fuzzy

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/material_tag_import_fuzzy.py` |
| 层级 | 服务层 |
| 领域 | 素材库 |
| 行数 | 199 |

**职责**: 标签导入的 AI 模糊匹配桥接：把精确匹配剩下的 unmatched 行先用字符 bigram 重合度预筛 Top-K 候选（控制 prompt 体积防超时），再调 Skill `bid-tech-tag-importer` 做语义匹配，产出 fuzzy 预览分区。异常全部上抛，由调用方降级——模糊匹配是兜底增强，绝不阻断确定性匹配。

## Input / Output
- Input: unmatched 行 + 候选文件清单；规模上限：一次 40 行、每行 6 候选、总候选 60；专用超时 180s（big-pickle 冷启动宽裕量）。
- Output: fuzzy 匹配建议（供预览人工确认）。

## 调用链
- **上游**: `technical_material_store._augment_with_fuzzy`（tag-import preview 且 useFuzzy=true）。
- **下游**: opencode Skill `bid-tech-tag-importer`、`material_tags`。

## 中间数据与状态
- 无持久状态；n-gram 预筛纯内存。
