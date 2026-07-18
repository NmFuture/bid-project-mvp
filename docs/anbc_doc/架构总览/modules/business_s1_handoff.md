# business_s1_handoff

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/business_s1_handoff.py` |
| 层级 | 服务层 |
| 领域 | 商务标 |
| 行数 | 103 |

**职责**: 商务标 S1 阶段交接件契约的消费端：读取 `project.stageArtifacts.s1`，校验 `status=published` 才允许 S3/AI 填写正式消费；未发布则抛错，无交接件时回退 legacy parse_result。

## Input / Output
- Input: 项目 dict（stageArtifacts.s1，schema `business-s1-handoff-v1`）。
- Output: `business_s1_consumption_context(project)` → `{source: s1_handoff|legacy_parse_result, handoff, paths, structuredResultPath, parseResult}`。

## 调用链
- **上游**: `business_gap_service`（缺口检测的输入契约）。
- **下游**: `bid_type`。

## 中间数据与状态
- `stageArtifacts.s1.status`（published 才可消费）；这是 README 所述「S1 阶段交接件契约」在代码里的落点，也是与 pwf（S1 侧）的协作边界。
