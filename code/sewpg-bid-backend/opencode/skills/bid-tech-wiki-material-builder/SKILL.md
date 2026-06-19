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

- HTTP（推荐，保证最新）：`GET /api/technical/materials/index`
- 容器内文件：`{DOCUMENTS_DIR}/_runtime/materials/technical_material_index.json`

每次素材目录结构变化（建/删/移目录、上传、拆分、改名、项目 bootstrap）后由后端钩子自动重建。结构（`schemaVersion = 1`）：

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

## 核心模式：镜像三级结构

Wiki 结构严格按 JSON 三级**一一映射**，不增减层级：

```
root（技术标Wiki）
  └─ 一级节点 = tier        01-标准文件 / 02-客户定制 / 03-项目定制（固定顺序）
       └─ 二级节点 = 3 级目录  机型号 / 客户名 / 项目标识
            └─ 三级节点 = 文件卡片  每个 file 一张，叶子节点
```

- **一级（tier 节点）**：标题 `NN-{档位中文名}`，正文给出 tier 代码、真实 name、path、fileCount、3 级目录语义，并用一张表列出本档所有 3 级目录（目录名 / 身份 / 文件数）。
- **二级（3 级目录节点）**：标题为目录真实名，正文给出目录 path、档位、身份（customerName / projectId）、fileCount、updatedAt，并用一张表列出文件清单（material_id / 文件名 / 扩展名 / 清洗状态）。
- **三级（文件卡片）**：标题为文件名，正文给出 material_id、完整路径、扩展名、清洗状态、所属档位与目录、身份字段。卡片只是结构索引，不承载正文；深层层级靠完整路径还原。

身份信息写入 `tags`：tier 节点带档位中文名；customer/project 目录节点把 `customerName`/`projectId` 加入 tags，便于下游按身份过滤。

## 构建步骤

1. 取索引：优先 `GET /api/technical/materials/index`（保证最新）；否则读容器内 `technical_material_index.json`。JSON 不存在或 `tiers` 为空时，产出空但结构合法的 blueprint，并在 summary 中标注无素材。
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
      "title": "01-标准文件",
      "markdownContent": "# 标准文件\n\n...",
      "tags": ["技术标", "标准文件", "档位"],
      "applicableTypes": ["技术标"],
      "children": [ /* 二级目录节点，其下再嵌三级文件卡片 */ ]
    }
  ]
}
```

一级节点固定为按档位的 `01-标准文件` / `02-客户定制` / `03-项目定制`（仅出现索引中存在的档位，顺序固定 standard→customer→project）。不要再生成旧版的 `01-素材总表`/`02-章节映射表`/`03-素材卡片`/`04-待填写清单`/`05-使用规则` 聚合结构——新架构以目录树为骨架，映射与规则由下游消费时按目录身份处理。

## 质量准则

- 严格镜像索引：节点的存在、归属、身份、文件数必须与 JSON 一致，不增删、不重排（档位顺序除外，固定 standard→customer→project）。
- 判档只看 `tier` 字段，不靠目录中文名。
- 不编造文件名、路径、客户/项目身份、参数、日期、保证值或业绩事实。
- `description`/`customerId`/`projectCode` 恒空，不要在卡片里臆造其值。
- 文件卡片保留完整 `path`，深层层级信息不得丢失。
- 索引为空时仍输出结构合法的 blueprint，并在 summary 标注。

## 文件卡片 AI 内容预览（preview）

镜像脚本只负责把三级目录镜像成 Wiki 树「骨架」（确定性、不调 LLM）。文件卡片上那张
**AI 内容预览**（一句话导读 + 要点 + 关键参数 + 检索关键词）是另一条线，由 LLM 生成。

本 skill 把预览的 **prompt 模板 / 输出 schema / 回复解析**沉淀在
`scripts/technical_wiki_preview.py`（纯 stdlib，零 `app.*` 依赖），由后端经
`app/services/technical_wiki_preview_prompt.py` 用 importlib 桥接 import 复用 —— 后端
不再裸写 prompt。导出：

- `PREVIEW_SCHEMA_VERSION`：预览缓存结构版本；prompt 或 preview 字段结构变化时升此版本，
  让所有文件缓存指纹失效、触发重算。
- `PREVIEW_BATCH_SIZE`：批量合并粒度（一次 LLM 调用喂多少份文件摘要）。
- `build_preview_prompt(name, path, tier_label, profile)` / `parse_preview_reply(reply, json_loader)`：单文件版（fallback / BATCH_SIZE=1）。
- `build_batch_preview_prompt(items)` / `parse_batch_preview_reply(reply, json_loader)`：批量版。

单张预览对象 schema：
```json
{"lead":"一句话导读 ≤80字","points":["3-5条要点"],"keyParams":[{"label":"","value":""}],"retrievalHints":["2-6个检索词"]}
```
批量回复 schema（按 fileId 回填）：
```json
{"previews":{"RAW-XXXX":<预览对象>, "RAW-YYYY":<预览对象>}}
```

约定：**后端发请求、控制缓存与并发**，本模块只提供「怎么问、怎么读」；预览**不挂 opencode
agent 逐文件编排**（几百文件起 agent 开销过大）。JSON 解析用依赖注入（后端把
`OpencodeClient._parse_json_payload` 作为 `json_loader` 传入），保持本模块独立。
减压两招：批量合并请求（请求数从「文件数」降到「文件数/BATCH」）+ per-file 指纹增量缓存
（内容/文件名/版本不变不重算，failed 下次重试）。
