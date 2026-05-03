---
name: bid-tech-outline-generator
description: This skill should be used when the user asks to "生成目录", "S1 模板与目录", "技术标目录生成", "根据招标文件和投标模板生成目录", or needs bid outline JSON with tender evidence for review and OnlyOffice jump/highlight.
---

# 技术标目录生成

用于当前 `S1 模板与目录`：根据投标文件模板、招标文件要求和招标附表/副表线索生成可审核目录 JSON。

命令名 `s2toc` 和工作区 `s2_toc_workdir` 是历史内部名，为兼容后端和已有产物保留，不代表当前用户阶段。

## 后端调用

运行一次：

```bash
s2toc <manifest>
```

命令会读取 manifest 中的 `templateFile`、`attachFile`、`tenderFiles[]`、`outputFile`、`evidenceFile`，并写出：

- `outputFile`: `bid-toc-json-v1` 目录 JSON
- `evidenceFile`: `bid-toc-evidence-v1` 候选、依据和决策 JSON
- `agentReviewFile`: 压缩后的 Agent 审核包，不是全量证据
- stdout: 小型 JSON 摘要，包含 `outputFile`、`evidenceFile`、`agentReviewFile` 和 `agentReviewDigest`

## 分工

- 脚本负责确定性抽取：模板目录骨架、招标段落候选、附表/副表候选、初始匹配依据。
- Agent 负责语义审核：判断招标要求是否被模板目录覆盖、哪些依据应绑定到目录项、哪些附表必须追加到目录末尾。
- 不使用素材库，不生成 `material_refs`，不编造招标文件没有写出的要求。
- 优先使用 stdout 的 `agentReviewDigest` 做审核；不要读取全量 `toc_evidence.json`，除非用户明确要求深查。

## 输出要求

最终只返回严格 JSON，不要 Markdown，不要解释文字。优先返回完整目录 JSON；如果不改脚本产物，也可以只返回摘要路径。

完整返回格式：

```json
{
  "schema_version": "bid-toc-json-v1",
  "outputFile": "<outputFile from manifest>",
  "evidenceFile": "<evidenceFile from manifest>",
  "summary": {"total_items": 0},
  "items": []
}
```

如只返回 Agent 判断，使用：

```json
{
  "schema_version": "bid-toc-json-v1",
  "outputFile": "<outputFile from manifest>",
  "evidenceFile": "<evidenceFile from manifest>",
  "agentDecisions": []
}
```

`agentDecisions[]` 可包含 `candidateId`、`targetItemId` 或 `targetTitle`、`decision`、`relation`、`confidence`、`reason`。常用 `decision` 为 `attach_evidence`、`append_item`、`exclude`。

## 依据规则

- 目录主骨架优先来自投标模板。
- 招标附表/副表类目录项放在模板目录之后，不穿插到中间章节。
- 每个来自招标文件的依据都保留 `source_refs[]`，并设置可跳转字段：`fileId`、`fileName`、`path`、`paragraphIndex`、`basisText`、`searchText`。
- `searchText` 尽量使用招标原文片段，保持 OnlyOffice 可以搜索到的原始写法；显示标题可以更规整。
- 无法确定的招标要求写入 evidence/decisions，不强行追加目录项。
