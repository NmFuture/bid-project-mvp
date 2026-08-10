---
name: bid-tech-score-index-xref
description: 当需要给技术标成稿的「技术评分标准索引表」章节索引列建立可点击跳转和自动页码，或该列为空需要先判断应索引哪些章节时使用。
allowed-tools: [Read, Write, Glob, Grep, Bash]
---

# 技术标评分索引表交叉引用

给技术标成稿里「技术评分标准索引表」的**章节索引列**建立 Word 原生交叉引用：

```
5.1 投标总体方案概述，P213
└──── 可点击跳转 ────┘  └ PAGEREF 域，F9 自动刷新
```

用书签 + 内部超链接 + PAGEREF 域实现，页码不写死。后续章节增删、页码变动，全选按 F9 即可刷新。

阶段位置见 `../STAGES.md`：本 skill 属成稿后处理，跑在 `bid-tech-assembler`（正文组装）和 `bid-tech-format-cleaner`（格式清洗）之后。跑在格式清洗之后是必需的——清洗会重排标题样式与文本编号，先建引用会让书签挂在被改写的段落上。

## 输入

manifest 字段：

- `inputFile`：格式清洗后的技术标 `.docx`。
- `outputFile`：带交叉引用的 `.docx` 输出路径，不能与 `inputFile` 相同。
- `mappingFile` / `mapping`：可选。章节索引列为空时提供 `{评审因素: [章节号或标题]}`，见下文「章节判断方法」。
- `indexHeaders` / `factorHeaders`：可选。覆盖表头识别措辞，默认见 `scripts/xref.py` 顶部常量。
- `syncTitle`：可选，默认 false。true 时用正文真实标题覆盖索引表原有文字。
- `styledLink`：可选，默认 false。true 时超链接用蓝色下划线样式。
- `overwrite`：可选，默认 false。true 时连已有内容的单元格一起按映射重写。
- `updateFieldsWithWord`：可选，默认 false。仅 Windows + pywin32 有效，后端容器里必须保持 false。

## 执行命令

```bash
python scripts/run_from_manifest.py <manifest> --response summary
```

输出 JSON，schema 固定为 `bid-tech-score-index-xref-v1`，含 `status`、`inputFile`、`outputFile`、`summary`、`warnings`。
`status=skipped` 表示文档里没有可识别的评分索引表（或映射解析失败），此时 `outputFile` 为空串，调用方沿用上一环节的成稿，不算失败。

也可直接用命令行三个子命令（人工排查、单文件处理时用）：

```bash
python scripts/xref.py inspect "投标文件.docx"                       # 导出 _结构.txt 和 _索引表.txt
python scripts/xref.py build   "投标文件.docx" --mapping m.json --dry-run
python scripts/xref.py build   "投标文件.docx" --mapping m.json --no-word
python scripts/xref.py verify  "投标文件_交叉索引.docx"
```

`--no-word` 跳过调 Word 算页码。装了 pywin32 的 Windows 机器才能自动算，否则成品页码是占位符，需在 Word 里 Ctrl+A 后按 F9。成稿此时已完整（书签、超链接、PAGEREF 域齐备），交付时要如实说明这一步由谁完成，不要把"待 F9"说成"已完成"。

## 行为规则

- 只改索引表的章节索引列和被引用标题上的书签，不改正文内容、不重排章节。
- 只索引本文件内真实存在的章节；跨卷附表（如技术附表 B/C/D）默认不引，除非用户明确要求。
- 幂等：重跑会复用已有 `_Xref_` 书签、剥掉旧的"，P123"尾巴，不会累加。
- 索引列已填 → 直接建引用；为空且未给映射 → 报 `xref_no_entry` 警告，不猜。
- 索引表文字与正文标题不一致时按章节号建立引用，并报 `xref_title_mismatch` 让人核对。
- 定位不到的条目保持原样，报 `xref_unresolved_entry`，绝不静默丢弃。

## 章节判断方法（仅当索引列为空）

三个输入：**评审因素**（要考什么）、**投标响应**（承诺了什么）、**标题树**（文件里有什么）。目标是让评委顺着索引最快找到证据。
先跑 `inspect` 导出 `_结构.txt` 与 `_索引表.txt`，读完再写映射 JSON（**只写章节号**，标题由脚本从正文补全，避免手抄出错）：

```json
{
  "_注释": "下划线开头的键会被忽略",
  "风轮系统先进性及可靠性": ["5.3.3", "5.7", "5.8.1", "5.8.2", "5.8.15", "5.9.4"],
  "保证年等效满负荷小时数": ["第3章", "附表2", "4.1", "5.1.2", "5.5", "6.4.1"]
}
```

键 = 评审因素原文（空白/标点差异不影响匹配）。值可写章节号（`5.8.1`、`第3章`）或无编号标题的前缀（`附表2`）。任一条解析不到，脚本整体报错，不会带着错号往下走。

同一项目的多个标包若结构相同，可用 `xref.py build --from-reference 已填好的.docx` 直接套用。**不同项目之间不要套用**，章节号一定会变。

判断细则、风电系统归属速查表和常见陷阱见 `references/section_mapping.md`。
