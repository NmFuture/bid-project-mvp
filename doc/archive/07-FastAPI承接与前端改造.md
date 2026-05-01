# FastAPI 承接与前端最小改造方案

> 归档说明：本文已于 2026-05-01 移入 `doc/archive/`，仅作历史迁移方案参考。当前开发入口请看 `/Users/wlb/Agent/bid-project/doc/14-甲方新增需求待办.md` 和 `/Users/wlb/Agent/bid-project/doc/README.md`。
>
> 目标：保留现有前端 `S0-S10` 展示流，用 FastAPI 统一承接所有 `/api`。
> 原则：**关键阶段真实执行，其余阶段先由 FastAPI mock。**

## 1. 总体方案

直接采用下面这条路线：

```text
Web 前端 -> FastAPI(/api)
                    -> PostgreSQL + 本地文件
                    -> opencode serve
                    -> OnlyOffice
                    -> 非 MVP mock 返回
```

一句话：

> **FastAPI 既是当前唯一后端，也是现阶段的统一 mock 网关。**

## 2. 哪些能力真实做

当前建议真实打通这些阶段：

- `S0`：项目列表 / 新建项目
- `S1`：解析招标文件
- `S2`：目录生成
- `S3`：目录审核
- `S7`：技术标正文拼装
- `S8`：素材拼装覆盖校验
- `S9`：OnlyOffice 共创
- `S10`：下载最新版 Word

补充说明：

- 登录鉴权当前先不作为主链路阻塞项
- `S0` 先把项目列表 / 新建项目做好即可

对应关键调用关系：

- `S2`：FastAPI -> `opencode` 目录生成 skill
- `S7`：FastAPI / worker -> 本地 `bid-tech-assembler` skill
- `S8`：FastAPI -> S7 `assembly_plan.json` 与素材卡片覆盖计算
- `S9`：FastAPI -> OnlyOffice config / callback / save

## 3. 哪些能力先 mock

下面这些阶段和模块先不做真实逻辑：

- `S4`
- `S5`
- `S6`
- cockpit
- audit
- settings

要求：

> **FastAPI 返回固定结构，前端页面能正常打开、跳转、不报错。**

## 4. FastAPI 内部推荐拆分

推荐最少拆成这些模块：

```text
backend/
  app/
    main.py
    routers/
      projects.py
      stages.py
      parse.py
      outline.py
      generate.py
      document.py
      mock_extra.py
    services/
      project_service.py
      parser_service.py
      outline_service.py
      draft_generation.py
      tech_assembly.py
      opencode_client.py
      docx_service.py
      onlyoffice_service.py
    storage/
      postgres_repo.py
      file_repo.py
```

说明：

- `project_service`：项目列表、项目创建、阶段状态
- `parser_service`：解析 `docx/pdf`
- `outline_service`：调用目录生成 skill
- `draft_generation`：兼容旧接口名，转发到技术标正文拼装服务
- `tech_assembly`：准备 S2 JSON、Wiki、素材库导出并调用 `bid-tech-assembler`
- `docx_service`：把章节内容写成 `.docx`
- `onlyoffice_service`：文档 config、save、callback
- `mock_extra.py`：统一承接非 MVP mock 接口

## 5. 前端最少改哪些文件

这次不再重排 `S0-S10` 展示流，所以前端不需要像之前那样大改跳转。当前最少只建议动下面这些文件。

## 5.1 必改

### `sewpg-bid-frontend/src/components/modals/ProjectWizardModal.jsx`

必须改这一处。

原因：

- 当前创建项目时只把文件名传给后端
- 没有把真实文件上传到 FastAPI
- 这样 `S1` 无法做真实解析

要改的内容：

- 把 `projectsAPI.create(payload)` 的入参从普通 JSON 改成 `FormData`
- 项目基础字段继续传
- 真实文件以 `bidFiles` 一起上传

这是当前 MVP 能不能跑通 `S1` 的关键改动。

## 5.2 建议改

### `sewpg-bid-frontend/src/pages/ProjectList.jsx`

这类和旧 mock 网关绑定的报错文案已经完成清理。

统一口径应保持为：

- “请检查 FastAPI 服务是否启动”

后续如果再补提示文案，也不要再引入 `mock-server` 或 `fastapi-mock` 相关说法。

## 5.3 当前可不改

下面这些文件当前可以先不动：

- `sewpg-bid-frontend/src/utils/stageFlow.js`
- `sewpg-bid-frontend/src/App.jsx`
- `sewpg-bid-frontend/src/pages/OutlineReview.jsx`
- `sewpg-bid-frontend/src/pages/GenerateProgress.jsx`
- `sewpg-bid-frontend/src/pages/CoverageHeatmap.jsx`
- `sewpg-bid-frontend/src/pages/CoCreationEditor.jsx`
- `sewpg-bid-frontend/src/pages/FinalExport.jsx`
- `sewpg-bid-frontend/src/api/index.js`

原因：

- 当前决定是保留 `S0-S10` 展示流
- FastAPI 去兼容现有接口形状
- 这样改动最小，联调最稳

## 6. FastAPI 对现有前端接口的承接

FastAPI 优先兼容当前 React 前端已经写好的接口，例如：

- `/api/projects`
- `/api/projects/{id}`
- `/api/projects/{id}/stages`
- `/api/projects/{id}/parse-results`
- `/api/projects/{id}/directory-generation`
- `/api/projects/{id}/outline`
- `/api/projects/{id}/fill-generation`
- `/api/projects/{id}/document`
- `/api/projects/{id}/final-document`

内部推荐映射：

| 前端接口 | FastAPI 内部语义 |
|---|---|
| `POST /api/projects` | `create_project + upload_bid_files` |
| `POST /api/projects/{id}/parse-results/run` | `run_parse` |
| `POST /api/projects/{id}/directory-generation/run` | `generate_outline` |
| `PUT /api/projects/{id}/outline` | `save_reviewed_outline` |
| `POST /api/projects/{id}/outline/confirm` | `confirm_outline` |
| `POST /api/projects/{id}/fill-generation/run` | `assemble_tech_bid` |
| `GET /api/projects/{id}/coverage` | `get_assembly_material_coverage` |
| `GET /api/projects/{id}/document` | `build_onlyoffice_config` |
| `POST /api/projects/{id}/document/callback` | `save_latest_docx` |
| `GET /api/projects/{id}/final-document` | `download_latest_docx` |

## 7. 推荐执行顺序

按下面顺序最稳：

1. 搭 FastAPI 骨架
2. 接 `PostgreSQL + 本地文件目录`
3. 先打通 `S0/S1/S2/S3`
4. 再打通 `S7/S8/S9/S10`
5. 再补 `S4/S5/S6` 的 mock / 承接接口
6. 最后只改 `ProjectWizardModal.jsx` 和少量提示文案

## 8. 一句话总结

> **现阶段最优路线不是重做前端，而是保留完整 `S0-S10` 展示流，由 FastAPI 统一接住所有 `/api`；关键阶段做真，其余阶段先 mock。**
