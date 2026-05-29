---
name: bid-tech-format-cleaner
description: 当用户要求清洗已成稿技术标 Word 格式、根据技术标目录提升标题样式、插入目录、统一页眉或清理技术标正文样式时使用。
---

# 技术标成稿 Word 格式清洗

本 skill 只处理已经成稿的技术标 `.docx`。它根据 S2/S5 准备好的技术标目录 JSON 定位标题，统一 Word 标题、目录、页眉、页面方向和正文基础格式。

## 输入

manifest 必须包含：

- `inputFile`：待清洗技术标 `.docx`。
- `outlineFile`：技术标目录 JSON，支持 `sections/children` 或后端转换后的技术标 outline。
- `outputFile`：清洗后 `.docx` 输出路径，不能与 `inputFile` 相同。
- `projectName`：项目名称，用于页眉。
- `styleSpecPath`：可选。后端默认传入 `bid-tech-assembler/references/heading_style.json`。

## 执行命令

```bash
python scripts/run_from_manifest.py <manifest> --response summary
```

`--response summary` 输出 JSON，schema 固定为 `bid-tech-format-clean-v1`，包含 `inputFile`、`outlineFile`、`outputFile`、`reportFile` 和 `summary`。

## 行为规则

- 先复制 `inputFile` 到 `outputFile`，只改输出文件。
- 读取目录中的章节标题，按目录顺序匹配 Word 段落。
- 匹配成功后设置 `Heading 1-4`，并清除标题段落残留编号属性。
- 对正文内部疑似三级/四级小标题做保守提升。
- 插入自动目录域；Word/WPS 打开后需要刷新域才能显示最终页码。
- 统一技术标页眉文本、标题字体、正文基础格式和页面方向。
- 保留正文内容、图片、表格和已有横版 section，不重排章节。
- 对未匹配标题、占位符、目录和格式风险生成报告。

## 输出报告

脚本会在 `outputFile` 同目录生成 `tech_format_clean_report.md`，记录：

- outline 总数。
- 成功匹配标题数。
- 未匹配标题清单。
- 正文内部提升标题数。
- TOC 是否插入/存在。
- 页眉是否清理。
- 页面方向统计。
- 格式风险提示。

## 常见风险

- 目录页码需要在 Word/WPS 中刷新域。
- outline 中有标题但正文中没有对应段落时，脚本不会补章，只在报告列出未匹配标题。
- 正文中如果有大量与标题相似的短句，内部小标题提升需要人工抽检。
