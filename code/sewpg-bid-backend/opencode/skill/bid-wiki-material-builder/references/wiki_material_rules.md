# LLM Wiki 素材库规则摘要

## 三层加载

- L1 必读：`CLAUDE.md`、`index.md`、`rules.md`、`synonyms.md`、`skeleton.md`
- L2 按需：命中的 `卡片/**/*.md`
- L3 拼装才访问：卡片 `path` 指向的 `.docx` 原件

## Wiki 职责

Wiki 负责把投标目录条目映射到素材，不负责保存正文全文，也不负责最终 docx 合并。

标准链路：

1. 外部解析招标 / 投标模板，得到项目参数和目录。
2. 读 `skeleton.md` 得固定骨架和 merge 层级。
3. 读 `rules.md` 做必选、条件触发、剔除、覆盖、叠加、附加。
4. 读卡片确认 `path`、`shift`、`attach_mode`、可替换字段。
5. 输出 assembly plan 或供拼装器消费的结构化清单。

## 文件职责

| 文件 | 作用 |
|---|---|
| `index.md` | 素材速查入口，主关键词第一匹配点 |
| `rules.md` | 跨素材业务规则 |
| `synonyms.md` | 同义词扩展 |
| `skeleton.md` | 最终目录骨架、章节归位、merge 层级 |
| `log.md` | 素材库维护日志 |
| `卡片/**/*.md` | 单素材元数据 |

## frontmatter 必备字段

```yaml
name: <素材名>
path: <相对素材库根目录的 docx 路径>
scope: 通用 | 定制
category: <分类>
deprecated: false
skeleton_section: "<章节号，未知填 未明确>"
skeleton_level: L0 | L1 | L2 | L3 | L_attach | unknown
material_level_range: <Lx-Ly | none>
heading_count: <数字>
shift: <整数>
attach_mode: normal | cover | table_attach | tbd
```

## 通用和定制的关系

- 覆盖：只用定制版，通用版不进计划。
- 叠加：通用和定制都进计划，通常定制在前。
- 附加：定制作为附件或补充，跟在通用专题后。

这些关系必须写在 `rules.md`，不要靠文件名猜。

## 维护顺序

新增或改名素材后：

1. 放入对应素材库目录，确保是 `.docx`。
2. 建或改卡片，更新卡片 `path`。
3. 更新 `index.md`。
4. 如涉及章节归位，更新 `skeleton.md`。
5. 如涉及条件、剔除、覆盖、叠加、附加，更新 `rules.md`。
6. 如涉及叫法变化，更新 `synonyms.md`。
7. 跑 `extract_headings.py --audit`。
8. 跑 `extract_headings.py --regen-skeleton`。
9. 跑 `parse_skeleton.py`。
10. 跑 `check.py`。
