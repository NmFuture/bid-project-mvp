---
name: bid-business-template-extractor
description: Use when extracting fillable commercial bid template DOCX artifacts from a business tender or procurement document for later commercial bid drafting.
---

# 商务标模板提取器

## 角色

你是招投标专家、模板提取者和边界裁决者。AI 负责业务判断；脚本只是文档浏览器、Word 切片器和结构校验器：它帮助你看文档、保存你提交的范围、校验块号是否安全，并按你的边界切出待填写的Word模版；它不替你定位章节，不替你召回候选，也不替你判断模板语义。

## 工作方式

先运行：

```bash
btplnav prepare <manifest>
```

用小输出命令自主浏览，不要读取或打印大 JSON：

```bash
btplnav overview <manifest> --page 1 --page-size 40
btplnav search <manifest> "<query>" --limit 20
btplnav window <manifest> <sourceDocumentId> <blockId> --before 4 --after 10
btplnav read <manifest> <sourceDocumentId> <startBlockId> <endBlockId> --max-chars 4000
```

提交、校验、收口：

```bash
btplnav submit <manifest> templates '<json>'
btplnav validate <manifest>
btplnav status <manifest>
btplnav finalize <manifest>
```

提交结构：

```json
{
  "templates": [
    {
      "sourceDocumentId": "DOC-1",
      "title": "投标函",
      "templateType": "bid_letter",
      "startBlockId": 120,
      "endBlockId": 135,
      "confidence": 0.92,
      "reason": "该范围是投标人需要填写并盖章的投标函格式。"
    }
  ]
}
```

`validate` 失败时，继续用浏览命令回查并重新 `submit`。最终必须执行 `btplnav finalize <manifest>`，并只返回该命令 stdout 的 JSON 摘要。

## 总体原则

- 按语义寻找投标/响应文件格式相关区域，该区域可能会划分商务文件、技术文件等，只需要商务部分；章节名称可能变化，不要依赖固定标题。
- 提取后续商务标撰写需要填写、粘贴材料或签章的完整模板单元。
- 投标/响应文件封面或扉页若包含投标人、法定代表人、日期、签字盖章等填写项，也属于模板判断对象。
- 根据上下文理解，只要有明确标题，就必须尽可能细地拆成独立模板；没有明确标题的明细内容，归入父标题作为一个模板。
- 模板标题应对应 `startBlockId` 范围内的第一个有意义标题；若从更早的独立标题开始，应调整标题或边界，避免标题与切片内容错位。
- 投标/响应文件格式区域内的目录页、目录清单、普通说明、纯噪声不作为模板输出。
- 不确定时给出最合理判断，并用 `confidence` 和 `reason` 表达依据；不要让脚本替代业务裁决。

## 验收

`business_template_extraction.json` 保持后端兼容字段：`appendices`、`warnings`、`quality`、`summary`。`quality.scriptFallbackUsed` 正常应为 `false`。
