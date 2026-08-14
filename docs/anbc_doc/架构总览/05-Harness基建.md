# 05 Harness 基建现状（AI agent 运行时）

> 定位：回答「我们的 agent 基建搭得怎么样」。按组成清单 → 调用链 → 部署形态 → 短板清单组织，结论均可追溯到代码。
> 事实来源：`code/sewpg-bid-backend/opencode/`、`app/services/agent_engine/`（原 `opencode_client.py` 已拆入该包）、`code/docker-compose*.yml`、`code/scripts/`（2026-08-09 只读核对，2026-08-14 按引擎改造刷新短板 1~6 与 10）。

## 1. 组成总表

| 组件 | 路径 | 职责 | 成熟度 |
|---|---|---|---|
| Skill 库（19 个） | `opencode/skills/` | AI 能力最小封装：SKILL.md（提示词契约）+ `scripts/run_from_manifest.py`（受控入口） | 较成熟；命名/双轨清晰 |
| 阶段命名体系 | `opencode/skills/STAGES.md` | 用户阶段 ↔ 命令别名 ↔ 历史工作目录编号的唯一映射 | 成熟，技术/商务两轨表齐全（harness-11） |
| agent 运行时镜像 | `opencode/Dockerfile` + `docker-entrypoint.sh` + `opencode.json` | opencode-ai@1.18.2（npm 锁版）+ Python 工具链 + skills + 命令别名 | 可用；别名按 `skills/commands.json` 注册表在容器启动时生成 wrapper（harness-09），加 skill 不再改 Dockerfile |
| agent 引擎包 | `app/services/agent_engine/`（engine-01 起由 `opencode_client.py` 拆入） | 后端唯一 LLM 出口：建会话/发 prompt/轮询监管/提前完成判定/JSON 修复；协议/工厂/编排/并发预算分模块 | 已拆包去巨石（短板 1 落点），业务命令经 EarlyCompletionPlan 注入，引擎内不再有业务字面量 |
| 异步任务编排 | `app/workers/redis_worker.py` + `job_queue.py` | Redis 队列单循环 worker，3 类 job（directory/fill/material_cleaning） | 成熟：有锁、inflight 回收、心跳续期 |
| 鉴权承载 | `code/opencode-auth/` | 运行时挂载点，entrypoint 把 auth.json 拷入 opencode home | 已自举（harness-10）：README 写明格式/生成方式/与 OPENCODE_SERVER_PASSWORD 的边界，`.gitkeep` 恢复跟踪，真实 auth.json 被 `.gitignore` 排除 |
| 部署运维脚本 | `code/scripts/` | up-5090 / up-airgap / 离线打包 / 镜像加载 | 成熟，5090 与气隙两条路径都覆盖 |
| compose 编排 | `docker-compose.yml`（opencode 服务段） | 单实例 opencode serve :4096（仅绑 127.0.0.1 回环），健康检查 `/global/health`（带 Basic 鉴权头），共享三卷 | 已有资源限额（cpus/mem_limit）与 OPENCODE_SERVER_PASSWORD 鉴权（短板 5 落点） |

## 2. Skill 清单（19 个 = 技术 10 + 商务 8 + 素材 1）

技术轨：

| Skill | 职责 | 后端调用方 |
|---|---|---|
| bid-tech-tender-structured-parser | S0/S1 招标文件结构化解读 | `parsing.py`（分片链路 + 单会话兜底） |
| bid-tech-outline-generator | 目录生成/调整 | `outline_generation.py`（章节并行） |
| bid-tech-gap-planner | S3 缺口识别（bid-tech-gap-plan-v1） | 经 `OpencodeEngine.run_bid_tech_gap_planner_with_trace` |
| bid-tech-table-filler | S3 空副表原样填写，标黄待补 | `technical_gap_ai_fill.py` |
| bid-tech-word-placeholder-filler | S3 待填 Word 占位符填写 | 同上链路 |
| bid-tech-fact-curator | 事实表 AI 复核（只产待确认建议） | `technical_fact_curator.py` |
| bid-tech-assembler | S4 正文 docx 组装 | 装配链路 |
| bid-tech-format-cleaner | 成稿格式清洗 | 格式清洗服务 |
| bid-tech-wiki-material-builder | 按三级索引重建素材 Wiki | Wiki 生成链路 |
| bid-tech-tag-importer | 标签导入模糊匹配兜底（只匹配不写库） | `material_tag_import_fuzzy.py` |

商务轨（8）：bid-business-tender-structured-parser / outline-generator / gap-planner / table-fill / assembler / format-cleaner / template-extractor / wiki-material-builder，调用方对应 `parsing.py`、`outline_generation.py`、`business_gap_planning.py`、`business_assembly.py`、`business_template_extractor.py`、`business_wiki_generation.py`。

素材轨（1）：bid-material-format-cleaner（入库清洗，worker `material_cleaning` job）。

历史遗留 `bid-draft-sections-json`（原 `opencode/.opencode/skills/`）已删除（deadcode-02）。

## 3. 调用链（一次 AI 动作的完整路径）

```
前端按钮 → api/routes/* → service
  1) 后端先跑确定性 prepare：写 manifest + 导航索引到共享卷（parsed/documents）
  2) OpencodeEngine.create_session()   POST http://opencode:4096/session
  3) OpencodeEngine.send_prompt()      POST /session/{id}/message（含 providerID/modelID）
→ opencode 容器内 agent 加载 SKILL.md
  → Bash 调命令别名 → run_from_manifest.py / s1parse_router.py
  → 中间产物经 s1parse submit 等写回共享卷
→ 后端轮询监管 _send_prompt_with_session_polling（agent_engine/opencode_engine.py:608）
  - 0.5s 轮询 messages，10s 心跳；idle 超时 max(120, min(timeout, 900)) → abort
  - early_tool_command（s1parse-finalize / s2outline-finalize / businessassemble…）
    检测到受控命令 stdout 完成即提前返回，不等 agent 读完大 JSON
→ 后端解析返回 JSON（_repair_json_payload 兜底）或直接读卷上产物
```

并发治理已统一（短板 2 落点）：进程级单一 `AGENT_CONCURRENCY_BUDGET` 预算（`agent_engine/concurrency.py`），引擎请求槽、S1 分片、目录章节与进程型引擎均从它派生，不再各池相加。配置链：DB 系统设置 → 环境变量回退。

权限模型（`opencode.json`）：skill/bash allow，task/read/edit deny，external_directory 白名单四目录；entrypoint 运行时强制重注入，三层优先级 runtime.json > INTERNAL_LLM 环境 > legacy 环境回退。

## 4. 部署形态

- compose 主层：opencode 单实例，端口只绑 `127.0.0.1:4096`，挂 `opencode-auth`（ro）+ uploads（ro）/documents/parsed 三卷 + 两个持久卷；fastapi/worker 侧 `AGENT_CONCURRENCY_BUDGET:-8`、`S1_PARSE_SHARD_CONCURRENCY:-7`；opencode 已有 `cpus`/`mem_limit` 限额与 `OPENCODE_SERVER_PASSWORD` 服务端 Basic 鉴权（engine-10）。
- 5090 差异层（25 行）只改 docling-worker 与 ocr 的 GPU 绑定（显式 `device_ids: ["0"]`），opencode 无 5090 专属取值——agent 走远端 LLM 网关，不吃本地 GPU。

## 5. 短板清单（按严重度，建议作为下一阶段基建改造项）

1. **客户端巨石化、业务特判下沉**：✅ 已解决——`opencode_client.py` 已拆为 `app/services/agent_engine/` 包（协议/工厂/编排/并发分模块），`s1parse-finalize` 等业务命令改由调用方经 `EarlyCompletionPlan` 注入，`opencode_engine.py` 不再出现业务字面量。
2. **并发治理割裂**：✅ 已解决——统一为进程级单预算 `AGENT_CONCURRENCY_BUDGET`（`agent_engine/concurrency.py`，默认 8），引擎请求槽、S1 分片、目录章节、codex/pi 进程槽全部从它派生，实际并发不再超标。
3. **生成中途无重试**：✅ 已解决——轮询监管链路 `_poll_session_messages` 带断线重连与断线耗时上报（`agent_engine/opencode_engine.py`），长任务不再一次抖动整轮作废。
4. **会话只建不删**：✅ 已解决——引擎协议新增 `delete_session`（`agent_engine/base.py`），修复/结束路径经 `delete_session_quietly` 回收会话；卷数据另有 `code/scripts/cleanup-opencode-data.sh` 清理策略。
5. **opencode 端口无鉴权暴露**：✅ 已解决（engine-10）——4096 只绑 `127.0.0.1` 回环，`OPENCODE_SERVER_PASSWORD` 启用 serve 原生 Basic 鉴权（5090 必填、空值 fail-fast），容器加 `cpus`/`mem_limit` 限额。
6. **同步阻塞模型**：✅ 已解决（engine-03）——引擎/编排全量异步化，`httpx.AsyncClient` + 每会话一个 asyncio task，daemon 轮询线程已消除。
7. **超时双轨混乱**：`OPENCODE_TIMEOUT_SEC=1800` 与系统设置 timeoutMs（默认 30s）并存，靠 `max(configured_read, idle+60)` 临时缝合。
8. **模型兼容逻辑多处重复**：`big-pickle → deepseek-v4-flash` 回退同时写在 `config.py:17-18`、`docker-entrypoint.sh:24-36`、`:66-69`、`:138-141` 共 4 处，需同步维护。
9. **skill 注册即改镜像**：✅ 已解决（harness-09）——命令别名迁到 `skills/commands.json` 注册表，`docker-entrypoint.sh` 的 `register_skill_commands` 在每次容器启动时生成 wrapper（含子命令白名单，白名单外 exit 64），Dockerfile printf 固化块已删（170→44 行）；新增 skill 只需加目录 + 登记注册表。
10. **opencode-auth 空壳**：✅ 已解决（harness-10）——`code/opencode-auth/` 已恢复占位（`.gitkeep` + README），auth.json 的格式/生成方式/与 `OPENCODE_SERVER_PASSWORD` 的边界已写清，真实凭证由 `.gitignore` 排除。
11. **STAGES.md 商务轨缺失**：✅ 已解决（harness-11）——商务轨 8 个别名（btplnav/business-outline/businessgap/businesstablefill/businessassemble/businessformat + 共享路由 s1parse/wikibuild）已按技术轨同格式补入 `skills/STAGES.md` 第二张表，与 `commands.json` 由测试强制对齐。

## 6. 一句话结论

Harness 已完成「单 LLM 出口 + skill 化封装 + 共享卷大文件交换 + Redis 异步编排 + 轮询监管/提前完成」的主干闭环，技术轨尤其成熟；2026-08 引擎改造已消化客户端巨石、并发割裂、重试/会话回收、端口鉴权、同步阻塞、auth 自举六块欠账，harness-09/11 又消化 skill 注册改镜像与 STAGES 商务轨两块，剩余短板为 7、8（超时双轨、模型兼容重复）。

> 文档漂移勘误（2026-08-12 以代码复核）：`modules/opencode_client.md` 行数已更正为 2817；`00-系统全景.md` 默认模型已更正为 deepseek-v4-flash。2026-08-14 再核：短板 1~6 与 10 已随引擎改造与 harness-10 落地（见 §5 各项落点），短板 9、11 随 harness-09/11 落地，仅 7、8 仍存在，详见 `docs/plan/analysis/20260812-系统性重构.md`。
