# 商务标目录生成 Skill 适配说明

> 用途：记录商务标 S2 目录生成 Skill 适配后的数据流、编号规则、刷新口径和验收记录，便于后续接手者继续维护。
> 更新日期：2026-05-25
> 适用范围：仅商务标目录生成与目录审核页；不改变技术标目录生成、技术标 Skill、技术标页面或技术标测试口径。
> 当前入口：商务标目录审核页面已迁到 `src/workspaces/business/pages/BusinessOutlineReview.jsx`；旧共享 OutlineReview 页面不再作为当前页面口径。

## 1. 当前结论

商务标目录生成现在以 `business-bid-outline` Skill 产出的 `outline.json` 作为唯一目录结构来源。目录编号不再由前端或后端按层级顺序自动生成，而是从 `outline.json` 中每个 section 的 `number` 字段贯通到后端 `toc.json`、目录审核页节点和前端编号列。

空编号是有效状态。历史商务标模板中没有编号、或者无法可靠推断编号的目录项，应在 `outline.json` 中写 `number: null` 或 `number: ""`，前端编号列显示为空。

## 2. 数据流

当前链路如下：

```text
历史商务标投标文件
  -> scripts/prepare_history_bid_outline_inputs.py
  -> history_bid_outline_inputs.json 的 outline_candidates[*].number
  -> business-bid-outline Skill 生成 outline.json
  -> 后端 _business_toc_items_from_sections()
  -> toc.json.items[*].number
  -> 后端 _outline_nodes_from_toc()
  -> outline_state.nodes[*].tocNumber
  -> 前端 BusinessOutlineReview 编号列
```

关键点：

1. `outline.json.sections[*].number` 和所有子级 section 的 `number` 字段必须显式存在。
2. 后端加载商务标 `outline.json` 时会校验 `number` 字段，缺失会报错，不再静默补编号。
3. 后端生成商务标 `toc.json` 时，`number` 直接来自 section 的 `number`，不会按 `1 / 1.1 / 1.2` 重新编号。
4. `outline_state.nodes[*].tocNumber` 来自 `toc.json.items[*].number`。
5. 前端 `BusinessOutlineReview.jsx` 的编号列显示 `tocNumber`，不再显示 UI 递归生成的 `seq`。

## 3. number 字段规则

`number` 表示最终 Word 标题排版编号，不表示节点排序，也不表示招标文件附件号。

生成规则：

1. 历史商务标标题带编号时，保留原编号，例如 `一、`、`二、`、`1.1`、`5.2`。
2. 历史商务标标题无编号时，保留空编号，写 `null` 或空字符串。
3. 新增目录项只有在历史同级编号规律清晰时才可续编编号。
4. 无法可靠推断时必须保留空编号，并可在 `review_items` 中提示人工确认。
5. 禁止因为目录层级存在，就自动生成 `1`、`1.1`、`1.2` 等编号。
6. 禁止把招标文件的附件号、表号、格式编号直接当作 Word 标题编号，除非历史商务标就是这样排版。

## 4. title 与编号分离

`title` 只保存干净标题，编号只保存在 `number` / `tocNumber`。

示例：

```json
{
  "title": "投标价格表",
  "number": "二、"
}
```

不要生成：

```json
{
  "title": "二、 投标价格表",
  "number": "二、"
}
```

后端对 `source == "business_outline"` 的目录项不会再把中文编号拼回标题，避免目录审核页出现“编号列有 `二、`，输入框里也有 `二、`”的重复显示。

## 5. 刷新口径

目录审核页读取的是后端保存的 `outline_state`。

生成或重生成目录完成后，如果浏览器页面仍停留在旧状态，可能继续看到旧 `outline_state`。刷新页面后会重新拉取最新状态。2026-05-09 的排查中，一级标题编号重复显示的问题最终确认为页面未刷新导致的旧状态展示，不是最新 `outline.json` 或前端编号列逻辑的问题。

## 6. 关键文件

后端：

1. `code/sewpg-bid-backend/app/services/outline_generation.py`
2. `code/sewpg-bid-backend/tests/test_directory_generation.py`

商务标目录 Skill：

1. `code/sewpg-bid-backend/opencode/skill/business-bid-outline/SKILL.md`
2. `code/sewpg-bid-backend/opencode/skill/business-bid-outline/references/outline.example.json`
3. `code/sewpg-bid-backend/opencode/skill/business-bid-outline/scripts/prepare_history_bid_outline_inputs.py`
4. `code/sewpg-bid-backend/opencode/skill/business-bid-outline/scripts/validate_outline.py`
5. `code/sewpg-bid-backend/opencode/skill/business-bid-outline/scripts/test_prepare_history_bid_outline_inputs.py`

前端：

1. `code/sewpg-bid-frontend/src/workspaces/business/pages/BusinessOutlineReview.jsx`
2. `code/sewpg-bid-frontend/src/utils/outlineNumber.js`
3. `code/sewpg-bid-frontend/src/utils/outlineNumber.test.mjs`

容器适配：

1. `code/docker-compose.yml`
2. `code/sewpg-bid-backend/Dockerfile`
3. `code/sewpg-bid-backend/opencode/Dockerfile`

## 7. 验收记录

2026-05-09 已用 Docker 环境执行真实商务标目录生成：

1. 项目：`PRJ-0004`
2. OpenCode session：`ses_1f2f073c3ffenS6H3NCxW8VEdG`
3. 开始时间：`2026-05-09T14:06:20Z`
4. 完成时间：`2026-05-09T14:10:26Z`
5. 总耗时：246 秒
6. Skill 执行耗时：243 秒
7. 工作目录：`/data/documents/PRJ-0004/business-workspace/s2_toc_workdir`
8. Skill 输出：`/data/documents/PRJ-0004/business-workspace/s2_toc_workdir/outline.json`
9. 后端转换结果：`/data/documents/PRJ-0004/business-workspace/s2_toc_workdir/toc.json`

编号链路核对结果：

```text
outline.json sections number:
["一、","二、","三、","3.1","3.2","","四、","五、","5.1","5.2"]

toc.json items number:
["一、","二、","三、","3.1","3.2","","四、","五、","5.1","5.2"]

outline_state nodes tocNumber:
["一、","二、","三、","3.1","3.2","","四、","五、","5.1","5.2"]
```

其中 `商务评分索引表` 为空编号，前端编号列应显示为空。

## 8. 验证命令

本链路变更后建议至少执行：

```powershell
cd code/sewpg-bid-frontend
node --test src/utils/outlineNumber.test.mjs
npm run build
npm run lint
```

```powershell
cd code/sewpg-bid-backend
.\.venv\Scripts\python.exe -m pytest tests/test_directory_generation.py -q
```

```powershell
cd code
docker compose up -d --build
docker compose ps
```

提交前再执行：

```powershell
git diff --check
```
