---
name: bid-material-format-cleaner
description: 当素材入库需要清洗 DOC/DOCX、剥离 Word 前序内容、规范真实标题或生成可检索清洗稿时使用。
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
---

# 素材 Word 清洗

将素材库中的旧版 DOC 转换为 DOCX，并对 DOCX 做确定性清洗。原件始终保留，清洗稿作为独立对象保存。

## 系统边界

| 输入类型 | 入库行为 | 清洗行为 |
| --- | --- | --- |
| `.doc` | 保留原件并进入清洗队列 | 入库服务调用 OnlyOffice 转为临时 DOCX，再交给 driver |
| `.docx` | 保留原件并进入清洗队列 | driver 直接规范化 |
| `.pdf` | 保留原件 | 不清洗、不转 Word、不进入深度转换 |
| `.xlsx` / `.xls` / `.xlsm` | 保留原件 | 不清洗、不转 Word、不进入深度转换 |
| 图片及其他允许格式 | 保留原件 | 不进入本 Skill |

阶段命名与历史工作目录统一引用 `../STAGES.md`。

## 职责划分

### 入库服务

`app/services/material_cleaning.py` 负责：

1. 从素材记录读取原始 MinIO bucket、key 和版本。
2. 对 DOC 原件生成 30 分钟有效的内部预签名 URL。
3. 调用 `app/services/material_doc_conversion.py` 请求 OnlyOffice 转换。
4. 将转换后的临时 DOCX 交给本 Skill 的 driver。
5. 将清洗稿上传到 `cleaned/RAW-xxxx/...docx` 并更新清洗状态。
6. 转换或清洗失败时保留原件，显式写入失败原因。

### OnlyOffice 转换器

`app/services/material_doc_conversion.py` 只负责 DOC 转 DOCX：

- 请求 `${ONLYOFFICE_INTERNAL_URL}/ConvertService.ashx`。
- 使用文件名、素材版本和预签名 URL 生成唯一转换 key。
- 只接受白名单主机返回的 HTTP/HTTPS 下载地址。
- 限制下载体积，不允许重定向。
- 校验产物是包含 `word/document.xml` 的有效 DOCX。
- 失败时删除不完整产物并保留原始 DOC。

### Skill driver

`scripts/driver.py` 只处理已经准备好的 DOCX：

- 递归扫描 `.docx`，忽略 DOC、PDF、Excel 和其他后缀。
- 每个文件复制到独立临时目录后再修改。
- 探测正文起点，最多执行一次常规 trim 和一次纠偏。
- 规范真实 Heading，清除其前置数字编号。
- 验证后一次性复制到输出目录。
- 写入 `cleaning_manifest.json`。

不要把 DOC、PDF 或 Excel 直接交给 driver。DOC 的 URL 转换必须由掌握 MinIO 权限的入库服务编排。

## DOC 转换数据流

```text
MinIO raw/.../source.doc
  -> 内部预签名 URL
  -> OnlyOffice ConvertService
  -> 临时 source.docx
  -> driver.py
  -> 临时清洗稿
  -> MinIO cleaned/RAW-xxxx/...docx
```

原始 `raw/.../source.doc` 不覆盖、不删除。只有用户主动覆盖、版本管理或删除素材时，才走素材库既有的对象处理规则。

## DOCX 清洗规则

1. 优先使用 `officecli view outline/text` 做探针。
2. `officecli` 不可用时立即回退 `word_cleaner.py`，不反复重试。
3. 前部已是正文时跳过 trim，只执行 normalize 和 verify。
4. 存在封面、目录、前言、声明、审批或修订记录时定位一次正文锚点并 trim。
5. 只把已有 Heading 样式或 outline 层级视为标题，不根据短文本或数字编号猜标题。
6. 空白标题只清除 Heading 样式和 outlineLvl，保留段落及其中的换行符和分页符。
7. 验证失败时最多纠偏一次；仍异常则标记 `REVIEW`。
8. 所有修改只发生在临时副本，源 DOCX 不修改。

## driver 调用

线上由素材清洗任务自动调用。本地验证时使用项目虚拟环境：

```bash
VENV_PY="./.venv/Scripts/python"
"$VENV_PY" "opencode/skills/bid-material-format-cleaner/scripts/driver.py" \
  "<DOCX_SOURCE_DIR>" \
  --output-dir "<OUTPUT_DIR>" \
  --report-file cleaning_manifest.json \
  --no-feishu
```

macOS / Linux 将解释器路径改为 `./.venv/bin/python`。

driver 运行依赖仅包括：

```bash
"$VENV_PY" -m pip install python-docx lxml
```

后端运行还需要可访问的 OnlyOffice 和 MinIO，但 driver 本身不访问这两个服务。

## 状态约定

- `OK`：完成切割或 DOC 转换后的规范化。
- `SKIP`：无需切割，但已完成规范化和验证。
- `REVIEW`：已生成可用清洗稿，但需要人工复核。
- `FAIL`：转换、读取、依赖、文档结构或验证出现硬失败。

素材记录使用以下清洗状态：

- `pending`：DOC/DOCX 已入库，等待清洗。
- `cleaning`：正在转换 DOC 或清洗 DOCX。
- `cleaned`：清洗稿已上传，原件仍保留。
- `failed`：本次转换或清洗失败，错误信息已保存，原件仍保留。
- `original_only`：PDF、Excel、图片等格式只保留原件。

## manifest 核心字段

```json
{
  "schemaVersion": "material-cleaning-manifest/v1",
  "summary": {
    "total": 1,
    "successTotal": 1,
    "reviewTotal": 0,
    "failedTotal": 0,
    "byKind": {"word": {"OK": 1}}
  },
  "records": [
    {
      "kind": "word",
      "status": "OK",
      "sourceSuffix": ".docx",
      "outputSuffix": ".docx",
      "outputExists": true,
      "isUsableForRetrieval": true,
      "needsHumanReview": false
    }
  ]
}
```

DOC 原件名称和来源路径由素材记录保存；manifest 描述 driver 实际接收的临时 DOCX 和清洗结果。

## 失败处理

- OnlyOffice 未配置、请求失败、返回错误码或无下载地址：标记 `failed`。
- 返回地址协议、认证信息或主机不可信：拒绝下载并标记 `failed`。
- 下载超限、重定向或产物不是有效 DOCX：删除临时产物并标记 `failed`。
- 单个 DOCX 清洗失败：记录 `FAIL`，不影响同批其他文件。
- 清洗稿上传成功但状态写库失败：补偿删除新清洗稿，原件保持不变。
