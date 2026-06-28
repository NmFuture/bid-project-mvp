# 技术标 Wiki 刷新/重建与 TLDR 预览 Handoff

> 编写日期：2026-06-28  
> 适用范围：技术标素材库 Wiki、三级目录 JSON 索引、文件 TLDR 内容预览。  
> 目标读者：后端、前端、运维和后续接手该链路的 agent。

---

## 1. 当前产品口径

技术标 Wiki 的结构真值是唯一 JSON 索引：

```text
.localdata/documents/_runtime/materials/technical_material_index.json
```

线上容器通常对应：

```text
/data/documents/_runtime/materials/technical_material_index.json
```

刷新和重建的语义已经收敛为：

| 操作 | 当前语义 | 导入模式 |
|---|---|---|
| 刷新 Wiki | 读取唯一 JSON，让自动生成 Wiki 根树与 JSON 保持一致。新增则新增，删除则移除，已有节点更新内容。 | `mode=refresh` |
| 重建 Wiki | 读取同一份唯一 JSON，全量替换自动生成 Wiki 根树。 | `mode=replace` |

两者都不再从 Wiki 入口重新扫描/归类原始素材，也不再走独立的“生成内容预览”按钮。

---

## 2. 入口与调用链

前端两个按钮都调用同一个接口：

```http
POST /api/technical/materials/wiki/bootstrap
```

请求体通过 `mode` 区分：

```json
{ "mode": "refresh" }
```

```json
{ "mode": "replace" }
```

后端主链路：

```text
technical_wiki_generation.generate_technical_wiki()
  -> load_technical_material_index()
  -> enrich_technical_wiki_previews(index_payload)
  -> write_json_file_atomic(TECHNICAL_MATERIAL_INDEX_PATH, index_payload)
  -> mirror_technical_index_to_wiki(index_payload, mode=refresh|replace)
  -> run_from_manifest.py 生成 Wiki blueprint
  -> import_generated_wiki_blueprint()
```

关键文件：

| 文件 | 责任 |
|---|---|
| `app/services/technical_wiki_generation.py` | Wiki 刷新/重建总入口；串联 JSON、预览补齐、Wiki 导入。 |
| `app/services/technical_wiki_preview_generation.py` | 生成/复用文件 TLDR 预览；处理 LLM、缓存、本地 fallback。 |
| `opencode/skills/bid-tech-wiki-material-builder/scripts/run_from_manifest.py` | 把 JSON 索引渲染为 Wiki blueprint；文件卡片渲染 TLDR。 |
| `app/services/technical_material_index.py` | 维护唯一 JSON 索引。 |
| `src/api/index.js` | 前端 Wiki bootstrap 超时已调到 10 分钟。 |

---

## 3. 目录结构约束

技术标素材只允许进入三个规范根：

```text
技术标/标准文件
技术标/客户定制
技术标/项目定制
```

历史别名需要归一：

| 历史/别名 | 规范名 |
|---|---|
| 客户素材 | 客户定制 |
| 项目素材 | 项目定制 |

未知二级目录不再自动猜测归类。例如 `技术标/国电投` 不应成为 Wiki 档位；正确路径应是：

```text
技术标/项目定制/国电投/...
```

Wiki 的目录层级固定镜像 JSON：

```text
技术标Wiki（自动生成）
  -> 档位：标准文件 / 客户定制 / 项目定制
    -> 3 级目录：机型号 / 客户名 / 项目标识
      -> 文件卡片
```

4 级及更深的文件会归并到所属 3 级目录下，但文件卡片保留完整路径。

---

## 4. TLDR 文件信息卡片

文件卡片现在优先显示：

```markdown
## TLDR 文件信息卡片
```

内容包括：

- 来源：`AI 生成` 或 `本地 TLDR`
- 一句话导读
- 核心要点
- 关键参数
- 检索提示

示例字段写在 JSON 文件节点的 `preview` 上：

```json
{
  "lead": "一句话导读",
  "points": ["核心要点 1", "核心要点 2"],
  "keyParams": [{ "label": "文件类型", "value": "docx" }],
  "retrievalHints": ["投标方案", "国电投"],
  "source": "local"
}
```

`source=local` 表示 LLM 没有成功产出时，由本地标题、正文摘录、路径、清洗状态生成兜底 TLDR。

---

## 5. 预览生成策略

### 5.1 缓存优先

每个原始文件的预览缓存落在：

```text
RawFile.ext_fields.techWikiPreview
```

缓存命中条件：

- `schemaVersion` 与当前预览 schema 一致
- `signature` 与当前文件抽取摘要一致
- `status == "completed"`
- `preview` 是非空对象

命中缓存时不再调用 LLM，直接注入 JSON 和 Wiki。

### 5.2 LLM 生成

如果缓存未命中，并且文件可抽取正文摘要，则进入批量 LLM 生成：

```text
extract_docx_profile()
  -> build_batch_preview_prompt()
  -> OpencodeClient.send_text_prompt()
  -> parse_batch_preview_reply()
```

LLM 成功后：

- `status = "completed"`
- `preview.source` 默认为 AI 生成
- 写回 `RawFile.ext_fields.techWikiPreview`
- 注入 `technical_material_index.json`
- 渲染进 Wiki 文件卡片

### 5.3 本地 TLDR fallback

如果 LLM 失败、返回缺项、非 docx、文件超限、正文无法抽取等情况，不再让文件卡片空白。

当前策略：

- 生成 `status = "fallback"` 的本地 TLDR。
- `preview.source = "local"`。
- Wiki 文件卡片仍显示 `TLDR 文件信息卡片`。
- 失败/跳过原因保留在 `generation.preview.errors`，但不阻塞刷新/重建。

这解决了之前“LLM 失败后 Wiki 整体 completed，但文件没有内容预览”的问题。

---

## 6. LLM 并发与压力

当前配置在：

```python
PREVIEW_BATCH_SIZE = 8
PREVIEW_CONCURRENCY = 4
```

含义：

- 批量大小：每次 LLM 请求最多携带 8 个文件摘要。
- 并发批次数：最多同时 4 个 LLM 请求。
- 理论峰值：最多同时处理约 32 个文件摘要。

压力判断：

- 当前压力不算大，但存在峰值。
- 已有缓存会直接复用，不会再打 LLM。
- 最近一次刷新统计：`415` 个缓存命中，所以实际新增 LLM 压力很低。
- LLM 失败时会降级为本地 TLDR，不会阻塞 Wiki 刷新完成。

如果 opencode 或模型网关不稳，建议把并发从 4 降到 2：

```python
PREVIEW_CONCURRENCY = 2
```

调整后：

- 峰值从同时 4 个请求降为同时 2 个请求。
- 一次最多约 16 个文件摘要在飞。
- 刷新/重建会慢一些，但更稳。

---

## 7. 返回结果与可观测信息

刷新/重建接口返回的 `generation.preview` 会包含：

```json
{
  "enabled": true,
  "total": 478,
  "completed": 415,
  "cached": 415,
  "fallback": 63,
  "skipped": 51,
  "failed": 0,
  "errors": []
}
```

字段说明：

| 字段 | 含义 |
|---|---|
| `total` | 本轮扫描到的文件数 |
| `completed` | 本轮成功注入 AI 预览的数量，缓存命中也会算入完成 |
| `cached` | 命中 DB 缓存、未打 LLM 的数量 |
| `fallback` | 使用本地 TLDR 的数量 |
| `skipped` | 非 docx、超限、无法抽取等跳过 LLM 的数量 |
| `failed` | 真正失败且没有可用预览的数量；当前应尽量保持 0 |
| `errors` | 前 20 条原因，供排查 |

接口 summary 会明确展示：

```text
内容预览：AI 成功 415 个（缓存 415 个），本地 TLDR 63 个，跳过 51 个，失败 0 个。
```

---

## 8. 最近一次本地验证结果

本地刷新接口已经验证通过。

示例节点：

```text
技术标/项目定制/国电投/投标方案.docx
RAW-0752
```

该节点当前已渲染：

```markdown
## TLDR 文件信息卡片

> 来源：本地 TLDR

> 上海电气以“客户发电量最大化、风机载荷安全，综合度电成本最低”为导向，制定投标方案如下...
```

关键参数区显示：

```text
文件类型: docx
所属目录: 国电投
清洗状态: cleaned
表格数量: 1
```

最近一次刷新统计：

```text
3 个档位 / 6 个 3 级目录 / 478 个文件
AI 成功 415 个（缓存 415 个），本地 TLDR 63 个，跳过 51 个，失败 0 个
```

---

## 9. 已移除/不应恢复的内容

以下独立预览入口不再作为产品功能存在：

```text
生成内容预览按钮
/api/technical/materials/wiki/previews/generate
/api/technical/materials/wiki/previews/status
```

预览能力现在是刷新/重建 Wiki 的内部步骤。

不要再让前端自动轮询独立 preview job；也不要重新加独立按钮，除非产品重新确认。

---

## 10. 验证命令

后端聚焦测试：

```bash
cd code/sewpg-bid-backend
.venv/bin/python -m unittest tests.test_technical_material_index tests.test_technical_wiki_runner tests.test_technical_wiki_generation
```

语法检查：

```bash
cd code/sewpg-bid-backend
.venv/bin/python -m py_compile \
  app/services/technical_wiki_generation.py \
  app/services/technical_wiki_preview_generation.py \
  app/services/technical_wiki_preview_prompt.py \
  opencode/skills/bid-tech-wiki-material-builder/scripts/run_from_manifest.py \
  opencode/skills/bid-tech-wiki-material-builder/scripts/technical_wiki_preview.py \
  tests/test_technical_wiki_runner.py \
  tests/test_technical_wiki_generation.py
```

前端构建：

```bash
cd code/sewpg-bid-frontend
npm run build
```

空白/格式检查：

```bash
git diff --check
```

手动刷新 Wiki：

```bash
curl -sS -X POST http://127.0.0.1:8000/api/technical/materials/wiki/bootstrap \
  -H 'Content-Type: application/json' \
  --data '{"mode":"refresh"}'
```

---

## 11. 后续建议

1. 如果 opencode 网关仍出现 502，先把 `PREVIEW_CONCURRENCY` 从 4 降到 2。
2. 可以把 `fallback` 数量作为健康指标。如果 fallback 突然升高，说明 LLM 网关、docx 抽取或缓存签名可能异常。
3. 当前本地 TLDR 是确定性摘要，足够避免空卡片；如果后续需要更高质量，可以在 opencode 恢复后通过刷新/重建自然替换为 AI 预览。
4. Wiki 结构仍应严格以 JSON 为准，不要在 Wiki 生成入口重新做素材分类。
