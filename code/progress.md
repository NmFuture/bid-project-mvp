# progress.md

> 当前用途：记录当前状态、验证基线和下一步。历史 MVP 联调流水和旧接口记录不再放在当前正文；需要追溯时查 git 历史或 `doc/archive/2026-05-26-old-docs/`。
> 更新日期：2026-05-26

## 1. 当前状态

文档已经收口为 4 份：

- `doc/值得留下来的内容.md`
- `doc/代码结构梳理.md`
- `doc/需求梳理.md`
- `doc/研发计划.md`

代码主线已经形成技术标和商务标双轨：

```text
技术标入口 -> 技术标页面 -> 技术标 API -> 技术标 service -> 技术标 Skill -> 技术标素材/Wiki -> 技术标文档/共创/下载

商务标入口 -> 商务标页面 -> 商务标 API -> 商务标 service -> 商务标 Skill -> 商务标素材/Wiki -> 商务标文档/共创/下载
```

当前保留的工作重点：

- 技术标真实样本端到端验收。
- 商务标真实样本端到端验收。
- 附表填写、待填写 Word、事实库、证据链、格式导出质量。
- 商务评分、报价、符合性、附件、承诺、否决项、业绩链路验证。
- 后端角色、工作区、项目类型强授权。
- 临时文件、文档工作区、MinIO 对象的项目删除清理和 TTL 策略。

## 2. 本轮文档和命名收口

- 旧文档已归档到 `doc/archive/2026-05-26-old-docs/`。
- 根 `README.md` 已改为 4 份当前文档入口。
- `doc/代码结构梳理.md` 已梳理页面、API、services、OpenCode/Skill、素材库/模板/Wiki 存储范围。
- 技术标解析 Skill 已统一为 `bid-tech-tender-structured-parser`。
- 商务目录 Skill 已统一为 `bid-business-outline-generator`。
- 素材清洗通用 Skill 已统一为 `bid-material-format-cleaner`。
- `bid-tech-format-cleaner/SKILL.md` 已补齐。
- 技术标运行态恢复已支持从项目 workspace 下既有 `toc.json` 恢复目录状态，和商务标行为对齐。

## 3. 当前验证基线

在 `/Users/wlb/Agent/bid-project/code/sewpg-bid-backend` 下已执行：

```bash
PYTHONPATH=. pytest tests/test_s1parse_router.py tests/test_s1parse_router_script.py tests/test_business_parse_skill_script.py tests/test_parse_pipeline.py::ParsePipelineTests::test_s1parse_skill_script_outputs_same_multifile_structured_contract opencode/skill/bid-tech-format-cleaner/tests/test_tech_format_cleaner.py
```

结果：`12 passed`。

```bash
PYTHONPATH=. pytest tests/test_business_material_library_rules.py -k material_cleaning_uses_short_paths_for_long_names
```

结果：`1 passed, 36 deselected`。

```bash
PYTHONPATH=. pytest tests/test_directory_generation.py
PYTHONPATH=. pytest opencode/skill/bid-business-outline-generator/scripts/test_run_from_manifest.py opencode/skill/bid-business-outline-generator/scripts/test_prepare_history_bid_outline_inputs.py opencode/skill/bid-business-outline-generator/scripts/test_prepare_tender_map_inputs.py opencode/skill/bid-business-outline-generator/scripts/test_resolve_source_text_candidates.py opencode/skill/bid-business-outline-generator/scripts/test_extract_format_children_candidates.py
```

结果：目录生成 `30 passed`；商务目录 Skill 脚本组合 `35 passed`。

```bash
PYTHONPATH=. pytest tests/test_bid_material_scope_services.py -k "runtime_recovery or technical_runtime_can_recover_directory"
git diff --check
```

结果：运行态恢复聚焦组合 `2 passed`；diff 检查通过。

## 4. 下一步

1. 启动当前 Docker 环境。
2. 用真实技术标样本跑完整流程，记录阻断点。
3. 用真实商务标样本跑完整流程，记录阻断点。
4. 把阻断点转成研发任务，优先处理影响交付的解析、目录、填表、正文生成、格式和导出问题。
5. 单独补生产权限和临时/对象存储清理策略。
