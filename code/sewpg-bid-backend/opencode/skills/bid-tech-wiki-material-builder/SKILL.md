---
name: bid-tech-wiki-material-builder
description: 当需要根据技术标三级目录 JSON 索引重建素材 Wiki（用于缺口处理、来源选择或标书组装）时使用
allowed-tools: [Read, Glob, Grep, Bash, Write, AskUserQuestion]
---

# 技术标素材 Wiki 构建器

## 概述

构建一个与技术标三级目录 JSON 索引**一一对应**的 Wiki，让后续 agent 能完全按照素材库的真实存储方式来检索导航。该 Wiki 是面向 AI 的检索与组装索引，不是散文式知识库，也不是文件浏览器的副本。目录结构是唯一事实来源；Wiki 不得臆造索引未表达的分组、映射或规则。

## 适用场景

用于技术标 Wiki 的首次创建或在原始素材变更后重建。当下游任务涉及 S3 缺口处理、为生成的空白表格选择素材来源、或组装技术方案时使用。

不要用于：仅业务标的素材、通用文档摘要、或编造缺失的项目事实。

## 唯一事实来源：技术标三级目录 JSON 索引（必读）

后端自动维护一份技术标三级目录结构索引，**它是本 Wiki 的唯一数据来源**：

- 唯一落盘文件：`{DOCUMENTS_DIR}/_runtime/materials/technical_material_index.json`
- HTTP 只读入口：`GET /api/technical/materials/index`

每次素材目录结构变化（建/删/移目录、上传、拆分、改名、项目 bootstrap）后由后端钩子自动重建。Wiki 构建只消费这份 JSON，不自行从 DB 重新推导结构。结构（`schemaVersion = 2`）：

```
{
  "bidType": "技术标",
  "stats": { "tierCount", "thirdLevelFolderCount", "fileCount" },
  "tiers": [                          // 2 级档位数组，固定 3 档
    {
      "name": "标准文件",             // 2 级目录真实名
      "tier": "standard",            // 归一档位：standard|customer|project
      "path", "fileCount",
      "folders": [                   // 3 级目录（动态）
        {
          "name", "path", "tier",
          "customerName",            // customer 档才有值
          "projectId",               // project 档才有值
          "fileCount", "updatedAt",
          "files": [
            { "id": "RAW-NNNN", "name", "path"(完整), "ext",
              "cleanStatus": "cleaned|pending|original_only|failed" }
          ]
        }
      ]
    }
  ]
}
```

详见 `doc/anbc_doc/20260618-技术标三级目录JSON索引-下游使用Handoff.md`。

### 三个档位语义（以 `tier` 字段为准，勿靠中文名硬判）

| 2 级目录真实名 | `tier` | 含义 | 3 级目录名的含义 |
|---|---|---|---|
| `标准文件` | `standard` | 通用/平台标准素材 | 机型号或分类（如 EW5.0-220） |
| `客户定制` | `customer` | 按客户区分 | 客户名（已回填到 `customerName`） |
| `项目定制` | `project` | 按项目区分 | 项目标识（已回填到 `projectId`） |

已知约束：`description`/`customerId`/`projectCode` 恒为空，不要依赖；需要身份用 `customerName`/`projectId`。深层（4 级及更深）文件归并到其 3 级祖先目录的 `files[]`，但 `file.path` 保留完整原始路径。

## 核心模式：镜像素材库真实层级

Wiki 前三级严格按 JSON **一一映射**；3 级目录内再按 `file.path` 还原素材库的深层子目录：

```
root（技术标Wiki）
  └─ 一级节点 = tier.name   严格使用 JSON tiers[] 顺序和真实 name
       └─ 二级节点 = 3 级目录  机型号 / 客户名 / 项目标识
            └─ 深层子目录……   按 file.path 还原 4 级及更深的原始层级
                 └─ 文件卡片  每个 file 一张，叶子节点
```

- **一级（tier 节点）**：标题使用 JSON 的 `tier.name`，正文给出 tier 代码、真实 name、path、fileCount、3 级目录语义，并用一张表列出本档所有 3 级目录（目录名 / 身份 / 文件数）。
- **二级（3 级目录节点）**：标题为目录真实名，正文给出目录 path、档位、身份（customerName / projectId）、fileCount、updatedAt，并用一张表列出全量文件清单（material_id / 文件名 / 相对路径 / 扩展名 / 清洗状态）。
- **深层子目录节点**：索引把深层文件归并进 3 级目录的 `files[]`，构建时按每个文件 `path` 相对 3 级目录的中间段重建子目录节点，层级与素材库完全一致；正文给出目录路径、直属文件清单和子目录数。
- **文件卡片（叶子）**：标题为文件名，挂在其真实所属目录下；正文给出 material_id、完整路径、扩展名、清洗状态、所属档位与目录、身份字段。卡片只是结构索引，不承载正文。

身份信息写入 `tags`：tier 节点带档位中文名；customer/project 目录节点把 `customerName`/`projectId` 加入 tags，便于下游按身份过滤。

## 构建步骤

1. 取索引：使用传入的 `technical_material_index.json` 或后端唯一落盘文件。不要在 Wiki 构建阶段重建索引。JSON 不存在或无效时应显式失败；`tiers` 为空时可产出空但结构合法的 blueprint，并在 summary 中标注无素材。
2. 跑构建脚本：`python3 scripts/run_from_manifest.py <index.json>`。脚本接受原始 index JSON，或包裹了它的 manifest（`materialIndex` / `technicalMaterialIndex` / `index` 键）。
3. 脚本输出 `wiki_blueprint.json`（`schema_version = bid-wiki-blueprint-v2`），含 `summary` / `rootTitle` / `nodes`，可直接交给 Wiki import。

## 输出契约

仅输出 JSON（脚本已保证此格式，无需手写）。结构如下：

```json
{
  "summary": "简短结果摘要",
  "rootTitle": "技术标Wiki（自动生成）",
  "nodes": [
    {
      "title": "标准文件",
      "markdownContent": "# 标准文件\n\n...",
      "tags": ["技术标", "标准文件", "档位"],
      "applicableTypes": ["技术标"],
      "children": [ /* 二级目录节点，其下再嵌三级文件卡片 */ ]
    }
  ]
}
```

一级节点严格对应 JSON `tiers[]`，不加序号、不重排、不改名。不要再生成旧版的 `01-素材总表`/`02-章节映射表`/`03-素材卡片`/`04-待填写清单`/`05-使用规则` 聚合结构——新架构以目录树为骨架，映射与规则由下游消费时按目录身份处理。

## 质量准则

- 严格镜像索引：节点的存在、归属、身份、文件数、数组顺序必须与 JSON 一致，不增删、不重排；深层子目录只能来自 `file.path` 的真实中间段，不得臆造。
- 判档只看 `tier` 字段，不靠目录中文名。
- 不编造文件名、路径、客户/项目身份、参数、日期、保证值或业绩事实。
- `description`/`customerId`/`projectCode` 恒空，不要在卡片里臆造其值。
- 文件卡片保留完整 `path`，深层层级信息不得丢失。
- 索引为空时仍输出结构合法的 blueprint，并在 summary 标注。

## 文件卡片内容边界

技术标 Wiki 文件卡片默认承载目录索引信息：文件定位、所属档位、3 级目录身份和结构说明。
若输入索引的文件节点带有 `preview` 字段，应在文件卡片渲染“内容预览”区；不得在 runner 内自行生成或臆造预览。
