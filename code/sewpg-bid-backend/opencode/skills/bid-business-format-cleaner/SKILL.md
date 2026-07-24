---
name: bid-business-format-cleaner
description: 当用户要求清洗已成稿商务标 Word 格式、根据 S2 审核后的 business_bid_outline.v1 outline.json 提升标题样式、插入目录、统一页眉或清理商务标空白页时使用。
---

# 商务标成稿 Word 格式清洗

本 skill 只处理已经成稿的商务标 `.docx`，根据 S2 审核后的 `outline.json` 定位标题并统一 Word 格式。它不接入 bid-project-mvp 后端，不修改技术标流程、技术标素材库、技术标 Skill、技术标页面、技术标 API、技术标测试或技术标文档。

## 输入

manifest 必须包含：

- `inputFile`：待清洗商务标 `.docx`。
- `outlineFile`：S2 审核后的 `business_bid_outline.v1` outline JSON。
- `outputFile`：清洗后 `.docx` 输出路径，不能与 `inputFile` 相同。
- `projectName`：项目名称，用于页眉。
- `styleSpecPath`：可选，默认 `references/business_heading_style.json`。

## 执行命令

```bash
python scripts/run_from_manifest.py examples/minimal_manifest.json --response summary
```

在 Windows PowerShell 中可使用：

```powershell
python .\scripts\run_from_manifest.py .\examples\minimal_manifest.json --response summary
```

`--response summary` 输出 JSON，schema 固定为 `bid-business-format-clean-v1`，包含 `inputFile`、`outlineFile`、`outputFile`、`reportFile` 和 `summary`。

## 行为规则

- 先复制 `inputFile` 到 `outputFile`，只改输出文件。
- 递归读取 `sections/children`，扁平化 `id/title/number/level`。
- 按 outline 顺序扫描 Word 段落，优先匹配 `number + title`，再匹配纯 `title`。
- 匹配成功后设置 `Heading {level}`，标题文本规范为 `{number} {title}` 或 `title`。
- 清除标题段落残留 `w:numPr`，采用文本编号。
- 缺失标题不插入、不删除正文，只写入报告。
- 清洗正文、表格、TOC 和页眉；保留正文内容、图片、表格和横竖版 section，不重排章节。
- 插入自动目录时，在 TOC 域前插入 `目 录` 标题；若文档存在封面分页符，目录插入在封面之后、商务评分索引表之前。
- 目录结束处使用独立竖版下一页分节符，避免目录页继承后续商务评分索引表的横版 section。
- TOC 取 1-4 级，条目的缩进、点引导制表位和行距参考 `references/business_toc_style.json`。
- 运行 `scripts/pagination_cleaner.py` 清理多余空白页，并在每个有正文的小节正文结束后补齐分页符；正文可以是段落、图片或表格。
- 父标题后若直接进入子标题且没有正文，不在父标题后加分页符；若正文后已有分页符，不重复增加。
- 分页清理会把 `bookmarkStart/bookmarkEnd`、批注范围、修订范围、权限范围和校对标记等无版面 OOXML 节点视为透明节点，不因这些节点重复补分页符。
- 若小节末尾已经存在边界分页符，同一小节正文内部的其它纯分页符会被视为多余空白页来源并清理；边界分页符可位于最后一个正文/图片段落内部。
- 若下一标题段落开头自带分页符，且上一小节末尾已经有边界分页符，则移除标题段落开头的重复分页符。
- 分页清理有 `outline.json` 时优先按 outline 标题文本定位边界，不依赖 Word 本地化或数字化后的标题样式 ID。

## 格式配置

页面、标题、正文、表格、页眉模板和风险残留词从 `references/business_heading_style.json` 读取。自动目录的标题、TOC 域、条目缩进、点引导制表位和行距从 `references/business_toc_style.json` 读取，并由 `business_heading_style.json` 的 `toc.style_spec_path` 引用。目录格式按参考文档真实自动目录页设置：标题 `目 录`、TOC 域 `TOC \o "1-4" \h \z \u`、TOC 1/2/3/4 左缩进 0/420/840/1260 twips、右侧点引导制表位 9060 twips、1.5 倍行距。业务说明见 `references/business_style_spec.md`。

v1 沿用现有技术标页面、标题、正文和表格格式规则；页眉模板改为：

```text
{projectName}投标文件-商务部分
```

## 输出报告

`verify.py` 会在 `outputFile` 同目录生成 `business_format_clean_report.md`，记录：

- outline 总数。
- 成功匹配标题数。
- 未匹配标题清单。
- TOC 是否插入。
- 页眉是否清理。
- 新增小节分页符数、清理多余分页符数、清理分页间空段数。
- 格式风险提示。

## 最小 manifest 示例

`examples/minimal_manifest.json` 使用内置最小 fixture，可直接运行；实际使用时将其中路径替换为真实文件：

```json
{
  "inputFile": "../tests/fixtures/minimal_business_bid.docx",
  "outlineFile": "../tests/fixtures/minimal_outline.json",
  "outputFile": "out/minimal_business_bid.cleaned.docx",
  "projectName": "示例项目",
  "styleSpecPath": "../references/business_heading_style.json"
}
```

## 常见风险

- Word/WPS 打开文件后仍需要刷新域，TOC 页码才会最终更新。
- outline 中有标题但 Word 正文中没有对应段落时，脚本不会补章，只在报告列出未匹配标题。
- 如果正文存在大量与标题同名的普通段落，按 outline 顺序匹配能降低误命中，但最终仍需人工抽检。
