---
name: bid-tech-format-cleaner
description: 当用户要求清洗已成稿技术标 Word 格式、根据技术标目录提升标题样式、插入目录、统一页眉或清理技术标正文样式时使用。
allowed-tools: [Read, Bash]
---

# 技术标成稿 Word 格式清洗

本 skill 只处理已经成稿的技术标 `.docx`，属于成稿后处理阶段。它根据后端在 `s5_format_switch_workdir` 准备的技术标目录 JSON（由 S1 目录阶段产物转换而来）定位标题，统一 Word 标题、目录、页眉、页面方向和正文基础格式。历史目录编号映射见 `../STAGES.md`。

## 输入

manifest 必须包含：

- `inputFile`：待清洗技术标 `.docx`。
- `outlineFile`：技术标目录 JSON，支持 `sections/children` 或后端转换后的技术标 outline。
- `outputFile`：清洗后 `.docx` 输出路径，不能与 `inputFile` 相同。
- `projectName`：项目名称，用于页眉。
- `styleSpecPath`：可选。默认配置和自定义配置都以 `bid-tech-assembler/references/heading_style.json` 为基线；自定义模式只覆盖后端校验通过的 `styleOverrides`。本 skill 无此参数时回退到同一路径，并复用 assembler 的编号修复模块。

## 执行命令

```bash
python scripts/run_from_manifest.py <manifest> --response summary
```

`--response summary` 输出 JSON，schema 固定为 `bid-tech-format-clean-v1`，包含 `inputFile`、`outlineFile`、`outputFile`、`reportFile`、`summary` 和 `warnings`。兼容字段 `reportFile` 固定为空字符串；`summary` 包含匹配/未匹配标题数、占位符数、TOC 状态、横竖版统计和 `warnings`，顶层 `warnings` 与其一致；每条 warning 只有 `code`、`message`、`count`。

## 行为规则

- 先复制 `inputFile` 到 `outputFile`，只改输出文件。
- 读取目录中的章节标题，按目录顺序匹配 Word 段落。
- 匹配成功后设置 `Heading 1-6`，并清除标题段落残留编号属性。
- 对正文内部疑似三级/四级小标题做保守提升。
- 按配置决定是否插入自动目录域及目录后的分页；Word/WPS 打开后需要刷新域才能显示最终页码。
- 实际应用标题、正文、表格、题注、页边距和页眉配置；重复切换默认/自定义时直接重刷格式，不重新组装正文。
- 保留正文内容、图片、表格、图表题注和已有横版 section，不重排章节、不强制改横竖版。
- 对未匹配标题、占位符、目录和格式风险生成结构化摘要与 warnings。

## 输出检查结果

脚本不会生成额外 Markdown 报告；`summary` 与 `warnings` 返回：

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
- outline 中有标题但正文中没有对应段落时，脚本不会补章，只在结构化 warning 中列出未匹配标题数。
- 正文中如果有大量与标题相似的短句，内部小标题提升需要人工抽检。
