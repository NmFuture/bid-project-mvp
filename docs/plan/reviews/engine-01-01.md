# engine-01 review 01（A0：AgentEngine 边界 + OpencodeClient → OpencodeEngine 纯改名）

- 审查对象：`task/engine-01` 分支 commit `bb16e33`
- 审查基准：`docs/plan/tasks/engine-01.md`、`docs/20260813-AgentEngine多内核引擎改造方案.md`（§2/§3/§5/§6 A0/§7）、`docs/plan/tasks/harness-01.md`、根 `AGENTS.md`
- 审查方式：`git show/diff` 全量审读 + AST 级逐函数对比（`git show HEAD~1:.../opencode_client.py` 对照新包）+ 全仓 grep + 与 CI 对齐环境复跑测试

## 验证记录（reviewer 复跑）

- 定向集（任务文件 verification 命令，`-k "opencode or outline or parsing or fact"`）：**549 passed, 96 subtests passed, 0 failed**。
- 全量 `-m "not integration"`：**2167 passed, 30 deselected, 107 subtests passed, 0 failed**（5m39s）。失败集合为 0，与基线一致。
- `git diff HEAD~1 HEAD --check` 通过；工作树干净。
- 纯改名验证（核心结论）：
  - 下沉 9 函数 AST 级逐字对比：`trace.py` 3 个、`errors.py` 3 个、`json_utils._balanced_json_object_candidates` 完全一致；`_repair_json_payload` 仅缩进差异（类方法 → 模块函数）；`_parse_json_payload` 唯一实质差异是类内引用 `OpencodeClient._balanced_json_object_candidates` 改为模块级引用——纯移动的必然适配，无语义变化。
  - `opencode_engine.py` 类主体：旧类 88 方法 → 新类 79 方法，差值恰为下沉的 9 个；其余 79 个方法（类名归一后）零差异，模块级常量/语句零差异。
  - 全部调用方 diff 仅为 import 路径与类名替换，无逻辑改动。

## Findings

### F1（P3，non-blocking）commit message 测试数与复跑不一致

- 位置：commit `bb16e33` message（"2265 passed"）；任务文件 `docs/plan/tasks/engine-01.md` verification 节。
- 现象：reviewer 用任务文件给定的 CI 对齐命令复跑，收集总数 2197（2167 passed + 30 deselected），与 message 声明的 2265 对不上，可能开发时选择器/环境不同。
- 影响：失败集合均为 0，结论不受影响；仅声明数字口径偏差，后续 commit message 建议写清实际命令与收集数。

### F2（P3，non-blocking）A0 阶段 OpencodeEngine 尚不满足 AgentEngine 协议

- 位置：`code/sewpg-bid-backend/app/services/agent_engine/base.py:54-80`（协议）vs `opencode_engine.py:87`（`create_session` 返回 `dict` 而非协议的 `str`）、`:844`（`list_session_messages` 与协议 `list_messages` 名称不一致）、缺 `run_session`/`delete_session`；`factory.py:22` 返回标注 `-> AgentEngine` 为名义类型。
- 说明：符合 A0「纯改名、行为零变化」定位，协议对齐已排期在 engine-02（`run_session`/`on_tool_completed`，见 `docs/plan/tasks/engine-02.md:35`）与 engine-03（async 化翻协议）。`Protocol` 未加 `runtime_checkable`，无运行期风险；仅提示后续波次必须完成对齐，否则工厂标注长期失真。

### F3（P3，non-blocking）调用方清单口径偏差

- 位置：commit message「16 处调用方」；`docs/plan/tasks/engine-01.md:35` 现状清单。
- 现象：实际改动 17 个 service 文件 + `code/sewpg-bid-backend/scripts/technical_wiki_preview.py`；其中 script 未列入任务现状清单，`system_settings.py` 仅为注释同步（`OpencodeClient` → `OpencodeEngine` 字样）。
- 影响：改动本身必要且正确（script 引用了被删除的旧模块，不改即坏）；仅清单/message 口径不精确。

### F4（P3，non-blocking）已知遗留引用（与 review 要点 3 一致，登记备查）

- 位置：`code/sewpg-bid-backend/graft/`（索引与 `.graph/wiring.json`）；`docs/anbc_doc/架构总览/` 的 `05-Harness基建.md`、`00-系统全景.md`、`04-技术标操作串讲.md`、其它 modules 卡片 downstream 列表、两个 HTML、`_data/business.json`/`common.json`；`docs/archive/` 与历史方案/handoff 文档；`docs/plan/tasks/harness-0*.md`、`engine-0*.md`（历史行号引用）。
- 说明：graft/ 索引与架构总览其它文档为已知遗留，待索引重建/文档刷新波次处理；archive 与任务文件引用旧路径属历史描述，不应回改。生产代码与测试零残留（全仓 grep 确认，唯一例外是新包 docstring 的出处说明）。`_data/bid_parse.json:18` 卡片名保留 `opencode_client`，故其它 `_data` 的 downstream 引用在卡片名口径下仍自洽。

### F5（P3，non-blocking）AgentEngineFactory 在 A0 无生产调用方

- 位置：`code/sewpg-bid-backend/app/services/agent_engine/factory.py`（全仓 grep 无 `AgentEngineFactory` 其它引用）。
- 说明：符合 §6 波次规划——A0 只立插入点，接线在后续波次（orchestrator/引擎切换）。非缺陷，登记以便后续任务核对接线点。

## 审查要点逐项结论

1. **纯改名/纯移动**：通过。AST 级对比确认除类名/导入路径/文件移动外无逻辑改动（差异明细见上）。
2. **base.py / factory.py contract**：通过。协议为同步签名、模块 docstring 完整注明 §3 async 目标形态、`early_tool_command: str` 保留现状语义（符合任务文件改造方案 1 的拍板）；factory 默认 `opencode`、`codex`/`pi` 抛 `NotImplementedError`、未知值 `ValueError`，配置分层注释符合根 AGENTS.md。
3. **残留引用**：生产代码/测试零残留；遗留范围与已知清单一致（F4）。
4. **stub/mock/fake 残留与超范围改动**：无。`agent_engine/` 包内无任何 fake/stub；测试中 `_FakeOpencodeEngine` 为既有测试替身 `_FakeOpencodeClient` 的同步改名；全部改动文件均在任务声明范围内（F3 的 script 为清单遗漏的必要改动）。
5. **类属性别名挂回**：通过。`opencode_engine.py:48-57` 覆盖全部 9 个下沉函数，包装形态与原一致（`_repair_json_payload`/`_build_output_trace` 保留 `self` 作实例方法，其余 `staticmethod`）；内部调用点仍走 `self._xxx`/`OpencodeEngine._xxx`，测试注入点全部同步（`tests/test_opencode_engine.py:304` 直接调 `OpencodeEngine._parse_json_payload`、`tests/test_technical_report_contract.py:14,170` 隔离加载路径指向 `json_utils.py`、各 patch 目标均指向新模块路径）。

## 结论

**pass**。A0 contract（纯改名、行为零变化、测试保持绿）全部满足，无 blocking findings；5 条 P3 均为口径/排期/已知遗留登记，不阻塞交付。
