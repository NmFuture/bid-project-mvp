# MVP 联调计划

## 目标

最终跑通：

```text
web -> fastapi -> opencode -> onlyoffice
```

最终部署形态：

```text
docker compose
  - web
  - fastapi
  - opencode
  - onlyoffice
```

## 步骤

- [x] 1. 完善 API 文档
  - 对齐当前前端接口名和字段
  - 明确真实阶段与 mock 阶段

- [x] 2. 搭 FastAPI 骨架
  - 建立 `sewpg-bid-backend/app`
  - 承接当前前端会先调用的基础接口
  - 跑通 S0 / S1 / S2 / S3 / S7 / S9 / S10 的骨架返回

- [x] 3. 接入 OnlyOffice
  - 本机 Docker 部署 OnlyOffice Document Server
  - FastAPI 接真实 `document / callback / final-document`
  - 前端 S9 嵌入真实 OnlyOffice 并验证保存回写
  - 当前状态：已完成，S9 已实测可编辑、保存、回写

- [x] 4. 接入 opencode
  - Docker 部署 `opencode serve`
  - S2 接目录生成 skill
  - S2 采用“投标模板目录优先，招标要求修正”的生成策略
  - S7 接初稿生成能力
  - 当前状态：Docker 中的 `opencode` 已部署并 smoke test 通过；S2 / S7 均已接入真实生成

- [x] 4.5 打通 S4 / S5 / S6 mock 流程
  - FastAPI 持久化承接 `gaps-detection / gaps / materials/submissions / review-items`
  - S4 基于当前目录生成缺口 mock 数据
  - S5 支持补料、标记已补录/跳过、提交审核
  - S6 支持生成审核预览文档并返回 OnlyOffice 会话

- [x] 4.8 打通 S8 mock 承接
  - FastAPI 新增 `GET /api/projects/{id}/coverage`
  - S8 基于 S7 章节 `generationMode` 生成覆盖树、部分覆盖项、未覆盖项
  - 保证 `S7 -> S8 -> S9 -> S10` 可以继续走通

- [ ] 5. 收成最终 Docker Compose
  - `web`
  - `fastapi`
  - `opencode`
  - `onlyoffice`
  - 明确 `.env` / 环境变量口径，至少包含：
    - `OPENCODE_BASE_URL`
    - `OPENCODE_PROVIDER_ID`
    - `OPENCODE_MODEL_ID`
    - 外部模型 `API_KEY`
  - 保证部署使用者可以自行配置 `opencode` 的 `baseUrl / apiKey`
