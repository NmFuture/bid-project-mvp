# business_section_tree

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/business_section_tree.py` |
| 层级 | 服务层 |
| 领域 | 商务标 |
| 行数 | 1075 |

**职责**: 商务标招标文件章节树抽取器：直接解析 docx OOXML（不走 LLM），按标题关键词（资格要求/须知前附表/评分标准/招标公告等）识别章节，产出最多 3 级的章节树（schema `bid-business-section-tree-v1`）。

## Input（输入）
- 招标 docx（zipfile+ElementTree 直读 word/document.xml）；标题关键词组（QUALIFICATION/BIDDER_INSTRUCTION/SCORING/GENERAL 四类）+ 排除线索（含「须/应/需」等正文动词的行不算标题）。

## Output（输出）
- `write_business_section_tree`：章节树 JSON 落盘（S1 解析产物之一，供缺口计划按章定位招标原文）。

## 调用链
- **上游**: `parsing`（S1 解析主流程内调用）。
- **下游**: 标准库（zipfile/ET/re），无服务依赖。

## 中间数据与状态
- 章节树 JSON（parsed 工作目录）；`MAX_SECTION_LEVEL=3`。
