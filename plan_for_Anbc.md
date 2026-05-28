# 安博成任务规划

## 1. 文档用途

这份文档用于沉淀安博成在本轮商务标端到端研发中的任务范围、参考依据、实施顺序、相关代码入口和验收口径。后续开发、联调、测试、复盘都以本文件和下列三份基线文档为准。

## 2. 必读参考源

后续开工前先读这三份文档，不再以归档旧文档作为当前事实：

| 文档 | 路径 | 需要重点看的内容 |
| --- | --- | --- |
| 需求梳理 | `doc/需求梳理.md` | 商务标主流程、素材库、共用业绩库、素材清洗、Wiki 生成、素材匹配三类处理方式。 |
| 代码结构梳理 | `doc/代码结构梳理.md` | 前后端入口、素材库/Wiki 服务、素材存储与路径范围、Skill 所在位置。 |
| 研发计划 | `doc/研发计划.md` | 本轮分工、安博成负责人条目、时间节点、验收口径和协作约束。 |

关键依据摘要：

- 当前目标是先把商务标端到端跑通，技术标后续单独梳理。
- 商务标主流程中，安博成负责的是素材库前置链路，支撑后续素材匹配、事实表、AI 填写和正文生成。
- 素材库需要支持上传、清洗、预览、标签、Wiki、检索和权限范围控制。
- 素材要支持多个标签，标签用于缩小 Skill 检索范围，提高匹配准确率。
- 共用业绩库不是简单文件夹，应由 PostgreSQL 保存结构化业绩字段和文件路径，由对象存储保存每条业绩对应的 Word 文件。
- Skill 优化必须保持泛化，不能按单个样本硬编码文件名、字段值或答案。

## 3. 总体职责

安博成本轮职责：

```text
素材库、素材标签、共用业绩库、素材清洗、商务 Wiki
```

核心交付物：

```text
可检索素材库、标签能力、共用业绩库最小版、商务 Wiki
```

这条链路的目标不是单独做一个好看的页面，而是让商务标后续流程可以稳定读取素材：

```text
商务素材上传
-> 清洗/预处理
-> 多标签和元数据维护
-> Wiki 生成和证据说明
-> 共用业绩库沉淀
-> 给素材匹配、事实表、AI 填写、正文生成提供可检索输入
```

## 4. 任务拆解

### 4.1 原始素材多标签

目标：商务标原始素材上传和编辑时支持多个标签，标签能保存到后端，并被后续素材匹配输入读取。

参考依据：

- `doc/需求梳理.md`：素材库需要支持标签；素材要支持多个标签。
- `doc/研发计划.md`：原始素材标签由安博成负责，目标是上传和编辑素材时支持多标签。
- `doc/代码结构梳理.md`：上传素材元数据在 `material_upload_metadata.py`，更新素材元数据在 `material_update_metadata.py`。

重点文件：

| 类型 | 文件 |
| --- | --- |
| 前端页面 | `code/sewpg-bid-frontend/src/workspaces/business/pages/BusinessMaterialDB.jsx` |
| 前端 API | `code/sewpg-bid-frontend/src/api/index.js` |
| 后端路由 | `code/sewpg-bid-backend/app/api/routes/business.py` |
| 上传元数据 | `code/sewpg-bid-backend/app/services/material_upload_metadata.py` |
| 更新元数据 | `code/sewpg-bid-backend/app/services/material_update_metadata.py` |
| 素材 store | `code/sewpg-bid-backend/app/services/business_material_store.py`、`material_store.py` |
| 相关测试 | `code/sewpg-bid-backend/tests/test_business_material_library_rules.py` |

建议实施步骤：

1. 梳理当前素材上传和编辑表单里的标签字段形态，是字符串、单选还是数组。
2. 统一前端传参：标签字段按数组处理，例如 `tags: ["资质", "承诺函", "商务附件"]`。
3. 统一后端接收和保存：上传、编辑两个入口都要保留多标签，不要只保存一个标签。
4. 确保素材列表、素材详情、清洗预览、Wiki 构建输入都能看到标签。
5. 补充或调整后端测试，至少覆盖上传多标签、编辑多标签、空标签、重复标签去重。

验收标准：

- 上传商务素材时可以填写多个标签。
- 编辑已有商务素材时可以新增、删除、修改多个标签。
- 刷新页面后标签仍然存在。
- 后端返回的素材元数据包含标签数组。
- 不破坏技术标素材库当前能力。

### 4.2 共用业绩库最小版

目标：新增技术标和商务标可共用的业绩库最小版本。本轮优先服务商务标，用于业绩清单、资格证明、评分响应和附件材料。

参考依据：

- `doc/需求梳理.md`：共用业绩库由 PostgreSQL 存业绩字段和文件路径，对象桶存每条业绩对应的 Word 文件。
- `doc/研发计划.md`：共用业绩库由安博成负责，动作是新增后端 service/API，前端增加入口。
- `doc/代码结构梳理.md`：素材对象在 MinIO `bid-materials`，结构化元数据在 PostgreSQL。

建议字段：

| 字段 | 说明 |
| --- | --- |
| `id` | 业绩记录 ID。 |
| `name` | 业绩名称。 |
| `customerName` | 客户名称。 |
| `projectType` | 项目类型。 |
| `scale` | 项目规模。 |
| `location` | 项目地点。 |
| `startedAt` / `completedAt` | 项目时间。 |
| `amount` | 合同金额或项目金额。 |
| `turbineModel` | 机型，技术标后续可用；商务标可为空。 |
| `tags` | 多标签。 |
| `applicableBidTypes` | 适用标类，例如 `["商务标", "技术标"]`。 |
| `scope` | 权限范围：通用、客户、项目。 |
| `wordObjectKey` | Word 文件对象 key。 |
| `cleanedObjectKey` | 清洗稿对象 key。 |
| `reviewStatus` | 审核状态：草稿、已审核、停用等。 |
| `createdAt` / `updatedAt` | 时间戳。 |

重点文件方向：

| 类型 | 文件或建议位置 |
| --- | --- |
| 后端 service | 新增 `code/sewpg-bid-backend/app/services/performance_library_service.py` 或按现有命名选择更贴合的 `achievement_*`/`performance_*` 文件。 |
| 后端 route | 可放入 `code/sewpg-bid-backend/app/api/routes/business.py` 的商务入口，或新增独立 route 后在 router 注册。 |
| 数据结构 | 复用当前 PostgreSQL/运行时表模式，先找 `material_runtime_tables.py` 和项目 repository 的建表方式。 |
| 文件对象 | 复用 MinIO/object store 相关工具，Word 文件建议进入 `bid-materials` 桶下共用业绩路径。 |
| 前端入口 | 商务素材库页面增加入口，或新增共用业绩库页面后接入导航。 |

建议实施步骤：

1. 先确认现有后端是如何建表和保存素材元数据的，优先沿用现有 repository/store 风格。
2. 设计最小 API：列表、创建、更新、删除/停用、上传 Word、下载/预览 Word。
3. 先跑通商务标可用的字段，不急着做完整技术标高级筛选。
4. 前端先做最小可用入口：列表、筛选、创建/编辑、上传 Word、标签维护。
5. 暴露给后续素材匹配输入：让肖雨航的 `business_gap_planning.py` 能读取业绩候选。

验收标准：

- 能新增一条业绩记录并上传对应 Word 文件。
- 业绩字段和 Word 文件路径写入 PostgreSQL。
- Word 文件写入对象存储。
- 能按标签、客户、适用标类做基础筛选。
- 商务标素材匹配后续能拿到业绩候选数据。

### 4.3 商务素材清洗

目标：提升上传素材的清洗质量，输出可检索、可引用内容，支撑 Wiki 生成和素材匹配。

参考依据：

- `doc/需求梳理.md`：素材清洗用于把上传文件处理成可检索、可引用的素材。
- `doc/研发计划.md`：`bid-material-format-cleaner` 由安博成重点优化。
- `doc/代码结构梳理.md`：`material_cleaning.py` 负责素材清洗；Skill 本体在 `opencode/skill/bid-material-format-cleaner/`。

重点文件：

| 类型 | 文件 |
| --- | --- |
| 清洗 Skill | `code/sewpg-bid-backend/opencode/skill/bid-material-format-cleaner/` |
| Skill 说明 | `code/sewpg-bid-backend/opencode/skill/bid-material-format-cleaner/SKILL.md` |
| 清洗脚本 | `code/sewpg-bid-backend/opencode/skill/bid-material-format-cleaner/scripts/` |
| 后端调用 | `code/sewpg-bid-backend/app/services/material_cleaning.py` |

建议实施步骤：

1. 阅读 Skill 的 `SKILL.md` 和 `scripts/driver.py`，确认输入 manifest 和输出结构。
2. 用真实商务素材样本跑清洗，记录表格、证书、承诺函、报价说明、附件模板的清洗问题。
3. 优先保证输出结构稳定：标题、正文、表格、页码、证据位置、源文件引用。
4. 对 PDF、Word、Excel 三类常见文件分别冒烟。
5. 不在 Skill 内硬编码样本文件名或固定答案。

验收标准：

- 商务素材上传后可以触发清洗/预处理。
- 清洗结果能预览。
- 清洗结果保留可引用的来源信息。
- 清洗输出能被 Wiki builder 或后续检索使用。
- 清洗失败时有可理解的错误信息，不阻断素材库其他操作。

### 4.4 商务 Wiki 生成

目标：生成能支持素材匹配的商务 Wiki 和证据说明，重点服务资质、业绩、承诺、附件模板和商务事实引用。

参考依据：

- `doc/需求梳理.md`：Wiki 生成用于给素材生成可用于匹配的说明。
- `doc/研发计划.md`：`bid-business-wiki-material-builder` 由安博成重点优化。
- `doc/代码结构梳理.md`：商务 Wiki 构建由 `wiki_generation.py` 调用商务 builder，生成中间结果后导入素材/Wiki 存储。

重点文件：

| 类型 | 文件 |
| --- | --- |
| 前端 Wiki 页面 | `code/sewpg-bid-frontend/src/workspaces/business/pages/BusinessMaterialWiki.jsx` |
| Wiki 生成 service | `code/sewpg-bid-backend/app/services/wiki_generation.py` |
| 商务 Wiki 兜底 | `code/sewpg-bid-backend/app/services/business_wiki_blueprint.py` |
| Wiki 导入 | `code/sewpg-bid-backend/app/services/material_wiki_import.py`、`material_wiki_import_operations.py` |
| Wiki Skill | `code/sewpg-bid-backend/opencode/skill/bid-business-wiki-material-builder/` |
| Wiki 测试 | `code/sewpg-bid-backend/tests/test_wiki_generation.py`、`test_wikibuild_router.py` |

建议实施步骤：

1. 阅读 `bid-business-wiki-material-builder/SKILL.md`，确认 manifest、输入素材、输出 blueprint。
2. 明确商务 Wiki 节点需要表达什么：资质证书、业绩证明、承诺函、授权文件、报价说明、附件模板、适用标签、证据来源。
3. 优化输出，使每个 Wiki 节点都能被素材匹配使用：有标题、摘要、标签、证据、来源文件、适用范围。
4. 验证 Wiki 导入后，前端 `/workspace/business/materials/wiki` 可以展示节点、附件和摘要。
5. 保证商务 Wiki 只进入商务范围，不串到技术标 Wiki。

验收标准：

- 商务素材库页能触发生成 Wiki 或刷新摘要。
- 生成结果能导入 Wiki 树。
- Wiki 节点包含可用于匹配的标签、摘要和证据说明。
- Wiki 附件/来源 URL 能通过 `/api/business/materials/...` 访问。
- 不跨标类暴露技术标或其他客户/项目素材。

## 5. 和其他人的协作边界

| 协作者 | 对方任务 | 你需要交付给对方的输入 |
| --- | --- | --- |
| 王立博 | 样本、验收、优先级裁决 | 素材库/Wiki/业绩库可用性说明，阶段验收记录，必须裁决的问题。 |
| 肖雨航 | 素材匹配、事实表、AI 填写 | 多标签素材、可检索 Wiki、共用业绩库候选读取方式。 |
| 彭维锋 | 解析、目录、正文、格式导出 | 保证素材和 Wiki 可被正文生成链路引用；必要时说明素材证据字段。 |
| 马雨欣 | 测试和复测 | 提供测试路径、测试数据准备方式、预期结果和已知问题。 |

重要边界：

- 做 Skill 时只改对应 Skill 目录；发现 API、service、数据库、存储、模板或其他 Skill 问题，先记录并单独提代码改动。
- 做前端/后端任务时不要顺手改 Skill 逻辑。
- 不能按单个样本硬编码文件名、字段值或答案。
- 技术标素材库不是本轮主任务；如果共享底座必须改，要确认不破坏技术标入口。

## 6. 时间计划

| 日期 | 安博成重点 | 当日产出 |
| --- | --- | --- |
| 2026-05-28 | 启动素材库；梳理标签、业绩库、清洗和 Wiki 当前状态。 | 改造方案、现状问题清单。 |
| 2026-05-29 | 素材标签、共用业绩库继续开发。 | 标签和业绩库接口初版。 |
| 2026-05-30 | 素材清洗和商务 Wiki 第一版。 | 清洗后素材、Wiki 初版。 |
| 2026-05-31 | 素材库/Wiki 继续打磨；准备给素材匹配使用。 | 可检索素材库、匹配输入第一版。 |
| 2026-06-01 | 素材库/Wiki 阶段收口，配合素材匹配主链路。 | 素材库验收材料，支撑固定素材/AI填写/人工补充匹配。 |

## 7. 推荐开发顺序

1. 先做原始素材多标签。
2. 再做共用业绩库最小版。
3. 然后跑通商务素材清洗。
4. 最后优化商务 Wiki 生成和导入。
5. 阶段收口时，与肖雨航联调素材匹配输入，确认标签、Wiki、业绩候选能被读取。

原因：素材匹配依赖素材标签、Wiki 和业绩候选。如果先优化匹配或正文，输入不稳定会反复返工。

## 8. 验证清单

每个小功能完成后至少做这些验证：

| 功能 | 验证方式 |
| --- | --- |
| 多标签上传 | 上传商务素材，填写多个标签，刷新页面确认仍存在。 |
| 多标签编辑 | 修改已有素材标签，确认后端返回数组且页面展示正确。 |
| 素材清洗 | 对 Word/PDF/Excel 至少各跑一个样本，确认有清洗输出和预览。 |
| 商务 Wiki | 点击生成 Wiki/刷新摘要，确认 Wiki 树有节点、摘要、标签和来源证据。 |
| 共用业绩库 | 新增业绩、上传 Word、编辑标签和适用标类，确认能列表筛选。 |
| 范围隔离 | 商务素材和 Wiki 不出现在技术标接口或技术标页面里。 |

建议命令：

```bash
cd /Users/anbc/Desktop/NmFuture/code/sewpg-bid-backend
PYTHONPATH=. pytest tests/test_business_material_library_rules.py tests/test_wiki_generation.py tests/test_wikibuild_router.py

cd /Users/anbc/Desktop/NmFuture/code/sewpg-bid-frontend
npm run build
```

Docker 环境验证：

```bash
cd /Users/anbc/Desktop/NmFuture/code
docker compose up -d --build
docker compose ps
curl http://localhost/api/healthz
```

## 9. 交付说明模板

每次交付建议按这个格式写：

```text
本次完成：
- ...

验证结果：
- ...

影响范围：
- ...

还卡在哪里：
- ...

需要谁配合：
- ...
```

## 10. 当前入口速查

| 能力 | URL 或路径 |
| --- | --- |
| 商务素材库页面 | `http://localhost/workspace/business/materials/raw` |
| 商务 Wiki 页面 | `http://localhost/workspace/business/materials/wiki` |
| 当前技术标素材页 | `http://localhost/workspace/tech/materials/raw` |
| 后端健康检查 | `http://localhost/api/healthz` |
| OpenCode 健康检查 | `http://localhost:4096/global/health` |
| Docker 启动入口 | `cd /Users/anbc/Desktop/NmFuture/code && docker compose up -d --build` |

