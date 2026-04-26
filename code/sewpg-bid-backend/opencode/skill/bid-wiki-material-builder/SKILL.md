---
name: bid-wiki-material-builder
description: 根据投标素材库中的 docx 原件初始化、补齐和维护 LLM Wiki，包括 wiki/index.md、rules.md、synonyms.md、skeleton.md、卡片 frontmatter、Merge 信息、素材 Heading 审计和一致性检查。用于“从素材库制作 wiki”“补料入库生成卡片”“维护投标资料库 wiki”“把技术标素材变成 LLM Wiki”。
allowed-tools: [Read, Glob, Grep, Bash, Write, AskUserQuestion]
---

# 投标素材库 LLM Wiki 制作

你负责把“投标资料库-通用 / 投标资料库-定制”中的 `.docx` 素材转成可供标书拼装使用的 LLM Wiki。

本 skill 只做 Wiki 初始化和维护，不直接生成最终投标文件。最终拼装交给目录生成 / bid assembler 类 skill。

平台 Wiki 必须是“投标文件装配规则库”，不是素材文件夹浏览器。生成时应先按标类分流，再在各标类下维护独立的索引、骨架、规则、同义词和卡片。

## 输入

调用时优先让用户给出素材库根目录。目录通常长这样：

```text
素材库根目录/
  投标资料库-通用/
  投标资料库-定制/
  wiki/                         # 没有则创建
```

如果用户只给了 `wiki/` 目录，向上一级推断素材库根目录。

## 输出

在素材库根目录下生成或维护文件系统版 Wiki：

```text
wiki/
  CLAUDE.md
  index.md
  rules.md
  skeleton.md
  synonyms.md
  log.md
  scripts/
  卡片/
```

其中：

- `index.md` 是素材速查入口。
- `rules.md` 是业务裁决真源。
- `skeleton.md` 是目录归位和 merge 层级真源。
- `synonyms.md` 是关键词检索映射。
- `卡片/**/*.md` 只承载元数据和 merge 信息，不承载 docx 正文全文。
- 素材正文唯一入口是卡片 frontmatter 的 `path` 字段。

在平台接口中导入数据库 Wiki 时，顶层结构应为：

```text
平台级Wiki
  00-Wiki使用说明
  01-技术标体系
    技术标素材速查索引
    技术标目录骨架 skeleton
    技术标装配规则 rules
    技术标同义词 synonyms
    技术标通用卡片
    技术标定制卡片
  02-商务标体系
    商务标素材速查索引
    商务标目录骨架 skeleton
    商务标装配规则 rules
    商务标同义词 synonyms
    商务标通用卡片
    商务标定制卡片
  03-共用规则
    字段替换表
    客户/业主同义词
    项目参数映射
    override / append / reference 规则
  04-质量审计
    缺卡片
    孤儿卡片
    Heading异常
    超大文件待后台解析
    未归位素材
```

## 快速流程

1. 定位素材库根目录和 `wiki/`。
2. 若是首次初始化，运行：

```bash
python3 scripts/bootstrap_wiki.py <素材库根目录>
```

3. 若用户希望直接带入本 skill 附带的示例卡片，追加：

```bash
python3 scripts/bootstrap_wiki.py <素材库根目录> --seed-template-cards
```

4. 维护 `skeleton.md`：把每份素材挂到正确章节，写清 `merge 素材`、骨架层级、shift、备注。
5. 运行 Heading 审计：

```bash
python3 wiki/scripts/extract_headings.py --audit
```

6. 对齐 `skeleton.md` 中的 Heading 树：

```bash
python3 wiki/scripts/extract_headings.py --regen-skeleton
```

7. 把 `skeleton.md` 的 merge 信息回填到卡片：

```bash
python3 wiki/scripts/parse_skeleton.py
```

8. 终检：

```bash
python3 wiki/scripts/check.py
```

如果检查失败，不要自动删除素材或卡片；根据报告逐项修正 `path`、卡片、index 或 skeleton。

## 制作规则

### 内容真源

- 素材内容真源是 `.docx` 原件，不是 markdown 卡片。
- 目录归位真源是 `skeleton.md`。
- 条件触发、剔除、覆盖、叠加、附加的真源是 `rules.md`。
- 同义词和模糊匹配真源是 `synonyms.md`。

### 卡片规则

每份素材必须有一张卡片。卡片名等于素材文件名去扩展名。

```text
技术标-发电机专题.docx -> 技术标-发电机专题.md
主轴强度复核报告（北区）.docx -> 主轴强度复核报告（北区）.md
```

卡片路径：

```text
卡片/通用/{标前概述|投标函件|总体方案|设备全周期|专项技术|风资源评估|风机子系统|环境适应性|技术标准|交付验收}/
卡片/定制/项目数据/
```

新增卡片时使用 [references/card_template.md](references/card_template.md)。

### 素材格式

- 新素材只允许 `.docx` 进入主素材库。
- PDF / xlsx 需要先转为 docx；原文件进 archive，不作为卡片 `path`。
- 卡片 `path` 必须指向相对素材库根目录的 `.docx`。

### 检索顺序

目录条目找素材时：

1. 先用 `skeleton.md` 的 fixed 映射。
2. 再用 `index.md` 主关键词。
3. 再用 `synonyms.md` 扩展。
4. 最后才用语义兜底。
5. 仍不确定时标 `UNMATCHED` 或 `NEEDS_REVIEW`，不要硬塞。

## 在平台接口中使用

当 FastAPI 通过“创建Wiki”调用本 skill 时，必须输出可导入系统 Wiki 树的 JSON，不要输出解释或 Markdown 代码块。JSON 结构固定为：

```json
{
  "summary": "一句简短总结",
  "rootTitle": "平台级Wiki（自动生成）",
  "nodes": [
    {
      "title": "节点标题",
      "markdownContent": "# 标题\n\n正文",
      "tags": ["通用材料"],
      "applicableTypes": ["通用"],
      "children": []
    }
  ]
}
```

平台级 Wiki 顶层至少包含：

- 00-Wiki使用说明
- 01-技术标体系
- 02-商务标体系
- 03-共用规则
- 04-质量审计

技术标和商务标必须分别维护自己的 `index / skeleton / rules / synonyms / 通用卡片 / 定制卡片`。不能把商务标素材混入技术标 skeleton，也不能把技术标素材混入商务标 rules。

当某一标类暂时没有素材时，不要虚构卡片；只生成标准分类框架和待补料说明。

## 参考资料

- 详细规则摘要：读 [references/wiki_material_rules.md](references/wiki_material_rules.md)
- 卡片模板：读 [references/card_template.md](references/card_template.md)

## 常见修正

- `check.py` 报“缺卡片”：为对应 docx 建卡片，并更新 `index.md`。
- `check.py` 报“孤儿卡片”：先确认素材是否被移动或改名；优先修正卡片 `path`。
- `index.md` 缺条目：重新运行 `bootstrap_wiki.py` 或手工补表格行。
- Heading 层级不对：先修 docx Heading 样式，再跑 `extract_headings.py --regen-skeleton` 和 `parse_skeleton.py`。
- 素材该不该进本项目：在 `rules.md` 写必选 / 条件触发 / 剔除 / 覆盖 / 叠加 / 附加，不写进卡片正文。
