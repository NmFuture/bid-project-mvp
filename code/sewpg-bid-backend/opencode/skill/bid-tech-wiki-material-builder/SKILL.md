---
name: bid-tech-wiki-material-builder
description: 根据技术标素材清单生成技术标 Wiki 初始化 JSON，面向目录生成和投标正文拼装共读的技术标素材卡片、目录骨架、装配规则、同义词和质量日志。
allowed-tools: [Read, Glob, Grep, Bash, Write, AskUserQuestion]
---

# 技术标 Wiki 素材库制作

你负责把技术标原始素材清单整理成可导入系统的 Wiki JSON。这个 Wiki 是“技术标装配规则库”，不是普通知识百科，也不是文件夹浏览器。

## 使用边界

- 只处理技术标素材，以及明确标为通用的素材。
- 不生成商务标体系，不把报价、授权、资质、合同条款等商务材料混入技术标 rules / skeleton。
- 卡片只承载索引、适用条件、原始 docx 路径、Heading 审计和 Merge 信息；素材正文真源仍是原始 docx。
- Wiki 是给 AI 检索和装配看的规则库，不是人工文件夹。每张卡片必须尽量写清 AI 身份字段，避免客户/项目素材串用。
- 不发明项目事实、机型参数、业绩、金额、证书编号或日期。

## 必须输出

只输出 JSON，不要解释，不要 Markdown 代码块。根节点标题必须是：

```json
"rootTitle": "技术标Wiki（自动生成）"
```

JSON 结构固定：

```json
{
  "summary": "一句简短总结",
  "rootTitle": "技术标Wiki（自动生成）",
  "nodes": [
    {
      "title": "节点标题",
      "markdownContent": "# 标题\n\n正文",
      "tags": ["技术标"],
      "applicableTypes": ["技术标"],
      "children": []
    }
  ]
}
```

## 顶层结构

顶层标题保持稳定：

- 00-Wiki使用说明
- 01-技术标素材速查索引
- 02-技术标目录骨架 skeleton
- 03-技术标装配规则 rules
- 04-技术标同义词 synonyms
- 05-技术标通用卡片
- 06-技术标定制卡片
- 07-技术标质量日志
- 08-共用规则

## 技术标关注点

优先围绕以下材料建索引和卡片：

- 技术方案、总体方案、供货范围
- 风资源、机位、发电量、机组选型
- 风机子系统、关键部件、环境适应性
- 交货、运输、安装、调试、运维
- 技术标准、规范响应、质量保证、验收考核
- 评分点映射、目录归位、缺口提醒

## 节点内容规则

- `01-技术标素材速查索引`：列出真实文件名、原始路径、推荐章节、Heading 摘要和用途。
- `02-技术标目录骨架 skeleton`：写清每类素材应挂到哪个投标章节，保留 `skeleton_section`、merge 层级、shift、attach_mode。
- `03-技术标装配规则 rules`：写必选、条件触发、override、append、reference、exclude 裁决。
- `04-技术标同义词 synonyms`：维护技术关键词和素材标题/章节之间的映射。
- `05/06` 卡片：按素材分类分组，每个真实 docx 至少出现在索引或卡片中。
- `07-技术标质量日志`：列出无 Heading、超大文件、未归位、重名、缺卡片等风险。
- `08-共用规则`：只写字段替换、客户/业主同义词、项目参数映射和通用 merge 关系。

## AI 身份字段

每个素材卡片的 `markdownContent` 中必须包含 `## AI 检索身份` 和 `## Merge 信息`，字段名保持英文小写，便于脚本解析：

- `identity_scope`: `general` / `customer` / `project`
- `material_scope`: 同上，表示素材归属层级
- `bid_type`: 技术标
- `customer_id`: 客户规范 ID，例如 `CUST-HUANENG`
- `customer_name`: 客户标准名，例如 `华能集团`
- `customer_aliases`: 客户同义词，用 `、` 分隔
- `project_id`: 系统项目 ID
- `project_code`: 业务项目编号

规则：通用素材可被所有技术标项目读取；客户素材只在客户 ID 或同义词命中时读取；项目素材只在项目 ID 或业务项目编号命中时读取。

如果没有技术标素材，只生成待补料框架和质量日志提醒，不要虚构卡片。
