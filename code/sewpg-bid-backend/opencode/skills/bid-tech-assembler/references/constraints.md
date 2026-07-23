# 组装约束细则（实现级）

`SKILL.md`「关键约束」只保留策略级条目；本文件承载实现级细节，修改对应脚本时同步更新。

## 编号与样式

- **Heading 样式名兼容**：`Heading 1-6` ↔ `标题 1-6` 双向映射（`preprocess.py` / `numbering_fixer.normalize_heading_style_names`）。
- **字体 rFonts 注入**：eastAsia=等线/等线Light、ascii=TNR（各级 Heading 不同），正文 eastAsia=等线；参数事实来源是 `references/heading_style.json`，`finalize.py` 兜底再刷。
- **"前言"段**：无编号 Heading 1，用自定义样式 `PrefaceTitle` 或 `ilvl=-1`。
- **（新增）/（适配）标签**：parse 阶段提取为 metadata，最终 docx 里剥除。

## 素材匹配与结构

- **附字头自动重排**：`build_assembly.rearrange_appendices` 按 title 语义把错放的附字头挂到正确父 normal 下，原位置已正确时不动。
- **整章素材 guard**：卡片 `skeleton_section` 深度与 entry `chapter_no_flat` 深度差超过 1 时，fallback 匹配跳过该卡片，避免整章素材被误挂到子节（需在卡片上显式标 skeleton_section 为「未明确」交人工处理）。
- **当前系统素材库适配**：Wiki 卡片的 `material_id`、`cleaned_file_name`、`path` 是素材定位依据；后端运行前将 MinIO/数据库素材导出成文件系统 docx，并把卡片 `path` 重写为导出后的相对路径。
- **素材库纯 docx**：`投标资料库-通用/` 和 `投标资料库-定制/` 下只允许 `.docx`；`scripts/cleaner.py` 的 CLI 已硬禁止向素材库写入 `*_cleaned.txt`。

## 合并与 Section

- **Section 隔离**：`merger._isolate_section` 为每份素材在 body 开头插入 continuous section break 带自身 sectPr，防止多份单 section 素材被 docxcompose 吞进同一 section 后被后续 landscape 素材污染。
- **纸张方向**：保留素材原始 page orientation（不强制竖版），素材里为宽表设的 landscape section 合入后仍是横版。
- **素材方向由素材决定**：skill 不自动纠正 page orientation；某素材应横版却存成竖版属素材本身错误，需人工改源 docx 再重跑。
- **单素材容错**：素材不存在、预处理失败或 compose 失败只增加 warning，不中断当前 plan；继续处理同节点及后续节点的其它素材。
- **空节点兜底**：`MATCHED / ADAPTED` 节点没有任何成功合并的素材时，必须保留 S2 Heading 并插入简短占位段落，避免输出空章节。

## 表格与图表

- **表格格式**：宋体、五号或小四、居中、单倍行距、无缩进。
- **图表题注**：不重编号，尊重素材原样。

## 验证守门

- **空章节检测**：`verify.scan_docx` 体级遍历（段落 + 表格 + drawing/pict），叶子 heading 后既无文字又无表格/图片的章节进入紧凑 JSON 校验结果，由 manifest runner 汇总到 `summary.verification` 和 `warnings`；这是暴露 wiki 归位错 / 素材空框架的关键守门哨。
- **结构化校验结果**：残留占位符、空章节、相邻重复标题、幽灵章节、非法 H1 和非法标题前缀只写入紧凑 JSON 校验结果，供 manifest runner 汇总到 `summary.verification` 和 `warnings`，不生成 Markdown 报告。
- **warning 稳定结构**：manifest 返回的 `warnings[]` 每项只能包含 `code`、`message`、`count`；`summary.warningCount` 等于所有 `count` 之和。

## 与 format-cleaner 的共享契约

`references/heading_style.json` 不只属于本 skill，它是技术标标题样式的**共享契约**，消费方有四处：

1. 本 skill `finalize.py`（`--style` 参数）与 `tools/create_tech_master.py`；
2. `bid-tech-format-cleaner/scripts/run_from_manifest.py:243`（无 styleSpecPath 时的默认回退，且该脚本还 import 本 skill 的 `numbering_fixer` 模块）;
3. 后端 `app/services/tech_assembly.py` 与 `app/services/technical_document_format.py`（硬编码路径传参）。

**移动或改名此文件、重构 scripts/ 目录前，必须同步以上全部消费方。**
