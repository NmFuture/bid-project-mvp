# opencode_client（A0 起为 agent_engine/opencode_engine）

| | |
|---|---|
| 源文件 | `code/sewpg-bid-backend/app/services/agent_engine/opencode_engine.py`（A0 迁入，原 `app/services/opencode_client.py`） |
| 层级 | 服务层 |
| 领域 | 解析与AI引擎 |
| 行数 | 2585 |

**职责**: opencode（LLM Agent 运行时）的 HTTP 引擎：建会话、发 prompt、轮询会话进度、抽取结构化回复。后端所有 LLM 调用的唯一出口。

- engine-01（A0）纯改名迁入 `agent_engine` 包：`OpencodeClient` → `OpencodeEngine`，`run_bid_*` / `generate_*_with_trace` 方法名与签名不变，行为零变化。
- 同包新增：`base.py`（`AgentEngine` 协议 + `ToolCompletedEvent`/`EngineRunResult`，同步签名起步）、`factory.py`（`AgentEngineFactory` 按 `AGENT_ENGINE` 环境变量实例化，默认 `opencode`，`codex`/`pi` 暂抛 `NotImplementedError`）。
- §5 公共能力下沉至同包 `json_utils.py`（JSON 修复/解析）、`trace.py`（输出轨迹留痕）、`errors.py`（错误归一化），函数体未改，`OpencodeEngine` 以类属性引用保持原访问形态。

## Input（输入）
- 构造参数缺省从 `system_settings_service.get_opencode_model_config_sync()`（系统设置页可改）回退到 `core.config`（`OPENCODE_BASE_URL`=http://opencode:4096、模型默认 deepseek-v4-flash、超时 1800s）。
- `send_text_prompt(title, prompt_text)`、`generate_outline_with_trace(prompt, callbacks)`、`generate_draft_sections_with_trace(...)` 等：调用方拼好的 prompt 文本。

## Output（输出）
- `{sessionId, providerId, modelId, reply, opencodeOutput(执行轨迹)}`；目录生成返回解析后的 outline JSON（summary+nodes）；支持 `session_ready_callback`/`stream_callback` 把会话进度流出去（技术标目录 SSE 的来源）。
- 错误统一转 RuntimeError（对用户文案为「futurecode 超时/失败」）。

## 调用链
- **上游**: `outline_generation`、草拟/填写/Wiki 生成等 AI 类服务（business/technical 两轨）。
- **下游**: opencode 容器 HTTP `/session`、`/session/{id}/message`；`system_settings_service`；同包 `json_utils`/`trace`/`errors`。

## 中间数据与状态
- opencode 会话（session_id）；执行轨迹 `opencodeOutput` 随结果落入运行态供前端展示；Skill 大文件交换走共享数据卷（uploads/documents/parsed），不经此 HTTP 通道。
