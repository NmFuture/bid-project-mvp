# 05 Harness 基建现状（AI agent 运行时）

> 定位：回答「我们的 agent 基建搭得怎么样」。按组成清单 → 调用链 → 部署形态 → 短板清单组织，结论均可追溯到代码。
> 事实来源：`code/sewpg-bid-backend/opencode/`、`app/services/opencode_client.py`、`code/docker-compose*.yml`、`code/scripts/`（2026-08-09 只读核对）。

## 1. 组成总表

| 组件 | 路径 | 职责 | 成熟度 |
|---|---|---|---|
| Skill 库（19 个） | `opencode/skills/` | AI 能力最小封装：SKILL.md（提示词契约）+ `scripts/run_from_manifest.py`（受控入口） | 较成熟；命名/双轨清晰 |
| 阶段命名体系 | `opencode/skills/STAGES.md` | 用户阶段 ↔ 命令别名 ↔ 历史工作目录编号的唯一映射 | 成熟，但只覆盖技术轨（商务表待补） |
| agent 运行时镜像 | `opencode/Dockerfile` + `docker-entrypoint.sh` + `opencode.json` | opencode-ai@1.18.2（npm 锁版）+ Python 工具链 + skills + 命令别名 | 可用；别名是 Dockerfile printf 出的 wrapper，加 skill 要改镜像 |
| agent 客户端 | `app/services/opencode_client.py`（2817 行） | 后端唯一 LLM 出口：建会话/发 prompt/轮询监管/提前完成判定/JSON 修复 | 功能完备但已臃肿，仍在增长（2026-08-12 复核 2817 行） |
| 异步任务编排 | `app/workers/redis_worker.py` + `job_queue.py` | Redis 队列单循环 worker，3 类 job（directory/fill/material_cleaning） | 成熟：有锁、inflight 回收、心跳续期 |
| 鉴权承载 | `code/opencode-auth/`（已不在仓库，git 不跟踪空目录） | 运行时挂载点，entrypoint 把 auth.json 拷入 opencode home | 半成品：无内容无说明，新环境无法自举 |
| 部署运维脚本 | `code/scripts/` | up-5090 / up-airgap / 离线打包 / 镜像加载 | 成熟，5090 与气隙两条路径都覆盖 |
| compose 编排 | `docker-compose.yml:279-339` | 单实例 opencode serve :4096，健康检查 `/global/health`，共享三卷 | 可用但无资源限制 |

## 2. Skill 清单（19 个 = 技术 10 + 商务 8 + 素材 1）

技术轨：

| Skill | 职责 | 后端调用方 |
|---|---|---|
| bid-tech-tender-structured-parser | S0/S1 招标文件结构化解读 | `parsing.py`（分片链路 + 单会话兜底） |
| bid-tech-outline-generator | 目录生成/调整 | `outline_generation.py`（章节并行） |
| bid-tech-gap-planner | S3 缺口识别（bid-tech-gap-plan-v1） | 经 `OpencodeClient.run_bid_tech_gap_planner_with_trace` |
| bid-tech-table-filler | S3 空副表原样填写，标黄待补 | `technical_gap_ai_fill.py` |
| bid-tech-word-placeholder-filler | S3 待填 Word 占位符填写 | 同上链路 |
| bid-tech-fact-curator | 事实表 AI 复核（只产待确认建议） | `technical_fact_curator.py` |
| bid-tech-assembler | S4 正文 docx 组装 | 装配链路 |
| bid-tech-format-cleaner | 成稿格式清洗 | 格式清洗服务 |
| bid-tech-wiki-material-builder | 按三级索引重建素材 Wiki | Wiki 生成链路 |
| bid-tech-tag-importer | 标签导入模糊匹配兜底（只匹配不写库） | `material_tag_import_fuzzy.py` |

商务轨（8）：bid-business-tender-structured-parser / outline-generator / gap-planner / table-fill / assembler / format-cleaner / template-extractor / wiki-material-builder，调用方对应 `parsing.py`、`outline_generation.py`、`business_gap_planning.py`、`business_assembly.py`、`business_template_extractor.py`、`business_wiki_generation.py`。

素材轨（1）：bid-material-format-cleaner（入库清洗，worker `material_cleaning` job）。

另有一个历史遗留 `bid-draft-sections-json` 在 `opencode/.opencode/skills/`，不在主目录，疑似未清理旧物。

## 3. 调用链（一次 AI 动作的完整路径）

```
前端按钮 → api/routes/* → service
  1) 后端先跑确定性 prepare：写 manifest + 导航索引到共享卷（parsed/documents）
  2) OpencodeClient.create_session()   POST http://opencode:4096/session
  3) OpencodeClient.send_prompt()      POST /session/{id}/message（含 providerID/modelID）
→ opencode 容器内 agent 加载 SKILL.md
  → Bash 调命令别名 → run_from_manifest.py / s1parse_router.py
  → 中间产物经 s1parse submit 等写回共享卷
→ 后端轮询监管 _send_prompt_with_session_polling（opencode_client.py:979）
  - 0.5s 轮询 messages，10s 心跳；idle 超时 max(120, min(timeout, 900)) → abort
  - early_tool_command（s1parse-finalize / s2outline-finalize / businessassemble…）
    检测到受控命令 stdout 完成即提前返回，不等 agent 读完大 JSON
→ 后端解析返回 JSON（_repair_json_payload 兜底）或直接读卷上产物
```

并发入口三处：S1 技术分片 ThreadPoolExecutor（默认 7 槽）；S2 目录章节 6+1 并行、按 `OPENCODE_CHAPTER_BASE_URLS` 轮询分发多实例；其余走全局 `_OPENCODE_REQUEST_SLOTS`。配置链：DB 系统设置 → 环境变量回退。

权限模型（`opencode.json`）：skill/bash allow，task/read/edit deny，external_directory 白名单四目录；entrypoint 运行时强制重注入，三层优先级 runtime.json > INTERNAL_LLM 环境 > legacy 环境回退。

## 4. 部署形态

- compose 主层：opencode 单实例，挂 `opencode-auth`（ro）+ uploads（ro）/documents/parsed 三卷 + 两个持久卷；fastapi/worker 侧 `OPENCODE_MAX_CONCURRENCY:-1`、`S1_PARSE_SHARD_CONCURRENCY:-7`；**无 deploy.resources 资源限制**。
- 5090 差异层（25 行）只改 docling-worker 与 ocr 的 GPU 绑定（显式 `device_ids: ["0"]`），opencode 无 5090 专属取值——agent 走远端 LLM 网关，不吃本地 GPU。

## 5. 短板清单（按严重度，建议作为下一阶段基建改造项）

1. **客户端巨石化、业务特判下沉**：2817 行硬编码识别 `s1parse-finalize`/`btplnav-finalize`/`factcurate` 等业务命令（如 `opencode_client.py:1179-1224`），每加一类 agent 任务要改公共客户端，回归高发。
2. **并发治理割裂**：三个信号量池（全局 / S1 分片 / 目录章节）互不知晓，实际并发=各池之和；代码默认 `OPENCODE_MAX_CONCURRENCY=8`（`config.py:245`）与 compose 默认 1 相反；目录章节 6+1 是硬编码常量（`outline_generation.py:45-46`）。
3. **生成中途无重试**：重试只覆盖 create_session；send_prompt 任何错误直接失败，长任务（上限 1800s）一次抖动整轮作废。
4. **会话只建不删**：只有 abort_session，无 DELETE；`opencode_data` 卷无限增长，无清理策略。
5. **opencode 端口无鉴权暴露**：4096 映射宿主机，客户端不带 auth header；容器内 bash allow + 无资源限额 = 内网任意人可让 agent 无上限执行 shell。
6. **同步阻塞模型**：httpx 同步 Client + 每会话一个 daemon 线程轮询，在 async FastAPI 里靠线程池消化；daemon 线程静默死亡的竞态已被实战踩过。
7. **超时双轨混乱**：`OPENCODE_TIMEOUT_SEC=1800` 与系统设置 timeoutMs（默认 30s）并存，靠 `max(configured_read, idle+60)` 临时缝合。
8. **模型兼容逻辑多处重复**：`big-pickle → deepseek-v4-flash` 回退同时写在 `config.py:17-18`、`docker-entrypoint.sh:24-36`、`:66-69`、`:138-141` 共 4 处，需同步维护。
9. **skill 注册即改镜像**：命令别名在构建期 printf 固化且内嵌子命令白名单，无注册机制。
10. **opencode-auth 空壳**：目录已不在仓库（git 不跟踪空目录），auth.json 来源/格式/生成方式无文档，仅 `.env.example` 一个变量名。
11. **STAGES.md 商务轨缺失**：商务别名（btplnav/businessgap 等）无统一映射表，散在 Dockerfile 里。

## 6. 一句话结论

Harness 已完成「单 LLM 出口 + skill 化封装 + 共享卷大文件交换 + Redis 异步编排 + 轮询监管/提前完成」的主干闭环，技术轨尤其成熟；主要欠账在**客户端可维护性、并发配置割裂、会话生命周期无回收、opencode 端口无鉴权暴露**四点。

> 文档漂移勘误（2026-08-12 以代码复核）：`modules/opencode_client.md` 行数已更正为 2817；`00-系统全景.md` 默认模型已更正为 deepseek-v4-flash。上述 11 项短板逐项复核**全部仍存在**（仅 PeripheralStore 替换完成、旧代码待删），详见 `docs/plan/analysis/20260812-系统性重构.md`。
