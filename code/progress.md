# progress.md

> 当前用途：只记录双轨独立化之后的最新进度口径。
> 历史 MVP 联调过程和旧接口调用记录不再放在当前工作树中，避免新会话和 AI 把旧通用入口当成现状；需要追溯时查 git 历史。
> 更新日期：2026-05-25

## 当前主线

技术标和商务标正在拆成两条独立生产线：

```text
技术标入口 -> 技术标页面 -> 技术标 API -> 技术标 service -> 技术标 Skill -> 技术标素材/Wiki -> 技术标文档/导出

商务标入口 -> 商务标页面 -> 商务标 API -> 商务标 service -> 商务标 Skill -> 商务标素材/Wiki -> 商务标文档/导出
```

权威计划看：

- `/Users/wlb/Agent/bid-project/doc/31-技术标与商务标双轨独立化实施计划.md`
- `/Users/wlb/Agent/bid-project/doc/README.md`

## 已完成到哪里

- 前端旧根入口和 workspace 内部旧别名已清理，当前从 `/parse/technical`、`/parse/business`、`/workspace/tech/...`、`/workspace/business/...` 进入。
- 商务标和技术标页面已按 workspace 拆分，阶段进度组件也已拆成 business/technical 两套。
- 后端旧通用 route 文件已移除，当前业务入口挂在 business/technical 两组 route 上。
- 项目、解析、目录、生成、文档、OCR、素材库、Wiki、审计、技术标缺口和商务标缺口都已有第一层 business/technical service 边界。
- 旧通用 store、material_store 仍是底层持久化底座，但对外不再作为业务入口直接暴露。
- 素材分类、默认目录、保护目录、清洗状态和技术标旧路径规范化规则已下沉到 `material_taxonomy.py`，`material_store.py` 继续作为持久化底座引用这些规则。
- 技术标投标机型候选已下沉到 `technical_turbine_material_options.py`，不再作为通用 `material_store` 能力暴露；商务标素材不会进入技术标机型候选。
- 技术标素材查询的投标机型过滤已迁到 `technical_material_store.raw_files`，`material_store.raw_files` 不再接收或处理 `turbine_model`，商务标素材查询不会继承技术标机型筛选逻辑。
- 素材上传元数据规则已下沉到 `material_upload_metadata.py`，上传时的标类、素材层级、客户/项目身份、商务固定/其他、清洗状态和技术机型提示不再直接写在 `material_store.raw_upload` 大块流程里。
- Wiki 根节点标类和 scoped 可见性规则已下沉到 `material_wiki_scope.py`，`material_store.wiki_list` 不再内联技术标/商务标根节点判断。
- Wiki 新建节点默认标类规则已下沉到 `material_wiki_scope.py`，新建根节点的技术标/商务标/通用适用范围不再直接写在 `material_store.wiki_create` 里。
- raw 目录规划规则已下沉到 `material_folder_scope.py`，技术/商务根目录、默认三类目录、项目素材根路径、目录层级推断和旧技术目录规范化元数据不再直接写在 `material_store.py` 里。
- RawFolder 素材层级推断包装已下沉到 `material_folder_scope.py`，`material_store.py` 不再保留 `_infer_material_tier_from_folder` 静态工具。
- raw 权限展示规则已下沉到 `material_folder_scope.py`，技术标/商务标素材根权限和可编辑动作不再直接写在 `material_store.py` 里；未被 business/technical API 使用的旧 `material_store.raw_permissions` 公开门面已删除。
- 商务标目录骨架规则已下沉到 `material_folder_scope.py`，商务标通用素材固定子目录、客户/项目素材自动子目录和商务定制目录层级判断不再直接写在 `material_store.py` 里。
- 素材身份选项规则已下沉到 `material_identity_options.py`，客户/项目身份归并、项目表 payload 解析和按标类过滤不再直接写在 `material_store.identity_options` 里。
- 素材身份选项读取执行层已下沉到 `material_identity_options_operations.py`，`raw_folders` / `raw_files` / `projects` 读取和项目表容错查询不再直接定义在 `material_store.py` 里。
- raw 文件筛选规则已下沉到 `material_raw_file_filter.py`，项目/客户/标类/素材层级/清洗状态过滤和分页不再直接写在 `material_store.raw_files` 里。
- raw 文件列表查询执行层已下沉到 `material_raw_file_operations.py`，目录递归查询、关键字查询、更新时间排序和筛选 payload 调用不再直接定义在 `material_store.py` 里。
- raw 文件对象执行层已下沉到 `material_raw_object_operations.py`，清洗稿对象清理、清洗任务入队、文件版本归档和原文件/历史版本对象删除不再直接定义在 `material_store.py` 里。
- raw 对象 key 拼接已下沉到 `material_raw_object_operations.py`，`material_store.py` 不再保留 `_raw_object_key` 静态工具。
- raw 文件访问执行层已下沉到 `material_raw_access_operations.py`，原素材下载地址、原素材内容读取、清洗稿 OnlyOffice 预览和清洗稿内容读取不再直接定义在 `material_store.py` 里。
- raw 文件生命周期执行层已下沉到 `material_raw_lifecycle_operations.py`，文件夹创建、文件夹删除和单文件删除不再直接定义在 `material_store.py` 里。
- 未被 business/technical facade 使用的旧通用 raw 清洗重试和清洗稿下载地址门面已删除，`material_store.raw_retry_clean_file` / `raw_download_cleaned_file` 及其对应未使用 operation 不再保留；正式入口只保留双轨清洗稿预览和清洗稿内容下载。
- raw 文件更新执行层已下沉到 `material_raw_update_operations.py`，重命名校验、同名冲突检查、MinIO key 迁移和更新后返回 payload 不再直接定义在 `material_store.py` 里。
- raw 单文件读写入口继续收口，`material_store.raw_update_file` / `raw_delete_file` / `raw_download_file` / `raw_download_content` / `raw_cleaned_preview` / `raw_download_cleaned_content` / `raw_move_file` 均要求显式传入标类，底层 operation 会校验文件或目标目录属于当前标类或通用素材，避免绕过 business/technical facade 操作对方素材。
- raw 上传目标目录推断已下沉到 `material_upload_target.py`，自动目录、层级根目录、scoped 路径和旧目录别名兼容判断不再直接写在 `material_store.raw_upload` 里。
- raw 上传动作元数据已下沉到 `material_upload_metadata.py`，新上传、覆盖和版本上传的 lastAction/lastOperator 写回规则不再直接写在 `material_store.raw_upload` 里。
- raw 上传执行层已下沉到 `material_upload_operations.py`，上传目标落实、白名单校验、相对路径展开、MinIO 写入、同名覆盖/版本处理、旧清洗稿清理和清洗任务入队不再直接定义在 `material_store.py` 里。
- 素材底座 raw 上传/目录骨架入口不再默认技术标，`material_store.raw_upload` / `raw_bootstrap_folders` 及其底层 operation 要求调用方显式传入标类；商务/技术素材 facade 继续分别固定传入商务标/技术标。
- 素材 helper 层隐式标类入口继续收口，身份选项、raw 文件过滤、raw 文件列表查询、Wiki 节点默认适用标类、Wiki 树/列表读取和 raw 移动元数据 helper 不再提供 `bid_type=""` / `destination_bid_type=""` 默认参数；调用方必须显式传入本次操作所属标类。
- 生成填充文案、素材身份选项、技术标装配 manifest、技术标缺口规划/review/legacy 状态中的技术标兜底已统一引用 `bid_type.py` 常量，不再各自写第二份 `"技术标"` 字符串。
- raw 移动元数据规则已下沉到 `material_move_metadata.py`，单文件移动/文件夹移动时的素材层级、标类、客户/项目身份、sourceMinioKey 和 lastAction 更新不再直接写在 `material_store.py` 里。
- raw 移动执行层已下沉到 `material_move_operations.py`，单文件移动、冲突覆盖/版本处理、目录整树移动、MinIO key 迁移和移动后元数据写回不再直接定义在 `material_store.py` 里。
- raw 文件夹移动保护规则已下沉到 `material_folder_scope.py`，基础根目录移动保护和禁止移动到自身/子目录的判断由移动执行层调用，不再直接写在 `material_store.raw_move_folder` 里。
- 素材目录维护执行层已下沉到 `material_folder_maintenance.py`，项目目录骨架初始化、上传目标目录创建、新建目录后的商务定制子目录补齐判断、商务标通用/定制子目录自动补齐、既有商务目录回填和技术标旧目录迁移不再直接定义在 `material_store.py` 里。
- raw 目录持久化执行层已下沉到 `material_raw_folder_operations.py`，根目录初始化、默认目录删除记录、规范目录补齐、路径建目录和嵌套目录创建不再直接定义在 `material_store.py` 里。
- 素材运行表初始化已下沉到 `material_runtime_tables.py`，raw/Wiki/template/auth/settings/audit/OCR 运行表 DDL 和 `ensure_material_runtime_tables` 公开 helper 不再直接写在 `material_store.py` 里；template/settings/audit/auth/OCR/商务缺口规划服务也不再为了建表 import 素材 store。
- raw 更新元数据规则已下沉到 `material_update_metadata.py`，重命名和商务素材 fixed/other 分类更新时的 sourceMinioKey、sourceFileName、businessMaterialKind、businessMaterialKindLabel 和 lastAction 不再直接写在更新执行流程里。
- raw 树展示规则已下沉到 `material_raw_tree.py`，目录树 directFileCount/fileCount 统计和根节点结构不再直接写在 `material_store.raw_tree` 里。
- raw 树读取执行层已下沉到 `material_raw_tree_operations.py`，根目录初始化、目录读取、文件读取和树 payload 调用不再直接定义在 `material_store.py` 里。
- raw 树与目录操作返回树不再先取全量树再由 facade 兜底过滤，`material_store.raw_tree` / `raw_create_folder` / `raw_delete_folder` / `raw_move_folder` 要求显式传入标类，目录创建、删除、移动后的返回树也按本工作区标类生成。
- raw 目录创建/删除/移动继续收口到底层 operation，父级目录、待删除目录、移动源目录和目标父目录都会按显式标类校验，不能绕过 business/technical facade 操作对方素材目录。
- 未被 business/technical API 使用的旧通用 `material_store.structured_*` 门面、`material_structured_operations.py` 执行层和旧 in-memory `PeripheralStore.structured_*` mock 门面已删除；结构化解析数据继续由 S1 解析结果、商务解析资产和缺口模块承接，不再作为旧通用素材库入口暴露。
- Wiki 树展示规则已下沉到 `material_wiki_tree.py`，根节点标类过滤、树节点结构、可见节点集合和默认选中顺序不再直接写在 `material_store.wiki_list` 里。
- Wiki 列表读取执行层已下沉到 `material_wiki_list_operations.py`，Wiki 节点读取、选中文档查询、附件列表拼装和 Wiki 选项返回不再直接定义在 `material_store.py` 里。
- Wiki 节点执行层已下沉到 `material_wiki_node_operations.py`，节点创建、更新、删除、摘要刷新和移动不再直接定义在 `material_store.py` 里。
- Wiki 附件执行层已下沉到 `material_wiki_attachment_operations.py`，附件 key 生成、附件展示 payload、上传、下载、删除和对象存储清理不再直接定义在 `material_store.py` 里。
- Wiki 附件读写入口继续收口，附件上传、内容下载和删除 operation 均校验节点或附件属于当前标类或通用 Wiki；`material_store.wiki_download_attachment_content` 不再提供无标类公共入口。
- Wiki 导入规则已下沉到 `material_wiki_import.py`，导入 mode、根节点 spec、节点默认标题/正文/标签/适用标类和导入结果文案不再直接写在 `material_store.import_generated_wiki_blueprint` 里。
- Wiki 导入执行层已下沉到 `material_wiki_import_operations.py`，自动生成 Wiki 的根节点替换、重复根清理、孤儿平台节点清理、自动子节点刷新、节点 create/upsert 和附件对象清理不再直接定义在 `material_store.py` 里。
- Wiki 自动导入入口继续收口，`material_store.import_generated_wiki_blueprint` 要求显式传入标类，底层会校验生成根节点适用标类与当前工作区一致，并按该标类返回 scoped Wiki 列表。
- 技术标缺口 review 规则已下沉到 `technical_gap_review.py`，`store.py` 中残留的 detection payload、缺口列表映射、review payload、review 文档内容和产物 URL 刷新旧私有方法已删除，不再保留第二份技术标缺口规则。
- 技术标 review 文档状态规则继续下沉到 `technical_gap_review.py`，旧 `store.get_review_items` / `store.prepare_review_document` / `store.confirm_review` 等公开兼容入口已删除，`tech_assembly.py` 直接读取技术标 repository/state/review 模块。
- 技术标覆盖率规则已下沉到 `technical_coverage.py`，`technical_delivery_service.py` 不再 import 通用 `store` 或调用 `store.get_coverage`，旧 `store.get_coverage` 兼容方法已删除，导出完成阶段也通过技术标 project service 更新。
- 文档保存状态规则已下沉到 `bid_document_state.py`，正文保存、强制保存和最终文档 payload 不再直接写在 `store.py` 里。
- 商务标/技术标文档格式状态写回规则已拆到 `business_document_state.py` / `technical_document_state.py`，并由 `bid_document_state.py` 提供统一薄门面；`store.py` 不再直接写 `businessFormatPreset` / `technicalFormatPreset` 等双轨专属字段，也不再直接 import 商务/技术格式状态模块或自行取格式写回时间戳。
- 旧通用 `store.py` 文档状态公开门面已删除，`get_document_state` / `save_document_content` / `force_save_document` / `get_final_document` / `apply_business_document_format` / `apply_technical_document_format` 不再作为绕过双轨文档 flow 的兼容入口存在；测试需要构造文档状态时直接调用 `bid_document_state.py` 状态函数并显式持久化。
- 商务标/技术标文档 service 的格式写回和强制保存状态更新已改为通过 `workspace_project_access.py` 取可写项目，再调用 `bid_document_state.py` 纯状态函数并显式持久化；`business_document_service.py` / `technical_document_service.py` 不再直接 import 通用 `store`。
- 文档 flow 中性底座的文档 payload、正文保存、强制保存、OnlyOffice callback、最终文档和 PDF 文件读取已改为通过双轨项目 service / `workspace_project_access.py` 访问项目运行态或可写状态；`bid_document_flow.py` 不再直接 import 通用 `store`。
- 后端项目阶段规则已下沉到 `project_stage_flow.py`，商务标四步压缩阶段、技术标六步阶段、技术标确认目录后跳过 S3 和旧阶段号映射不再直接写在 `store.py` 里。
- 项目生命周期和展示状态规则已下沉到 `bid_project_state.py`，新建项目初始状态、参与/放弃投标后的解析产物迁移、项目素材目录删除、review decision、项目列表/详情 payload、模板 fallback 和阶段更新返回值不再直接写在 `store.py` 里。
- 项目 JSONB 持久化 SQL 已下沉到 `bid_project_repository.py`，`store.py` 不再直接 import `psycopg` / `Jsonb`，也不再直接写 projects 表建表、查询、插入或删除 SQL。
- 业务 service 对项目可写状态的访问已改为公开门面，`app/services` 不再直接调用 `store._require` / `store._persist_project` 私有方法；gap repository、OCR 候选确认和商务标装配 S3 plan 恢复写回都通过 `workspace_project_access` 的可写状态与持久化门面，`ocr_service.py` 不再直接 import 通用 `store`，`business_assembly.py` 不再直接调用 `store.persist_project_state`。
- 项目 service 的项目列表、创建、详情、更新、删除、模板 fallback、解析进度和阶段更新已收口到 `workspace_project_access.py` 公开门面；`bid_project_service.py` 不再直接 import 通用 `store`。
- 旧通用 `store.py` 模板 fallback 读写门面已删除，`template_fallback_context` / `update_template_fallback` 不再作为绕过双轨项目 service 的兼容入口存在；fallback 上下文读取和开关写回由 `workspace_project_access.py` 取项目后调用 `bid_project_state.py` 状态函数并显式持久化。
- 看板项目列表已改为通过 `business_project_service` / `technical_project_service` 获取，不再直接调用 `store.list_projects` 或自行持有标类常量。
- 双轨项目类型 guard 已收口到 `workspace_project_access.py`，商务/技术项目 service、解析 service、目录生成、生成调度、gap repository 只保留领域命名门面，技术标草稿生成、技术标正文装配、技术标格式切换、商务标正文/格式入口、商务受控润色、商务缺口规划和商务解析资产同步不再各自直接读取通用项目并重复判断 `bidType`；标类归一规则已收口到 `bid_type.py`，`parse_profiles.py` 与 `identity.py` 不再各自定义 `normalize_bid_type`，审计、解析产物落地、商务文档 service、目录/大纲状态、目录生成、生成调度、gap repository、事实表、workspace 路径、模板 fallback、素材 facade、素材分类、素材目录维护、raw 目录初始化、素材上传/更新元数据、素材上传/Wiki、商务素材切分、技术机型候选和 Wiki 生成也从 `bid_type.py` 取技术标/商务标/通用常量或判断函数，不再通过素材 facade、gap repository、生成链路、解析链路、素材目录链路、素材分类链路或 Wiki 生成素材过滤局部字符串比较间接维护标类口径。
- 生成填充状态文案已下沉到 `bid_fill_state.py`，商务/技术正文标签、正文拼装 skill 任务标签和默认 `fill_state` 不再直接写在 `store.py` 里。
- 运行态恢复、默认状态补齐和时间戳工具已下沉到 `bid_runtime_state.py`，解析结果/解析存储、解析进度、目录状态、大纲状态、正文生成状态、文档状态、商务标 S2 目录产物恢复、目录树节点转换、双轨 workspace 路径和 `now_iso` 不再直接写在或经由 `store.py` 对外重导出。
- S1 解析状态规则已下沉到 `bid_parse_state.py`，解析完成 payload、解析进度事件、原文件类型标签和模板文件写回不再直接写在 `store.py` 里。
- 旧通用 `store.py` 解析完成门面已删除，`complete_parse` 不再作为绕过双轨解析 service 的兼容入口存在；测试需要构造解析完成态时直接调用 `bid_parse_state.py` 状态函数并显式持久化。
- 旧通用 `store.py` 解析结果/解析存储读取门面已删除，`get_parse_result` / `get_parse_storage` 不再作为绕过双轨解析 service、商务解析资产 service 或目录生成底层的兼容入口存在；测试需要复用解析结果/存储时直接从项目运行态取深拷贝。
- 旧通用 `store.py` 解析进度读取门面已删除，`get_parse_progress` 不再作为绕过双轨项目 service 的兼容入口存在；项目解析状态读取由 `workspace_project_access.py` 取可写项目后调用 `bid_parse_state.py` 状态函数并按需显式持久化。
- 旧通用 `store.py` 解析输入读取门面已删除，`get_parse_inputs` 不再作为绕过双轨解析 service、目录 flow 或目录生成底层的兼容入口存在；测试需要验证模板 fallback 输入时直接读取项目运行态并调用 `bid_project_state.project_parse_input_records`。
- 旧通用 `store.py` 解析进度写入门面已删除，`start_parse_progress` / `update_parse_progress` 不再作为绕过双轨解析 service 的兼容入口存在；解析进度开始/更新由 `bid_parse_service.py` 通过 `bid_parse_state.py` 状态函数和显式项目持久化完成。
- 旧通用 `store.py` 解析结果/模板文件写回门面已删除，`update_parse_result` / `update_template_files` 不再作为绕过双轨解析 service 或商务解析资产 service 的兼容入口存在；测试需要构造解析结果或模板文件时直接调用 `bid_parse_state.py` 状态函数并显式持久化。
- S1 解析 service 的解析结果、解析进度、解析输入文件和模板文件写回已改为通过双轨项目 service / `workspace_project_access.py` 访问项目运行态或可写状态；`bid_parse_service.py` 不再直接 import 通用 `store`。
- 商务解析资产的解析结果读取、结构化解析存储更新和 parse_result 写回已改为通过商务项目运行态、`update_parse_result_state` 与 `persist_workspace_project_state` 完成；`business_parse_assets.py` 不再直接 import 通用 `store`。
- 上传大小展示工具已下沉到 `file_utils.py`，解析上传服务不再调用 `store.format_size`，`store.py` 不再挂非持久化展示工具。
- 素材/模板文件名清洗、大小展示和显示时间工具已统一迁到 `file_utils.py`，`template_store.py`、`system_settings.py`、商务解析资产和商务素材切分不再从 `material_store.py` 导入 `safe_segment` / `size_label`；`material_store.py` 不再挂非持久化展示工具。
- 目录/大纲状态规则已下沉到 `bid_outline_state.py`，目录生成状态更新、目录证据读取、保存生成大纲、确认大纲和商务标大纲重生成兜底不再直接写在 `store.py` 里。
- 旧通用 `store.py` 目录/大纲读取门面已删除，`get_directory_state` / `get_outline_state` 不再作为绕过双轨目录 flow 或项目运行态访问层的兼容入口存在；测试需要读取目录状态时直接使用项目运行态和 `directory_state_with_rule_evidence` 保留证据文件回填语义。
- 旧通用 `store.py` 目录生成运行态写入门面已删除，`start_directory_generation` / `update_directory_generation_state` / `fail_directory_generation` 不再作为绕过双轨目录 flow 的兼容入口存在；测试需要构造目录运行态时直接调用 `bid_outline_state.py` 状态函数并显式持久化。
- 旧通用 `store.py` 目录/大纲写回门面已删除，`save_generated_outline` / `save_outline` / `regenerate_outline` / `confirm_outline` 不再作为绕过双轨目录 flow 的兼容入口存在；测试需要构造目录和大纲状态时直接调用 `bid_outline_state.py` 状态函数并显式持久化。
- S2 目录 flow 的目录状态、目录生成进度、招标文件预览、人工大纲保存、重生成和确认写回已改为通过双轨项目 service / `workspace_project_access.py` 访问项目运行态或可写状态；`bid_directory_flow.py` 不再直接 import 通用 `store`。
- S2 目录生成底层的解析输入读取和生成目录保存已改为通过项目运行态、`project_parse_input_records`、`save_generated_outline_state` 与 `persist_workspace_project_state` 处理；`outline_generation.py` 不再直接 import 通用 `store`。
- 正文生成运行状态规则已下沉到 `bid_fill_generation_state.py`，开始/更新/失败/完成、输出文件状态、运行时长/文件大小格式化和双轨正文完成事件不再直接写在 `store.py` 里。
- 商务/技术正文装配的目录状态、解析存储、模板输入、文档缺失提示和正文生成结果写回已改为通过项目运行态、`project_parse_input_records`、`save_fill_generation_result_state` 与 `persist_workspace_project_state` 处理；`business_assembly.py` / `tech_assembly.py` 不再直接 import 通用 `store`。
- 旧通用 `store.py` 正文生成状态读取门面已删除，`get_fill_state` 不再作为绕过双轨生成 service 或项目运行态访问层的兼容入口存在；测试需要读取正文生成状态时直接从项目运行态深拷贝 `fill_state`。
- 旧通用 `store.py` 正文生成写回门面已删除，`start_fill_generation` / `update_fill_generation_state` / `fail_fill_generation` / `save_fill_generation_result` 不再作为绕过双轨生成 flow 的兼容入口存在；测试需要构造正文生成运行态时直接调用 `bid_fill_generation_state.py` 状态函数并显式持久化。
- 当前 `app/services` 与 `app/api/routes` 中直接 `store` 依赖只保留在 `workspace_project_access.py`，作为统一项目访问门面。
- Redis 后台 worker 的目录/正文任务最终状态读取已改为通过 `workspace_project_access.py` 读取项目运行态；`app/workers/redis_worker.py` 不再直接 import 通用 `store`。
- `store.py` 中旧 MVP 占位完成门面 `complete_directory_generation` / `complete_fill_generation` 和无人使用的 `get_template_fallback` 已删除；测试需要构造完成态时直接调用 state 函数并显式持久化，避免旧 store 兼容入口继续暗示可跳过正式流程。
- 解析流程测试已迁到双轨入口；旧项目解析、项目素材范围、OCR、素材库和审计入口只作为 404 防回退测试保留。
- 共享素材底座输出内部 URL 占位符，由 business/technical material facade 改写为对应工作区 URL。

## 验证记录

在 `/Users/wlb/Agent/bid-project/code/sewpg-bid-backend`：

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_peripheral_routes.py tests/test_bid_material_scope_services.py tests/test_wiki_generation.py tests/test_wiki_export_routes.py tests/test_business_document_editing.py tests/test_gap_review_flow.py tests/test_gap_event_loop_safety.py tests/test_business_gap_planner.py tests/test_business_assembly.py tests/test_fill_generation.py tests/test_material_identity_options.py tests/test_turbine_model_selection.py tests/test_onlyoffice_document.py tests/test_directory_generation.py tests/test_business_material_splitter.py tests/test_business_material_library_rules.py -q
```

结果：`305 passed, 5 skipped`。

补充检查：

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_material_identity_options.py tests/test_business_material_library_rules.py tests/test_peripheral_routes.py tests/test_project_material_scope.py tests/test_bid_material_scope_services.py tests/test_wiki_generation.py tests/test_wiki_export_routes.py tests/test_onlyoffice_document.py tests/test_business_material_splitter.py -q
PYTHONPATH=. .venv/bin/python -m compileall app
git diff --check
```

结果：素材/Wiki/身份专项 `161 passed, 5 skipped`；编译和 diff 检查均通过。

本轮 `now_iso` 依赖收口和文档口径整理补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_runtime_recovery_rules_are_outside_store tests/test_business_gap_planner.py tests/test_gap_review_flow.py tests/test_fill_generation.py tests/test_turbine_model_selection.py tests/test_business_assembly.py -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_peripheral_routes.py tests/test_bid_material_scope_services.py tests/test_wiki_generation.py tests/test_wiki_export_routes.py tests/test_business_document_editing.py tests/test_gap_review_flow.py tests/test_gap_event_loop_safety.py tests/test_business_gap_planner.py tests/test_business_assembly.py tests/test_fill_generation.py tests/test_material_identity_options.py tests/test_turbine_model_selection.py tests/test_onlyoffice_document.py tests/test_directory_generation.py tests/test_business_material_splitter.py tests/test_business_material_library_rules.py -q
git diff --check
```

结果：聚焦组合 `68 passed`；完整后端组合 `305 passed, 5 skipped`；diff 检查通过。

本轮 `material_store` 工具函数收口补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_material_file_display_helpers_are_outside_material_store tests/test_bid_material_scope_services.py::test_raw_folder_scope_rules_are_outside_material_store tests/test_bid_material_scope_services.py::test_raw_file_object_operations_are_outside_material_store tests/test_bid_material_scope_services.py::test_raw_update_metadata_rules_are_outside_material_store tests/test_bid_material_scope_services.py::test_raw_move_metadata_rules_are_outside_material_store tests/test_business_material_splitter.py -q
```

结果：聚焦组合 `16 passed`；随后完整后端组合 `306 passed, 5 skipped`；`git diff --check` 通过。

本轮旧 `raw_permissions` 通用门面删除补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_raw_folder_scope_rules_are_outside_material_store tests/test_business_material_library_rules.py -q
```

结果：聚焦组合 `34 passed`；随后完整后端组合 `306 passed, 5 skipped`；`git diff --check` 通过。

本轮 `store.py` 项目持久化 SQL 下沉补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_project_persistence_is_outside_store tests/test_store_persistence.py::ProjectMaterialScopeTests::test_project_material_scope_uses_selected_customer_and_material_project tests/test_stage_progress.py::StageProgressTests::test_get_stages_returns_collapsed_workflow_steps -q
```

结果：聚焦组合 `3 passed`；项目状态相关组合 `132 passed, 2 skipped`；随后完整后端组合 `307 passed, 5 skipped`；`git diff --check` 通过。

本轮业务 service 项目状态公开门面补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_services_use_public_project_state_mutation_api tests/test_bid_material_scope_services.py::test_bid_project_persistence_is_outside_store tests/test_bid_material_scope_services.py::test_business_gap_payload_stays_in_business_service tests/test_bid_material_scope_services.py::test_technical_gap_detection_stays_out_of_store_private_helpers tests/test_business_assembly.py::BusinessAssemblyServiceTests::test_business_material_export_uses_business_material_store -q
```

结果：聚焦组合 `5 passed`；业务/缺口/OCR 相关组合 `137 passed, 8 skipped`；随后完整后端组合 `308 passed, 5 skipped`；`git diff --check` 通过。

本轮双轨项目访问层补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_draft_generation_uses_workspace_specific_modules tests/test_bid_material_scope_services.py::test_services_use_public_project_state_mutation_api tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards tests/test_bid_material_scope_services.py::test_business_gap_selectable_materials_stays_in_business_service tests/test_business_assembly.py::BusinessAssemblyServiceTests::test_business_material_export_uses_business_material_store -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_services_use_public_project_state_mutation_api tests/test_bid_material_scope_services.py::test_ocr_routes_are_workspace_scoped tests/test_project_material_scope.py::ProjectMaterialScopeRouteTests::test_workspace_ocr_task_routes_are_split tests/test_project_material_scope.py::ProjectMaterialScopeRouteTests::test_legacy_project_ocr_endpoint_is_not_registered tests/test_security_settings_ocr_routes.py::SecuritySettingsOcrRoutesTests::test_ocr_requires_config_and_can_list_tasks tests/test_security_settings_ocr_routes.py::SecuritySettingsOcrRoutesTests::test_ocr_success_persists_task_candidates_and_confirmation -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards tests/test_bid_material_scope_services.py::test_business_parse_assets_upload_uses_business_material_store tests/test_bid_material_scope_services.py::test_business_parse_assets_do_not_import_material_store_singleton tests/test_bid_material_scope_services.py::test_business_and_technical_document_format_state_rules_are_split tests/test_onlyoffice_document.py::OnlyOfficeDocumentTests::test_technical_document_format_endpoint_uses_technical_service -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_stage_progress.py tests/test_peripheral_routes.py -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards tests/test_business_document_editing.py tests/test_business_assembly.py::BusinessAssemblyServiceTests::test_business_material_export_uses_business_material_store -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_draft_generation_uses_workspace_specific_modules tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards tests/test_directory_generation.py tests/test_fill_generation.py tests/test_business_gap_planner.py -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py tests/test_directory_generation.py tests/test_fill_generation.py tests/test_business_gap_planner.py tests/test_business_document_editing.py tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_peripheral_routes.py tests/test_business_assembly.py -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_peripheral_routes.py tests/test_bid_material_scope_services.py tests/test_wiki_generation.py tests/test_wiki_export_routes.py tests/test_business_document_editing.py tests/test_gap_review_flow.py tests/test_gap_event_loop_safety.py tests/test_business_gap_planner.py tests/test_business_assembly.py tests/test_fill_generation.py tests/test_material_identity_options.py tests/test_turbine_model_selection.py tests/test_onlyoffice_document.py tests/test_directory_generation.py tests/test_business_material_splitter.py tests/test_business_material_library_rules.py -q
git diff --check
```

结果：项目/格式聚焦组合为 `5 passed`；OCR 项目状态访问与双轨入口组合 `4 passed, 2 skipped`；另一组项目/格式组合为 `5 passed`；项目入口/解析相关组合 `54 passed, 5 skipped`；商务文档聚焦组合 `5 passed`；目录/生成/缺口聚焦组合 `56 passed`；相关后端组合 `204 passed, 5 skipped`；完整后端组合 `309 passed, 5 skipped`；`git diff --check` 通过。

本轮旧 `store.py` 目录/大纲写回门面删除补充：

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_outline_state_rules_are_outside_store tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards tests/test_directory_generation.py::DirectoryGenerationTests::test_business_outline_regenerate_uses_generated_business_toc_not_technical_defaults tests/test_turbine_model_selection.py::TurbineModelSelectionTests::test_gap_manifest_ai_fill_and_assembly_carry_selected_turbine_model tests/test_business_gap_planner.py tests/test_gap_review_flow.py tests/test_onlyoffice_document.py tests/test_fill_generation.py tests/test_business_assembly.py -q
```

结果：聚焦组合 `82 passed`；编译通过；完整后端组合 `312 passed, 5 skipped`；`git diff --check` 通过。

本轮旧 `store.py` 正文生成写回门面删除补充：

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_fill_generation_state_rules_are_outside_store tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards tests/test_fill_generation.py tests/test_business_assembly.py::BusinessAssemblyServiceTests::test_business_fill_generation_uses_business_assembler_without_technical_gap_state -q
```

结果：聚焦组合 `16 passed`；编译通过；完整后端组合 `312 passed, 5 skipped`；`git diff --check` 通过。

本轮旧 `store.py` 解析完成门面删除补充：

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_parse_state_rules_are_outside_store tests/test_parse_pipeline.py::ParsePipelineTests::test_parse_results_materializes_legacy_required_appendix_preview_docx tests/test_directory_generation.py tests/test_fill_generation.py tests/test_business_gap_planner.py::BusinessGapPlannerTests::test_business_gap_api_uses_business_workspace_and_keeps_technical_gap_state_empty tests/test_business_assembly.py::BusinessAssemblyServiceTests::test_business_fill_generation_uses_business_assembler_without_technical_gap_state -q
```

结果：聚焦组合 `47 passed`；编译通过；完整后端组合 `312 passed, 5 skipped`；`git diff --check` 通过。

本轮旧 `material_store` raw 清洗重试和清洗稿下载地址门面删除补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_raw_access_operations_are_outside_material_store tests/test_bid_material_scope_services.py::test_raw_lifecycle_operations_are_outside_material_store tests/test_onlyoffice_document.py::OnlyOfficeDocumentTests::test_cleaned_material_preview_route_returns_onlyoffice_session tests/test_onlyoffice_document.py::OnlyOfficeDocumentTests::test_cleaned_material_preview_route_blocks_unavailable_cleaned_word -q
```

结果：聚焦组合 `4 passed`；随后继续跑完整后端组合和 diff 检查。

标类归一规则补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_type_rules_have_single_source_of_truth tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_stage_progress.py tests/test_material_identity_options.py -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_type_rules_have_single_source_of_truth tests/test_bid_material_scope_services.py::test_raw_folder_scope_rules_are_outside_material_store tests/test_bid_material_scope_services.py::test_wiki_scope_rules_are_outside_material_store tests/test_bid_material_scope_services.py::test_raw_upload_target_rules_are_outside_material_store tests/test_bid_material_scope_services.py::test_wiki_generation_import_uses_workspace_material_stores tests/test_bid_material_scope_services.py::test_technical_raw_files_owns_turbine_model_filtering tests/test_business_material_library_rules.py tests/test_material_identity_options.py tests/test_wiki_generation.py tests/test_wiki_export_routes.py -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_type_rules_have_single_source_of_truth tests/test_business_gap_planner.py tests/test_gap_review_flow.py tests/test_business_assembly.py tests/test_material_identity_options.py -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_peripheral_routes.py tests/test_bid_material_scope_services.py tests/test_wiki_generation.py tests/test_wiki_export_routes.py tests/test_business_document_editing.py tests/test_gap_review_flow.py tests/test_gap_event_loop_safety.py tests/test_business_gap_planner.py tests/test_business_assembly.py tests/test_fill_generation.py tests/test_material_identity_options.py tests/test_turbine_model_selection.py tests/test_onlyoffice_document.py tests/test_directory_generation.py tests/test_business_material_splitter.py tests/test_business_material_library_rules.py -q
git diff --check
```

结果：标类规则聚焦组合 `59 passed`；素材/Wiki/标类常量聚焦组合 `53 passed`；事实表/S3 依赖口径聚焦组合 `56 passed`；完整后端组合 `310 passed, 5 skipped`；`git diff --check` 通过。补充确认 `bid_type.py` 是技术标/商务标/通用标类常量与 `normalize_bid_type` 的唯一规则源，`parse_profiles.py` 与 `identity.py` 不再各自定义标类归一函数，审计、gap repository、事实表、素材 facade、素材目录/上传/Wiki、技术机型候选和 Wiki 生成不再各自声明或间接转出技术标/商务标常量。

解析与商务文档默认标类补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_type_rules_have_single_source_of_truth tests/test_parse_pipeline.py tests/test_business_document_editing.py tests/test_onlyoffice_document.py -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_peripheral_routes.py tests/test_bid_material_scope_services.py tests/test_wiki_generation.py tests/test_wiki_export_routes.py tests/test_business_document_editing.py tests/test_gap_review_flow.py tests/test_gap_event_loop_safety.py tests/test_business_gap_planner.py tests/test_business_assembly.py tests/test_fill_generation.py tests/test_material_identity_options.py tests/test_turbine_model_selection.py tests/test_onlyoffice_document.py tests/test_directory_generation.py tests/test_business_material_splitter.py tests/test_business_material_library_rules.py -q
git diff --check
```

结果：解析/商务文档聚焦组合 `58 passed`；完整后端组合 `310 passed, 5 skipped`；`git diff --check` 通过。补充确认 `parsing.py` 的技术标/商务标默认参数和 `business_document_service.py` 的商务文案兜底都从 `bid_type.py` 取常量；文档相对时间扫描无命中，解析/商务文档/装配旧默认字符串扫描无命中。

项目状态默认标类补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_type_rules_have_single_source_of_truth tests/test_bid_material_scope_services.py::test_bid_runtime_recovery_rules_are_outside_store tests/test_store_persistence.py::ProjectMaterialScopeTests::test_project_material_scope_uses_selected_customer_and_material_project tests/test_parse_pipeline.py -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_peripheral_routes.py tests/test_bid_material_scope_services.py tests/test_wiki_generation.py tests/test_wiki_export_routes.py tests/test_business_document_editing.py tests/test_gap_review_flow.py tests/test_gap_event_loop_safety.py tests/test_business_gap_planner.py tests/test_business_assembly.py tests/test_fill_generation.py tests/test_material_identity_options.py tests/test_turbine_model_selection.py tests/test_onlyoffice_document.py tests/test_directory_generation.py tests/test_business_material_splitter.py tests/test_business_material_library_rules.py -q
git diff --check
```

结果：项目状态/运行态聚焦组合 `44 passed`；完整后端组合 `310 passed, 5 skipped`；`git diff --check` 通过。补充确认 `store.py` 的模板 fallback、`bid_project_state.py` 的项目创建/解析产物提升/项目素材路径分流、`bid_runtime_state.py` 的解析结果和解析存储恢复都从 `bid_type.py` 取默认技术标常量；项目状态旧默认字符串扫描无命中。

模板 fallback 与解析输入补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_project_state_rules_are_outside_store tests/test_parse_pipeline.py::ParsePipelineTests::test_parse_inputs_do_not_use_legacy_template_when_project_has_no_template tests/test_parse_pipeline.py::ParsePipelineTests::test_parse_inputs_use_settings_default_template_when_project_has_no_template tests/test_parse_pipeline.py::ParsePipelineTests::test_project_template_overrides_fallback_template tests/test_security_settings_ocr_routes.py::SecuritySettingsOcrRoutesTests::test_ocr_success_persists_task_candidates_and_confirmation -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_type_rules_have_single_source_of_truth tests/test_bid_material_scope_services.py::test_bid_project_state_rules_are_outside_store tests/test_parse_pipeline.py::ParsePipelineTests::test_parse_inputs_do_not_use_legacy_template_when_project_has_no_template tests/test_parse_pipeline.py::ParsePipelineTests::test_parse_inputs_use_settings_default_template_when_project_has_no_template tests/test_parse_pipeline.py::ParsePipelineTests::test_project_template_overrides_fallback_template -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_peripheral_routes.py tests/test_bid_material_scope_services.py tests/test_wiki_generation.py tests/test_wiki_export_routes.py tests/test_business_document_editing.py tests/test_gap_review_flow.py tests/test_gap_event_loop_safety.py tests/test_business_gap_planner.py tests/test_business_assembly.py tests/test_fill_generation.py tests/test_material_identity_options.py tests/test_turbine_model_selection.py tests/test_onlyoffice_document.py tests/test_directory_generation.py tests/test_business_material_splitter.py tests/test_business_material_library_rules.py -q
git diff --check
```

结果：模板 fallback/解析输入聚焦组合 `4 passed, 1 skipped`，标类与项目状态聚焦组合 `5 passed`；完整后端组合 `310 passed, 5 skipped`；`git diff --check` 通过。补充确认 `get_parse_inputs`、`get_template_fallback` 和 `template_fallback_context` 的业务编排已下沉到 `bid_project_state.py`，`store.py` 不再直接 import `template_store`、调用 `resolve_fallback_bid_template_file_sync` 或执行 `asyncio.run`；后续旧 `store.get_parse_inputs` / `store.template_fallback_context` / `store.update_template_fallback` 公开门面也已删除。

项目列表展示状态补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_project_state_rules_are_outside_store tests/test_store_persistence.py::ProjectMaterialScopeTests::test_project_material_scope_uses_selected_customer_and_material_project tests/test_project_material_scope.py::ProjectMaterialScopeRouteTests::test_materials_path_returns_project_readable_scopes tests/test_project_material_scope.py::ProjectMaterialScopeRouteTests::test_business_materials_path_returns_business_scopes tests/test_stage_progress.py -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_peripheral_routes.py tests/test_bid_material_scope_services.py tests/test_wiki_generation.py tests/test_wiki_export_routes.py tests/test_business_document_editing.py tests/test_gap_review_flow.py tests/test_gap_event_loop_safety.py tests/test_business_gap_planner.py tests/test_business_assembly.py tests/test_fill_generation.py tests/test_material_identity_options.py tests/test_turbine_model_selection.py tests/test_onlyoffice_document.py tests/test_directory_generation.py tests/test_business_material_splitter.py tests/test_business_material_library_rules.py -q
git diff --check
```

结果：项目列表/阶段/素材范围聚焦组合 `9 passed`；完整后端组合 `310 passed, 5 skipped`；`git diff --check` 通过。补充确认项目列表 summary、标类过滤、更新时间排序和分页已下沉到 `bid_project_state.py` 的 `project_list_state`；`store.py` 不再保留 `_summary` / `_normalize_template_fallback` 包装，也不再直接写项目列表排序过滤逻辑。

阶段列表展示状态补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_project_state_rules_are_outside_store tests/test_stage_progress.py tests/test_store_persistence.py::ProjectMaterialScopeTests::test_project_material_scope_uses_selected_customer_and_material_project -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_peripheral_routes.py tests/test_bid_material_scope_services.py tests/test_wiki_generation.py tests/test_wiki_export_routes.py tests/test_business_document_editing.py tests/test_gap_review_flow.py tests/test_gap_event_loop_safety.py tests/test_business_gap_planner.py tests/test_business_assembly.py tests/test_fill_generation.py tests/test_material_identity_options.py tests/test_turbine_model_selection.py tests/test_onlyoffice_document.py tests/test_directory_generation.py tests/test_business_material_splitter.py tests/test_business_material_library_rules.py -q
git diff --check
```

结果：项目状态/阶段聚焦组合 `7 passed`；完整后端组合 `310 passed, 5 skipped`；`git diff --check` 通过。补充确认阶段列表展示入口已下沉到 `bid_project_state.py` 的 `project_stages_state`；`store.py` 不再直接 import `project_stage_flow` 或调用 `project_progress_stages`。

文档格式状态写回补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_business_and_technical_document_format_state_rules_are_split tests/test_bid_material_scope_services.py::test_bid_document_state_rules_are_outside_store tests/test_bid_material_scope_services.py::test_bid_runtime_recovery_rules_are_outside_store tests/test_onlyoffice_document.py::OnlyOfficeDocumentTests::test_technical_document_format_endpoint_uses_technical_service tests/test_business_document_editing.py -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_peripheral_routes.py tests/test_bid_material_scope_services.py tests/test_wiki_generation.py tests/test_wiki_export_routes.py tests/test_business_document_editing.py tests/test_gap_review_flow.py tests/test_gap_event_loop_safety.py tests/test_business_gap_planner.py tests/test_business_assembly.py tests/test_fill_generation.py tests/test_material_identity_options.py tests/test_turbine_model_selection.py tests/test_onlyoffice_document.py tests/test_directory_generation.py tests/test_business_material_splitter.py tests/test_business_material_library_rules.py -q
```

结果：文档状态/格式聚焦组合 `7 passed`；完整后端组合 `310 passed, 5 skipped`。补充确认商务标/技术标格式写回薄委托已收进 `bid_document_state.py`，`store.py` 不再直接 import `business_document_state.py` / `technical_document_state.py`，也不再通过 `runtime_now_iso()` 自行生成格式写回时间戳。

文档模块读取状态边界补充：

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards tests/test_business_document_editing.py -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards tests/test_onlyoffice_document.py::OnlyOfficeDocumentTests::test_technical_document_format_endpoint_uses_technical_service -q
```

结果：商务受控润色聚焦组合 `4 passed`，技术格式切换聚焦组合 `2 passed`；随后完整后端组合 `310 passed, 5 skipped`；`git diff --check` 通过；前端 `npm run build` 通过，仅有 Vite 大 chunk 警告。补充确认 `business_document_editing.py` 不再 import `store` 或直接调用 `store.get_document_state(project_id)`，缺文件提示所需文件名从商务标 workspace 运行态读取；`technical_document_format.py` 不再 import `store`，格式切换所需 `document_state` / `outline_state` / `parse_storage` 从技术标 workspace 运行态读取，避免格式模块继续绕过项目访问层读 store。

文档 service 写回状态边界补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards tests/test_business_document_editing.py tests/test_onlyoffice_document.py::OnlyOfficeDocumentTests::test_technical_document_format_endpoint_uses_technical_service tests/test_onlyoffice_document.py::OnlyOfficeDocumentTests::test_business_document_format_endpoint_uses_business_service -q
```

结果：编译通过，聚焦组合 `6 passed`；随后完整后端组合 `311 passed, 5 skipped`，`git diff --check` 通过。补充确认 `business_document_service.py` 的 AI 对话上下文从已 guard 的商务项目运行态读取 `document_state` / `fill_state`，受控替换后的强制保存和商务格式写回改走 `force_save_document_state` / `apply_business_document_format_to_project`；`technical_document_service.py` 的技术格式写回改走 `apply_technical_document_format_to_project`。两者均通过 `require_workspace_project_for_update` 与 `persist_workspace_project_state` 显式处理项目类型 guard 和持久化，不再直接调用 `store.get_document_state`、`store.get_fill_state`、`store.force_save_document` 或 `store.apply_*_document_format`。

文档 flow store 依赖收口补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards tests/test_onlyoffice_document.py tests/test_business_document_editing.py -q
```

结果：编译通过，文档聚焦组合 `18 passed`；随后完整后端组合 `311 passed, 5 skipped`，`git diff --check` 通过。补充确认 `bid_document_flow.py` 已移除 `store` import；文档 payload、保存正文、强制保存、final document、PDF、文件下载和 OnlyOffice callback 统一通过 `ensure_project` / `require_workspace_project_for_update` 读取或写入项目状态，并调用 `save_document_content_state`、`force_save_document_state`、`final_document_state` 与 `persist_workspace_project_state`。

S1 解析 service store 依赖收口补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards tests/test_parse_pipeline.py tests/test_project_material_scope.py -q
```

结果：编译通过，解析/项目素材范围聚焦组合 `49 passed`；随后完整后端组合 `311 passed, 5 skipped`，`git diff --check` 通过。补充确认 `bid_parse_service.py` 已移除 `store` import；解析结果读取、解析进度读取/开始/更新、解析输入文件读取、解析完成写回和模板文件追加，统一通过已 guard 的项目运行态或 `require_workspace_project_for_update` 可写状态，并调用 `project_parse_input_records`、`complete_parse_state`、`update_parse_progress_state`、`update_template_files_state` 与 `persist_workspace_project_state`。

S2 目录 flow store 依赖收口补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards tests/test_directory_generation.py -q
```

结果：编译通过，目录聚焦组合 `31 passed`；随后完整后端组合 `311 passed, 5 skipped`，`git diff --check` 通过。补充确认 `bid_directory_flow.py` 已移除 `store` import；目录状态读取、目录生成进度更新/失败写回、招标文件预览、人工大纲保存、重生成和确认目录，统一通过已 guard 的项目运行态或 `require_workspace_project_for_update` 可写状态，并调用 `project_parse_input_records`、`directory_state_with_rule_evidence`、`start_directory_generation_state`、`update_directory_generation_state`、`fail_directory_generation_state`、`save_outline_state`、`regenerate_outline_state`、`confirm_outline_state` 与 `persist_workspace_project_state`。

S2 目录生成底层 store 依赖收口补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards tests/test_directory_generation.py -q
rg -l "from app\.services\.store import store|\bstore\." code/sewpg-bid-backend/app/services code/sewpg-bid-backend/app/api/routes -g '*.py' | sort
```

结果：编译通过，目录聚焦组合 `31 passed`；随后完整后端组合 `311 passed, 5 skipped`，`git diff --check` 通过；直接 `store` 依赖扫描中 `outline_generation.py` 已消失，剩余为 `bid_project_service.py`、`business_assembly.py`、`business_parse_assets.py`、`dashboard_service.py`、`tech_assembly.py` 和合法访问门面 `workspace_project_access.py`。补充确认 `outline_generation.py` 的解析存储读取、解析输入读取和生成目录保存改为通过项目运行态、`project_parse_input_records`、`save_generated_outline_state` 与 `persist_workspace_project_state` 完成，不再直接调用 `store.get_parse_storage`、`store.get_parse_inputs` 或 `store.save_generated_outline`。

商务解析资产 store 依赖收口补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards tests/test_bid_material_scope_services.py::test_business_parse_assets_upload_uses_business_material_store tests/test_bid_material_scope_services.py::test_business_parse_assets_do_not_import_material_store_singleton tests/test_parse_pipeline.py tests/test_project_material_scope.py -q
rg -l "from app\.services\.store import store|\bstore\." code/sewpg-bid-backend/app/services code/sewpg-bid-backend/app/api/routes -g '*.py' | sort
```

结果：编译通过，商务解析资产/解析/项目素材范围聚焦组合 `51 passed`；随后完整后端组合 `311 passed, 5 skipped`，`git diff --check` 通过；直接 `store` 依赖扫描中 `business_parse_assets.py` 已消失，剩余为 `bid_project_service.py`、`business_assembly.py`、`dashboard_service.py`、`tech_assembly.py` 和合法访问门面 `workspace_project_access.py`。补充确认商务解析资产读取 parse_result、更新 structured result 文件、同步 parse_storage 和写回 parse_result 均改为通过商务项目运行态、`require_workspace_project_for_update`、`update_parse_result_state` 与 `persist_workspace_project_state` 完成，不再直接调用 `store.get_parse_result`、`store.get_parse_storage` 或 `store.update_parse_result`。

service 直接 `store` 入口收口补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_type_rules_have_single_source_of_truth -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards tests/test_bid_material_scope_services.py::test_draft_generation_uses_workspace_specific_modules tests/test_bid_material_scope_services.py::test_services_use_public_project_state_mutation_api tests/test_bid_material_scope_services.py::test_business_assembly_fact_table_stays_in_fact_table_helper tests/test_fill_generation.py tests/test_business_assembly.py -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards tests/test_bid_material_scope_services.py::test_bid_type_rules_have_single_source_of_truth tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_stage_progress.py tests/test_peripheral_routes.py -q
rg -l "from app\.services\.store import store|\bstore\." code/sewpg-bid-backend/app/services code/sewpg-bid-backend/app/api/routes -g '*.py' | sort
```

结果：编译通过；看板标类口径聚焦 `1 passed`；装配/生成聚焦组合 `29 passed`；项目入口/阶段/解析聚焦组合 `55 passed, 5 skipped`；随后完整后端组合 `311 passed, 5 skipped`，`git diff --check` 通过；直接 `store` 依赖扫描只剩 `workspace_project_access.py`。补充确认 `dashboard_service.py` 改走双轨项目 service；`business_assembly.py` / `tech_assembly.py` 改走项目运行态与 `save_fill_generation_result_state`；`bid_project_service.py` 的项目列表、创建、详情、更新、删除、模板 fallback、解析进度和阶段更新均改走 `workspace_project_access.py` 公开门面。

worker 与旧 store 占位门面收口补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_fill_generation_state_rules_are_outside_store tests/test_bid_material_scope_services.py::test_bid_outline_state_rules_are_outside_store tests/test_directory_generation.py::DirectoryGenerationTests::test_directory_generation_stream_returns_event_stream_payload tests/test_store_persistence.py::StorePersistenceTests::test_project_persists_across_postgres_store_restart -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_outline_state_rules_are_outside_store tests/test_bid_material_scope_services.py::test_bid_project_state_rules_are_outside_store -q
rg -l "from app\.services\.store import store|\bstore\." code/sewpg-bid-backend/app -g '*.py' | sort
```

结果：编译通过；worker 防回退聚焦 `1 passed`；旧占位完成门面聚焦 `3 passed, 1 skipped`；项目/目录状态聚焦 `2 passed`；随后完整后端组合 `311 passed, 5 skipped`，`git diff --check` 通过；整个 `app` 下直接 `store` 依赖只剩 `workspace_project_access.py`。补充确认 `redis_worker.py` 不再直接读 `store.get_directory_state` / `store.get_fill_state`，`store.py` 也不再保留 `complete_directory_generation` / `complete_fill_generation` / `get_template_fallback` 旧门面。

素材运行表公开 helper 补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_material_runtime_tables_are_outside_material_store tests/test_material_identity_options.py tests/test_business_gap_planner.py tests/test_business_material_library_rules.py -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_peripheral_routes.py tests/test_bid_material_scope_services.py tests/test_wiki_generation.py tests/test_wiki_export_routes.py tests/test_business_document_editing.py tests/test_gap_review_flow.py tests/test_gap_event_loop_safety.py tests/test_business_gap_planner.py tests/test_business_assembly.py tests/test_fill_generation.py tests/test_material_identity_options.py tests/test_turbine_model_selection.py tests/test_onlyoffice_document.py tests/test_directory_generation.py tests/test_business_material_splitter.py tests/test_business_material_library_rules.py -q
```

结果：素材运行表/身份/商务素材聚焦组合 `49 passed`；完整后端组合 `310 passed, 5 skipped`。补充确认 `ensure_material_runtime_tables` 已迁到 `material_runtime_tables.py`，`material_store.py` 不再定义 `_ensure_runtime_tables` 或公开运行表 helper；template/settings/audit/auth/OCR/商务缺口规划服务直接引用运行表模块。

素材底座默认标类补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_type_rules_have_single_source_of_truth tests/test_bid_material_scope_services.py::test_raw_upload_target_rules_are_outside_material_store tests/test_bid_material_scope_services.py::test_raw_upload_action_metadata_rules_are_outside_material_store tests/test_bid_material_scope_services.py::test_raw_folder_scope_rules_are_outside_material_store tests/test_material_identity_options.py tests/test_business_material_library_rules.py -q
```

结果：素材底座标类/上传/目录聚焦组合 `41 passed`。补充确认 `material_store.py` 和 `material_upload_operations.py` 不再 import `bid_type.py`，`raw_upload` / `raw_bootstrap_folders` 及其底层上传、目录骨架、上传目标和上传元数据函数不再提供默认技术标参数，标类必须由业务/技术 facade 或调用方显式传入。

标类兜底字符串补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_type_rules_have_single_source_of_truth tests/test_bid_material_scope_services.py::test_bid_fill_state_labels_are_outside_store tests/test_gap_review_flow.py tests/test_fill_generation.py::FillGenerationTests::test_run_fill_generation_returns_running_state_immediately tests/test_material_identity_options.py -q
```

结果：标类兜底字符串聚焦组合 `35 passed`。补充确认 `bid_fill_state.py`、`material_identity_options.py`、`tech_assembly.py`、`technical_gap_planner.py`、`technical_gap_review.py` 和 `technical_gap_state.py` 的技术标兜底已改为引用 `TECHNICAL_BID_TYPE` 常量，并在单一标类源防回退测试中覆盖。

workspace 默认标类补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_type_rules_have_single_source_of_truth tests/test_directory_generation.py tests/test_business_gap_planner.py tests/test_gap_review_flow.py tests/test_fill_generation.py -q
```

结果：workspace 标类/目录/缺口/填充聚焦组合 `83 passed`。补充确认 `workspace_artifacts.py` 不再 import `bid_type.py`，通用 `workspace_*` helper 和 `promote_parse_artifacts_to_workspace` 不再提供默认技术标参数；技术标路径继续通过 `technical_workspace_*` 显式 wrapper 进入。

模板/生成 flow 默认标类补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_type_rules_have_single_source_of_truth tests/test_parse_pipeline.py::ParsePipelineTests::test_parse_inputs_do_not_use_legacy_template_when_project_has_no_template tests/test_parse_pipeline.py::ParsePipelineTests::test_parse_inputs_use_settings_default_template_when_project_has_no_template tests/test_parse_pipeline.py::ParsePipelineTests::test_project_template_overrides_fallback_template tests/test_business_gap_planner.py -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_type_rules_have_single_source_of_truth tests/test_fill_generation.py tests/test_business_assembly.py::BusinessAssemblyServiceTests::test_business_fill_generation_uses_business_assembler_without_technical_gap_state -q
```

结果：模板 fallback/商务缺口/生成 flow 聚焦组合分别为 `15 passed` 和 `15 passed`。补充确认 `template_store.resolve_fallback_bid_template_file*` 不再提供默认技术标参数，商务缺口规划调用 fallback 模板时使用 `BUSINESS_BID_TYPE` 常量；`bid_generation_flow.py` 的生成审计、进度回调、后台任务和调度 helper 不再提供默认技术标参数，worker 和测试调用均显式传入标类。

身份规则默认标类补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_type_rules_have_single_source_of_truth tests/test_material_identity_options.py tests/test_project_material_scope.py tests/test_business_material_library_rules.py tests/test_wiki_generation.py -q
```

结果：身份/素材/Wiki 聚焦组合 `52 passed`。补充确认 `identity.classify_material_path` 与 `identity.material_identity` 不再提供默认技术标参数，素材上传元数据、素材身份选项、素材目录规则和 Wiki 生成调用时均显式传入标类。

解析默认标类补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_type_rules_have_single_source_of_truth tests/test_parse_pipeline.py tests/test_project_material_scope.py -q
```

结果：解析/项目素材范围聚焦组合 `49 passed`。补充确认 `parsing.materialize_parse_appendix_docx_assets` 和 `parse_tender_documents` 不再提供默认技术标参数，商务/技术解析 service 与 workspace 推广调用方均显式传入标类。

Wiki/外围默认标类补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_type_rules_have_single_source_of_truth tests/test_peripheral_routes.py tests/test_wiki_generation.py tests/test_business_material_library_rules.py -q
```

结果：Wiki/外围素材聚焦组合 `41 passed, 5 skipped`。补充确认 `wiki_generation.generate_platform_wiki` 与 deterministic blueprint helper 不再提供默认技术标参数，商务/技术 Wiki bootstrap 路由和测试均显式传入标类；旧 in-memory `peripheral.py` 的 raw 上传与目录骨架入口也不再默认技术标，按调用方传入标类生成项目素材路径。

标类直写参数补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_type_rules_have_single_source_of_truth tests/test_parse_pipeline.py tests/test_business_assembly.py tests/test_business_document_editing.py tests/test_business_gap_planner.py tests/test_fill_generation.py tests/test_stage_progress.py -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_type_rules_have_single_source_of_truth tests/test_onlyoffice_document.py tests/test_stage_progress.py tests/test_peripheral_routes.py tests/test_business_document_editing.py -q
rg -n "bid_type=\"技术标\"|bid_type=\"商务标\"|\"bidType\": \"技术标\"|\"bidType\": \"商务标\"|or \"技术标\"|or \"商务标\"|return \"商务标\"|return \"技术标\"|bid_type: str = BUSINESS_BID_TYPE|bid_type: str = TECHNICAL_BID_TYPE" app/services app/api -g '!**/__pycache__/**'
```

结果：标类常量/解析/商务装配/文档/缺口/生成聚焦组合 `86 passed`，技术格式/外围聚焦组合 `22 passed, 5 skipped`；扫描无命中。补充确认商务承诺函解析 materialize、商务装配/格式/缺口规划、技术草稿/装配/格式、dashboard 项目列表、双轨项目 service 和旧 in-memory seed 的标类参数均改为引用 `bid_type.py` 常量或显式 profile 标类，不再直接写第二份 `"技术标"` / `"商务标"` 参数口径。

标类/素材根路径唯一口径补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py tests/test_business_gap_planner.py tests/test_gap_review_flow.py tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_peripheral_routes.py -q
rg -n 'BUSINESS_BID_TYPE = "商务标"|TECHNICAL_BID_TYPE = "技术标"|f"商务标/项目素材|"商务标/项目素材|f"技术标/项目素材|"技术标/项目素材' app/api app/services
```

结果：标类/素材路径聚焦组合 `175 passed, 5 skipped`；随后完整后端组合 `310 passed, 5 skipped`；`git diff --check` 通过；扫描只保留 `bid_type.py` 中的唯一常量定义。补充确认 `routes/business.py` 不再定义第二份 `BUSINESS_BID_TYPE`，商务缺口默认补料路径、商务解析产物入库路径、技术标缺口补料回执路径和旧 in-memory seed 路径均通过 `bid_type.py` 与 `material_folder_scope.project_material_root_path` / `material_tier_root_path` 生成，不再直接写 `商务标/项目素材` 或 `技术标/项目素材`。前端已删除无人引用的旧共享 `src/components/shared/MaterialsViewSwitch.jsx`，技术标素材切换器和技术标素材/Wiki 页面默认落到 `/workspace/tech/materials`，不再回退旧 `/materials` 根入口；`npm run build` 通过，仅有 Vite 大 chunk 警告。

工作树梳理补充：

```bash
git status --short
find .qoder .understand-anything -maxdepth 3 -type f | sort | head -n 120
git status --short --untracked-files=all | awk '$1=="??" {print $2}' | sed -n '1,220p'
git diff --name-status --diff-filter=D | sed -n '1,220p'
```

结果：`.qoder/` 与 `.understand-anything/` 确认为本机/插件生成的记忆、索引和知识图谱文件，已加入 `.gitignore`，不再混入项目成果。剩余未跟踪项按计划归类为后端双轨 route/service/test、新前端 business/technical workspace 文件和新文档；删除项按计划归类为旧通用后端 route/service、旧共享前端业务页面/组件和过期过程文档；修改项按计划归类为双轨拆分承接文件、文档入口压缩和 API/README 口径更新。当前未 stage、未 commit。

阶段流程专项：

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_stage_progress.py tests/test_fill_generation.py::FillGenerationTests::test_technical_stage_skips_s3_after_outline_confirmation -q
```

结果：`6 passed`。

技术标机型候选拆分补充：

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_material_identity_options.py tests/test_turbine_model_selection.py tests/test_bid_material_scope_services.py tests/test_project_material_scope.py tests/test_business_material_library_rules.py -q
```

结果：`77 passed`。

前端在 `/Users/wlb/Agent/bid-project/code/sewpg-bid-frontend`：

```bash
npm run check
```

结果：通过，仅有 Vite 大 chunk 警告。

旧入口扫描结论：商务标 `/generate`、`/coverage`、`/export` 路由不再保留；`/workspace/tech/projects/:id/generate` 是技术标正式生成页，不属于旧入口。旧 `/api/projects...`、`/api/materials...`、`/api/audit...` 只剩 404 防回退测试和内部 URL 兼容替换函数。

旧结构化素材门面删除补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_legacy_structured_material_store_api_is_removed tests/test_business_material_library_rules.py tests/test_project_material_scope.py -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_peripheral_routes.py tests/test_bid_material_scope_services.py tests/test_wiki_generation.py tests/test_wiki_export_routes.py tests/test_business_document_editing.py tests/test_gap_review_flow.py tests/test_gap_event_loop_safety.py tests/test_business_gap_planner.py tests/test_business_assembly.py tests/test_fill_generation.py tests/test_material_identity_options.py tests/test_turbine_model_selection.py tests/test_onlyoffice_document.py tests/test_directory_generation.py tests/test_business_material_splitter.py tests/test_business_material_library_rules.py -q
git diff --check
rg -l "from app\.services\.store import store|\bstore\." code/sewpg-bid-backend/app -g '*.py' | sort
```

结果：编译通过；结构化素材删除/商务素材库/项目素材范围聚焦组合 `41 passed`；完整后端组合 `311 passed, 5 skipped`；`git diff --check` 通过；整个 `app` 下直接 `store` 依赖仍只剩 `workspace_project_access.py`。补充确认未被 business/technical API 使用的旧通用 `material_store.structured_*` 门面和 `material_structured_operations.py` 执行层已删除，结构化解析数据继续由 S1 解析结果、商务解析资产和缺口模块承接。

旧 `PeripheralStore.structured_*` mock 门面删除补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_legacy_peripheral_structured_material_api_is_removed tests/test_bid_material_scope_services.py::test_legacy_structured_material_store_api_is_removed tests/test_peripheral_routes.py tests/test_security_settings_ocr_routes.py -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_peripheral_routes.py tests/test_bid_material_scope_services.py tests/test_wiki_generation.py tests/test_wiki_export_routes.py tests/test_business_document_editing.py tests/test_gap_review_flow.py tests/test_gap_event_loop_safety.py tests/test_business_gap_planner.py tests/test_business_assembly.py tests/test_fill_generation.py tests/test_material_identity_options.py tests/test_turbine_model_selection.py tests/test_onlyoffice_document.py tests/test_directory_generation.py tests/test_business_material_splitter.py tests/test_business_material_library_rules.py -q
git diff --check
rg -n "structured_(list|template|preview_import|confirm_import|create|update|delete|import_excel)|_structured_|materials_structured|导入结构化素材|STRUCTURED_MATERIAL_NOT_FOUND|peripheral_store\._structured_table_options" code/sewpg-bid-backend/app/services/peripheral.py code/sewpg-bid-backend/app/services/template_store.py code/sewpg-bid-backend/app/services/material_store.py code/sewpg-bid-backend/tests/test_bid_material_scope_services.py
```

结果：编译通过；旧 peripheral structured 防回退、外围路由和设置/OCR 聚焦组合 `2 passed, 13 skipped`；完整后端组合 `312 passed, 5 skipped`；`git diff --check` 通过；旧 `structured_*` 素材 CRUD/import mock、`_structured_*` 状态字段、`materials_structured` 审计模块和 `template_store` 对 `peripheral_store._structured_table_options` 的隐式读取均已消失，模板 Excel 表类型改为 `DEFAULT_EXCEL_TEMPLATE_TABLE_OPTIONS` / `_excel_table_options` 口径。

前端素材库路由口径补充：workspace 内原始素材页已从 `/workspace/tech|business/materials/structured` 改为 `/workspace/tech|business/materials/raw`，顶部素材库导航和 business/technical 素材切换器同步使用 `raw` key；`structured` 只保留为 S1 解析结果 JSON 字段语义，不再作为素材库页面路由或旧结构化素材库入口。

```bash
npm run check
rg -n 'materials/structured|active="structured"|active='\''structured'\''|key: '\''structured'\''|key: "structured"|/structured' code/sewpg-bid-frontend/src code/sewpg-bid-frontend/docs code/progress.md doc/31-技术标与商务标双轨独立化实施计划.md -g '*.{js,jsx,ts,tsx,md}'
```

结果：前端 lint + build 通过，仅保留 Vite 大 chunk 警告；源码路由扫描中 `code/sewpg-bid-frontend/src` 已无 `/materials/structured`、`/structured` tab path 或 `structured` active/key 命中，剩余命中只在文档中作为旧入口说明和本条变更记录。

旧 `store.py` 文档状态门面删除补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_document_state_rules_are_outside_store tests/test_bid_material_scope_services.py::test_business_and_technical_document_format_state_rules_are_split tests/test_onlyoffice_document.py::OnlyOfficeDocumentTests::test_technical_document_format_endpoint_uses_technical_service tests/test_onlyoffice_document.py::OnlyOfficeDocumentTests::test_business_document_format_endpoint_uses_business_service tests/test_onlyoffice_document.py::OnlyOfficeDocumentTests::test_route_payload_uses_real_document_file_keys -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_onlyoffice_document.py tests/test_business_document_editing.py tests/test_bid_material_scope_services.py::test_bid_document_state_rules_are_outside_store tests/test_bid_material_scope_services.py::test_business_and_technical_document_format_state_rules_are_split tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_peripheral_routes.py tests/test_bid_material_scope_services.py tests/test_wiki_generation.py tests/test_wiki_export_routes.py tests/test_business_document_editing.py tests/test_gap_review_flow.py tests/test_gap_event_loop_safety.py tests/test_business_gap_planner.py tests/test_business_assembly.py tests/test_fill_generation.py tests/test_material_identity_options.py tests/test_turbine_model_selection.py tests/test_onlyoffice_document.py tests/test_directory_generation.py tests/test_business_material_splitter.py tests/test_business_material_library_rules.py -q
git diff --check
rg -n "store\.(get_document_state|save_document_content|force_save_document|apply_business_document_format|apply_technical_document_format|get_final_document)|def (get_document_state|save_document_content|force_save_document|apply_business_document_format|apply_technical_document_format|get_final_document)\(" code/sewpg-bid-backend/app code/sewpg-bid-backend/tests -g '*.py'
```

结果：编译通过；文档状态/格式聚焦组合 `5 passed`；OnlyOffice/商务文档/访问门面组合 `20 passed`；完整后端组合 `312 passed, 5 skipped`；`git diff --check` 通过；`AppStore` 公开方法列表中已无旧文档状态门面。补充确认正式文档接口继续通过 `bid_document_flow.py` / 双轨文档 service 访问已 guard 的项目运行态或可写状态，测试构造强制保存改为 `force_save_document_state` + `persist_project_state`；同名命中只剩正式 route/flow 方法名和防回退断言，不再有 `store.*` 旧文档门面调用。

旧 `store.py` 解析进度写入门面删除补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_parse_state_rules_are_outside_store tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards tests/test_parse_pipeline.py::ParsePipelineTests::test_parse_inputs_do_not_use_legacy_template_when_project_has_no_template -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_bid_material_scope_services.py::test_bid_parse_state_rules_are_outside_store tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_peripheral_routes.py tests/test_bid_material_scope_services.py tests/test_wiki_generation.py tests/test_wiki_export_routes.py tests/test_business_document_editing.py tests/test_gap_review_flow.py tests/test_gap_event_loop_safety.py tests/test_business_gap_planner.py tests/test_business_assembly.py tests/test_fill_generation.py tests/test_material_identity_options.py tests/test_turbine_model_selection.py tests/test_onlyoffice_document.py tests/test_directory_generation.py tests/test_business_material_splitter.py tests/test_business_material_library_rules.py -q
git diff --check
rg -n "def (start_parse_progress|update_parse_progress)\(|start_parse_progress_state|update_parse_progress_state\(" code/sewpg-bid-backend/app/services/store.py code/sewpg-bid-backend/tests/test_bid_material_scope_services.py code/sewpg-bid-backend/app/services/bid_parse_service.py
```

结果：编译通过；解析状态/项目访问门面聚焦组合 `3 passed`；解析/项目素材范围组合 `50 passed`；完整后端组合 `312 passed, 5 skipped`；`git diff --check` 通过；`AppStore` 公开方法列表中已无 `start_parse_progress` / `update_parse_progress`。补充确认解析进度写入只保留在双轨解析 service 内，`store.py` 不再 import 或调用 `start_parse_progress_state` / `update_parse_progress_state`；同名命中只剩 `bid_parse_state.py`、`bid_parse_service.py` 和防回退测试。

旧 `store.py` 解析结果/模板文件写回门面删除补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_parse_state_rules_are_outside_store tests/test_business_gap_planner.py::BusinessGapPlannerTests::test_business_gap_api_uses_business_workspace_and_keeps_technical_gap_state_empty tests/test_business_assembly.py::BusinessAssemblyServiceTests::test_business_fill_generation_uses_business_assembler_without_technical_gap_state -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_business_gap_planner.py tests/test_business_assembly.py tests/test_parse_pipeline.py tests/test_bid_material_scope_services.py::test_bid_parse_state_rules_are_outside_store tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_peripheral_routes.py tests/test_bid_material_scope_services.py tests/test_wiki_generation.py tests/test_wiki_export_routes.py tests/test_business_document_editing.py tests/test_gap_review_flow.py tests/test_gap_event_loop_safety.py tests/test_business_gap_planner.py tests/test_business_assembly.py tests/test_fill_generation.py tests/test_material_identity_options.py tests/test_turbine_model_selection.py tests/test_onlyoffice_document.py tests/test_directory_generation.py tests/test_business_material_splitter.py tests/test_business_material_library_rules.py -q
git diff --check
rg -n "store\.(update_parse_result|update_template_files)|def (update_parse_result|update_template_files)\(|update_parse_result_state\(|update_template_files_state\(" code/sewpg-bid-backend/app/services/store.py code/sewpg-bid-backend/app code/sewpg-bid-backend/tests -g '*.py'
```

结果：编译通过；解析状态/商务缺口/商务装配聚焦组合 `3 passed`；商务缺口/商务装配/解析扩展组合 `66 passed`；完整后端组合 `312 passed, 5 skipped`；`git diff --check` 通过；`AppStore` 公开方法列表中已无 `update_parse_result` / `update_template_files`。补充确认解析结果写回和模板文件写回只保留在 `business_parse_assets.py` / `bid_parse_service.py` 或测试内显式 state 函数路径，`store.py` 不再 import 或调用 `update_parse_result_state` / `update_template_files_state`；直接 `store` 依赖扫描仍只剩 `workspace_project_access.py`。

旧 `store.py` 解析结果/解析存储读取门面删除补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_parse_state_rules_are_outside_store tests/test_directory_generation.py::DirectoryGenerationTests::test_only_explicit_appendix_tables_are_auto_added_after_template_outline tests/test_directory_generation.py::DirectoryGenerationTests::test_generate_outline_fails_when_template_is_missing tests/test_directory_generation.py::DirectoryGenerationTests::test_generate_outline_rejects_invalid_project_template_docx tests/test_gap_review_flow.py::GapReviewFlowTests::test_gap_detection_creates_real_gap_plan_from_directory_material_refs_and_parse_appendices -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_directory_generation.py tests/test_gap_review_flow.py tests/test_parse_pipeline.py tests/test_bid_material_scope_services.py::test_bid_parse_state_rules_are_outside_store tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_peripheral_routes.py tests/test_bid_material_scope_services.py tests/test_wiki_generation.py tests/test_wiki_export_routes.py tests/test_business_document_editing.py tests/test_gap_review_flow.py tests/test_gap_event_loop_safety.py tests/test_business_gap_planner.py tests/test_business_assembly.py tests/test_fill_generation.py tests/test_material_identity_options.py tests/test_turbine_model_selection.py tests/test_onlyoffice_document.py tests/test_directory_generation.py tests/test_business_material_splitter.py tests/test_business_material_library_rules.py -q
git diff --check
rg -l "from app\.services\.store import store|\bstore\." code/sewpg-bid-backend/app -g '*.py' | sort
rg -n "store\.(get_parse_result|get_parse_storage)|def (get_parse_result|get_parse_storage)\(" code/sewpg-bid-backend/app code/sewpg-bid-backend/tests -g '*.py'
```

结果：编译通过；解析状态/目录/缺口聚焦组合 `5 passed`；目录/缺口/解析扩展组合 `101 passed`；完整后端组合 `312 passed, 5 skipped`；`git diff --check` 通过；直接 `store` 依赖扫描仍只剩 `workspace_project_access.py`；`AppStore` 公开方法列表中已无 `get_parse_result` / `get_parse_storage`。补充确认测试复用解析结果/存储时改为从 `store.get_project_runtime_state(project_id)` 读取深拷贝，正式 app 侧仍由双轨解析 service、商务解析资产 service、目录生成底层或 workspace access 读取已 guard 的运行态。

旧 `store.py` 解析进度读取门面删除补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_parse_state_rules_are_outside_store tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards tests/test_parse_pipeline.py::ParsePipelineTests::test_parse_progress_records_real_steps_and_completion -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_bid_material_scope_services.py::test_bid_parse_state_rules_are_outside_store tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_peripheral_routes.py tests/test_bid_material_scope_services.py tests/test_wiki_generation.py tests/test_wiki_export_routes.py tests/test_business_document_editing.py tests/test_gap_review_flow.py tests/test_gap_event_loop_safety.py tests/test_business_gap_planner.py tests/test_business_assembly.py tests/test_fill_generation.py tests/test_material_identity_options.py tests/test_turbine_model_selection.py tests/test_onlyoffice_document.py tests/test_directory_generation.py tests/test_business_material_splitter.py tests/test_business_material_library_rules.py -q
rg -n "store\.(get_parse_progress)|def (get_parse_progress)\(" app tests -g '*.py'
```

结果：编译通过；解析进度/访问门面聚焦组合 `3 passed`；解析/项目素材范围组合 `50 passed`；完整后端组合 `312 passed, 5 skipped`；`AppStore` 公开方法列表中已无 `get_parse_progress`，正式项目解析状态读取由 `workspace_project_access.py` 取可写项目后调用 `ensure_parse_progress_state` 并按需显式持久化；同名命中只剩防回退断言。

旧 `store.py` 解析输入读取门面删除补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_parse_state_rules_are_outside_store tests/test_parse_pipeline.py::ParsePipelineTests::test_parse_inputs_do_not_use_legacy_template_when_project_has_no_template tests/test_parse_pipeline.py::ParsePipelineTests::test_parse_inputs_use_settings_default_template_when_project_has_no_template tests/test_parse_pipeline.py::ParsePipelineTests::test_project_template_overrides_fallback_template -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_pipeline.py tests/test_security_settings_ocr_routes.py::SecuritySettingsOcrRoutesTests::test_ocr_success_persists_task_candidates_and_confirmation tests/test_bid_material_scope_services.py::test_bid_parse_state_rules_are_outside_store tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_peripheral_routes.py tests/test_bid_material_scope_services.py tests/test_wiki_generation.py tests/test_wiki_export_routes.py tests/test_business_document_editing.py tests/test_gap_review_flow.py tests/test_gap_event_loop_safety.py tests/test_business_gap_planner.py tests/test_business_assembly.py tests/test_fill_generation.py tests/test_material_identity_options.py tests/test_turbine_model_selection.py tests/test_onlyoffice_document.py tests/test_directory_generation.py tests/test_business_material_splitter.py tests/test_business_material_library_rules.py -q
rg -n "store\.(get_parse_inputs)|def (get_parse_inputs)\(" app tests -g '*.py'
```

结果：编译通过；解析输入 fallback 聚焦组合 `4 passed`；解析/设置 OCR/访问门面组合 `43 passed, 1 skipped`；完整后端组合 `312 passed, 5 skipped`；`AppStore` 公开方法列表中已无 `get_parse_inputs`。补充确认测试验证模板 fallback 输入时改为从项目运行态读取并调用 `project_parse_input_records`，正式 app 侧仍由双轨解析 service、目录 flow 或目录生成底层读取已 guard 的解析输入；同名命中只剩防回退断言。

旧 `store.py` 模板 fallback 读写门面删除补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_project_state_rules_are_outside_store tests/test_parse_pipeline.py::ParsePipelineTests::test_parse_inputs_do_not_use_legacy_template_when_project_has_no_template tests/test_parse_pipeline.py::ParsePipelineTests::test_parse_inputs_use_settings_default_template_when_project_has_no_template tests/test_parse_pipeline.py::ParsePipelineTests::test_project_template_overrides_fallback_template tests/test_directory_generation.py::DirectoryGenerationTests::test_generate_outline_fails_when_template_is_missing tests/test_business_gap_planner.py::BusinessGapPlannerTests::test_business_gap_api_uses_business_workspace_and_keeps_technical_gap_state_empty -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_pipeline.py tests/test_directory_generation.py tests/test_business_gap_planner.py tests/test_bid_material_scope_services.py::test_bid_project_state_rules_are_outside_store tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_peripheral_routes.py tests/test_bid_material_scope_services.py tests/test_wiki_generation.py tests/test_wiki_export_routes.py tests/test_business_document_editing.py tests/test_gap_review_flow.py tests/test_gap_event_loop_safety.py tests/test_business_gap_planner.py tests/test_business_assembly.py tests/test_fill_generation.py tests/test_material_identity_options.py tests/test_turbine_model_selection.py tests/test_onlyoffice_document.py tests/test_directory_generation.py tests/test_business_material_splitter.py tests/test_business_material_library_rules.py -q
rg -n "store\.(template_fallback_context|update_template_fallback)|def (template_fallback_context|update_template_fallback)\(" app tests -g '*.py'
```

结果：编译通过；模板 fallback/解析输入/目录缺模板/商务缺口聚焦组合 `6 passed`；解析/目录/商务缺口扩展组合 `84 passed`；完整后端组合 `312 passed, 5 skipped`；`AppStore` 公开方法列表中已无 `template_fallback_context` / `update_template_fallback`。补充确认正式 fallback 上下文读取和开关写回改由 `workspace_project_access.py` 取项目后调用 `project_template_fallback_context` / `update_template_fallback_state`，测试构造 fallback 关闭态也改为显式 state 函数加项目持久化；同名命中只剩 `bid_project_service.update_template_fallback` 正式业务方法名和防回退断言。

旧 `store.py` 目录/大纲读取门面删除补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards tests/test_directory_generation.py::DirectoryGenerationTests::test_get_directory_state_loads_rule_evidence_from_existing_file tests/test_directory_generation.py::DirectoryGenerationTests::test_generate_outline_rejects_invalid_project_template_docx tests/test_directory_generation.py::DirectoryGenerationTests::test_futurecode_progress_updates_before_completion tests/test_directory_generation.py::DirectoryGenerationTests::test_background_job_updates_running_state_then_completes -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_directory_generation.py tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards tests/test_bid_material_scope_services.py::test_bid_outline_state_rules_are_outside_store -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_peripheral_routes.py tests/test_bid_material_scope_services.py tests/test_wiki_generation.py tests/test_wiki_export_routes.py tests/test_business_document_editing.py tests/test_gap_review_flow.py tests/test_gap_event_loop_safety.py tests/test_business_gap_planner.py tests/test_business_assembly.py tests/test_fill_generation.py tests/test_material_identity_options.py tests/test_turbine_model_selection.py tests/test_onlyoffice_document.py tests/test_directory_generation.py tests/test_business_material_splitter.py tests/test_business_material_library_rules.py -q
rg -n "store\.(get_directory_state|get_outline_state)|def (get_directory_state|get_outline_state)\(" app tests -g '*.py'
```

结果：编译通过；目录状态/证据回填聚焦组合 `5 passed`；目录生成扩展组合 `32 passed`；完整后端组合 `312 passed, 5 skipped`；`AppStore` 公开方法列表中已无 `get_directory_state` / `get_outline_state`。补充确认测试读取目录状态时改为通过项目运行态和 `directory_state_with_rule_evidence`，保留从证据文件回填 `ruleEvidence` 的语义；读取大纲状态时改为直接深拷贝项目运行态中的 `outline_state`；同名命中只剩防回退断言。

旧 `store.py` 正文生成状态读取门面删除补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards tests/test_fill_generation.py::FillGenerationTests::test_background_job_updates_running_state_then_writes_real_docx tests/test_fill_generation.py::FillGenerationTests::test_generation_failure_before_inputs_marks_prepare_task_failed tests/test_business_assembly.py::BusinessAssemblyServiceTests::test_business_fill_generation_uses_business_assembler_without_technical_gap_state -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_fill_generation.py tests/test_business_assembly.py tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_peripheral_routes.py tests/test_bid_material_scope_services.py tests/test_wiki_generation.py tests/test_wiki_export_routes.py tests/test_business_document_editing.py tests/test_gap_review_flow.py tests/test_gap_event_loop_safety.py tests/test_business_gap_planner.py tests/test_business_assembly.py tests/test_fill_generation.py tests/test_material_identity_options.py tests/test_turbine_model_selection.py tests/test_onlyoffice_document.py tests/test_directory_generation.py tests/test_business_material_splitter.py tests/test_business_material_library_rules.py -q
rg -n "store\.(get_fill_state)|def (get_fill_state)\(" app tests -g '*.py'
```

结果：编译通过；正文生成运行/完成/失败和商务装配聚焦组合 `4 passed`；填充/商务装配扩展组合 `26 passed`；完整后端组合 `312 passed, 5 skipped`；`AppStore` 公开方法列表中已无 `get_fill_state`。补充确认测试读取正文生成状态时改为从项目运行态深拷贝 `fill_state`，正式 app 侧仍由双轨生成/文档 service 通过已 guard 的项目运行态读取；同名命中只剩防回退断言。

旧 `store.py` 目录生成运行态写入门面删除补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards tests/test_directory_generation.py::DirectoryGenerationTests::test_futurecode_progress_updates_before_completion tests/test_directory_generation.py::DirectoryGenerationTests::test_background_job_updates_running_state_then_completes tests/test_directory_generation.py::DirectoryGenerationTests::test_run_directory_generation_returns_running_state_immediately -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_directory_generation.py tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards tests/test_bid_material_scope_services.py::test_bid_outline_state_rules_are_outside_store -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_peripheral_routes.py tests/test_bid_material_scope_services.py tests/test_wiki_generation.py tests/test_wiki_export_routes.py tests/test_business_document_editing.py tests/test_gap_review_flow.py tests/test_gap_event_loop_safety.py tests/test_business_gap_planner.py tests/test_business_assembly.py tests/test_fill_generation.py tests/test_material_identity_options.py tests/test_turbine_model_selection.py tests/test_onlyoffice_document.py tests/test_directory_generation.py tests/test_business_material_splitter.py tests/test_business_material_library_rules.py -q
rg -n "store\.(start_directory_generation|update_directory_generation_state|fail_directory_generation)|def (start_directory_generation|update_directory_generation_state|fail_directory_generation)\(" app tests -g '*.py'
```

结果：编译通过；目录运行态进度聚焦组合 `4 passed`；目录生成扩展组合 `32 passed`；完整后端组合 `312 passed, 5 skipped`；`AppStore` 公开方法列表中已无 `start_directory_generation` / `update_directory_generation_state` / `fail_directory_generation`。补充确认测试构造目录运行态开始状态时改为调用 `start_directory_generation_state` 并显式持久化，正式目录运行态开始/更新/失败写回只保留在 `bid_directory_flow.py` 中；同名命中只剩正式 flow 方法、state helper 和防回退断言。

素材 helper 隐式标类入口收口补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_material_scope_helpers_require_explicit_bid_type tests/test_bid_material_scope_services.py::test_material_identity_options_rules_are_outside_material_store tests/test_bid_material_scope_services.py::test_raw_file_filter_rules_are_outside_material_store tests/test_bid_material_scope_services.py::test_wiki_node_scope_rules_are_outside_material_store tests/test_bid_material_scope_services.py::test_wiki_tree_display_rules_are_outside_material_store tests/test_material_identity_options.py tests/test_business_material_library_rules.py::BusinessMaterialLibraryRulesTests::test_raw_file_filter_applies_project_customer_tier_and_clean_status tests/test_business_material_library_rules.py::BusinessMaterialLibraryRulesTests::test_raw_file_filter_keeps_bid_scope_and_pagination_together tests/test_business_material_library_rules.py::BusinessMaterialLibraryRulesTests::test_wiki_node_bid_types_inherit_parent_or_default_to_scope tests/test_business_material_library_rules.py::BusinessMaterialLibraryRulesTests::test_wiki_tree_context_filters_roots_and_preserves_selected_order tests/test_business_material_library_rules.py::BusinessMaterialLibraryRulesTests::test_raw_move_metadata_preserves_action_and_updates_scope tests/test_business_material_library_rules.py::BusinessMaterialLibraryRulesTests::test_raw_move_metadata_can_set_file_move_action tests/test_business_material_library_rules.py::BusinessMaterialLibraryRulesTests::test_raw_move_folder_metadata_sets_folder_move_action -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_peripheral_routes.py tests/test_bid_material_scope_services.py tests/test_wiki_generation.py tests/test_wiki_export_routes.py tests/test_business_document_editing.py tests/test_gap_review_flow.py tests/test_gap_event_loop_safety.py tests/test_business_gap_planner.py tests/test_business_assembly.py tests/test_fill_generation.py tests/test_material_identity_options.py tests/test_turbine_model_selection.py tests/test_onlyoffice_document.py tests/test_directory_generation.py tests/test_business_material_splitter.py tests/test_business_material_library_rules.py -q
rg -n 'bid_type: str = ""|destination_bid_type: str = ""|item_bid_type: str = ""' app/services/material_*.py
git diff --check
```

结果：编译通过；素材 helper 显式标类聚焦组合 `16 passed`；完整后端组合 `313 passed, 5 skipped`；`git diff --check` 通过；`app/services/material_*.py` 已无 `bid_type=""` / `destination_bid_type=""` / `item_bid_type=""` 默认参数。补充确认身份选项、raw 文件过滤、raw 文件列表查询、Wiki 节点默认适用标类、Wiki 树/列表读取和 raw 移动元数据 helper 均要求调用方显式传入本次操作标类，同时保留历史素材记录缺失 `bidType` 字段时的读取容错。

前端双轨构建验证补充：

```bash
npm run build
npm run lint
```

结果：前端生产构建通过，仅有 Vite 大 chunk 警告；ESLint 通过。补充确认删旧页面/旧 helper 后，当前双轨 workspace 路由可正常完成构建。

raw 树显式标类收口补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_material_scope_helpers_require_explicit_bid_type tests/test_bid_material_scope_services.py::test_raw_tree_display_rules_are_outside_material_store tests/test_business_material_library_rules.py tests/test_project_material_scope.py::ProjectMaterialScopeRouteTests::test_materials_path_returns_project_readable_scopes tests/test_project_material_scope.py::ProjectMaterialScopeRouteTests::test_business_materials_path_returns_business_scopes -q
```

结果：编译通过；raw 树/素材目录范围聚焦组合 `37 passed`；随后完整后端组合 `313 passed, 5 skipped`；`git diff --check` 通过。补充确认 `material_store.raw_tree`、raw 创建/删除/移动目录后的返回树均已按显式标类进入，业务/技术 facade 分别传入商务标/技术标。

raw 单文件入口显式标类收口补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_material_scope_helpers_require_explicit_bid_type tests/test_bid_material_scope_services.py::test_raw_access_operations_are_outside_material_store tests/test_bid_material_scope_services.py::test_raw_lifecycle_operations_are_outside_material_store tests/test_bid_material_scope_services.py::test_raw_update_metadata_rules_are_outside_material_store tests/test_bid_material_scope_services.py::test_raw_file_filter_rules_are_outside_material_store tests/test_business_material_library_rules.py::BusinessMaterialLibraryRulesTests::test_raw_file_bid_scope_allows_common_materials_and_rejects_opposite_bid tests/test_business_material_library_rules.py::BusinessMaterialLibraryRulesTests::test_raw_file_filter_applies_project_customer_tier_and_clean_status tests/test_business_material_library_rules.py::BusinessMaterialLibraryRulesTests::test_raw_file_filter_keeps_bid_scope_and_pagination_together tests/test_onlyoffice_document.py::OnlyOfficeDocumentTests::test_cleaned_material_preview_route_returns_onlyoffice_session tests/test_onlyoffice_document.py::OnlyOfficeDocumentTests::test_cleaned_material_preview_route_blocks_unavailable_cleaned_word -q
```

结果：编译通过；raw 单文件范围校验聚焦组合 `10 passed`；随后完整后端组合 `314 passed, 5 skipped`；`git diff --check` 通过。补充确认 raw 更新、删除、下载、清洗稿预览/内容下载和单文件移动底层入口均显式接收标类，并在 operation 内校验素材范围；通用素材保持双轨可见，旧记录缺 `bidType` 时按目录根推断。

Wiki 附件显式标类收口补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_wiki_attachment_operations_are_outside_material_store tests/test_business_material_library_rules.py::BusinessMaterialLibraryRulesTests::test_wiki_attachment_scope_allows_common_docs_and_rejects_opposite_bid tests/test_wiki_generation.py tests/test_wiki_export_routes.py -q
```

结果：编译通过；Wiki 附件/Wiki 生成导出聚焦组合 `12 passed`；随后完整后端组合 `315 passed, 5 skipped`；`git diff --check` 通过。补充确认 Wiki 附件上传、内容下载和删除底层 operation 均校验标类范围，`material_store.wiki_download_attachment_content` 不再提供无标类公共入口。

Wiki 自动导入显式标类收口补充：

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_wiki_import_rules_are_outside_material_store tests/test_wiki_generation.py tests/test_wiki_export_routes.py tests/test_business_material_library_rules.py::BusinessMaterialLibraryRulesTests::test_generated_wiki_import_rules_build_scoped_root_and_defaults -q
```

结果：Wiki 导入/生成/导出聚焦组合 `12 passed`；随后完整后端组合 `315 passed, 5 skipped`；`git diff --check` 通过。补充确认自动生成 Wiki 导入底层要求显式标类，root 适用标类与调用标类不一致时会拒绝，导入后也按当前标类返回 scoped Wiki 列表。

raw 目录 operation 显式标类校验补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_material_scope_helpers_require_explicit_bid_type tests/test_bid_material_scope_services.py::test_raw_lifecycle_operations_are_outside_material_store tests/test_bid_material_scope_services.py::test_raw_folder_move_scope_rules_are_outside_material_store tests/test_business_material_library_rules.py::BusinessMaterialLibraryRulesTests::test_raw_file_bid_scope_allows_common_materials_and_rejects_opposite_bid tests/test_business_material_library_rules.py::RawMaterialProtectedFolderTests::test_auto_bootstrapped_business_folders_cannot_be_deleted -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_parse_pipeline.py tests/test_project_material_scope.py tests/test_peripheral_routes.py tests/test_bid_material_scope_services.py tests/test_wiki_generation.py tests/test_wiki_export_routes.py tests/test_business_document_editing.py tests/test_gap_review_flow.py tests/test_gap_event_loop_safety.py tests/test_business_gap_planner.py tests/test_business_assembly.py tests/test_fill_generation.py tests/test_material_identity_options.py tests/test_turbine_model_selection.py tests/test_onlyoffice_document.py tests/test_directory_generation.py tests/test_business_material_splitter.py tests/test_business_material_library_rules.py -q
```

结果：编译通过；raw 目录标类校验聚焦组合 `5 passed`；随后完整后端组合 `315 passed, 5 skipped`。补充确认 raw 目录创建、删除、移动均把显式标类传到底层 operation，父级目录、待删除目录、移动源目录和目标父目录都会做范围校验。

商务标文档旧入口口径补充：

```bash
rg -n "src/pages/(TenderReview|OutlineReview|ProjectList|MaterialDB|MaterialWiki|GapRecognition|GenerateProgress|CoverageHeatmap|FinalExport|ParseResult|CoCreationEditor)|routes/(projects|parse|directory|generation|document|export|audit|coverage|materials|ocr|outline|review)|/api/projects|/api/materials|/api/audit" doc/21-商务标解析模块执行计划.md doc/23-商务标目录生成Skill适配说明.md
git diff --check
```

结果：商务标解析说明和商务标目录 Skill 适配说明已无旧共享页面、旧通用 route 和旧 `/api/projects` / `/api/materials` / `/api/audit` 命中；`git diff --check` 通过。补充确认 `doc/21` 现在指向 `routes/business.py`、`business_parse_service`、`BusinessTenderReview` 和 `BusinessParseResult`，`doc/23` 现在指向 `BusinessOutlineReview`。

`material_store` 薄 facade 防回退补充：

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_material_store_is_thin_operation_facade -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_material_store_is_thin_operation_facade tests/test_bid_material_scope_services.py::test_material_file_display_helpers_are_outside_material_store tests/test_bid_material_scope_services.py::test_material_runtime_tables_are_outside_material_store tests/test_bid_material_scope_services.py::test_raw_tree_display_rules_are_outside_material_store tests/test_bid_material_scope_services.py::test_wiki_attachment_operations_are_outside_material_store -q
git diff --check
```

结果：薄 facade 单测 `1 passed`；相邻素材边界组合 `5 passed`。补充确认 `material_store.py` 只保留 operation facade 调用，SQL、模型、MinIO、DDL 和运行表细节必须留在 operations/state 模块内。

工作树拆包口径补充：

```bash
git status --porcelain=v1 | awk '{s=substr($0,1,2); c[s]++} END {for (s in c) print c[s], s}' | sort -nr
git diff --shortstat
git diff --name-status | awk '{print $1}' | sort | uniq -c | sort -nr
git ls-files --others --exclude-standard | awk -F/ '{if ($1=="code") print $1"/"$2"/"$3; else print $1}' | sort | uniq -c | sort -nr
```

结果：当时工作树仍未 stage、未 commit；快照为 `100 ??` / `99 M` / `67 D`，tracked diff 为 `166 files changed, 15096 insertions(+), 48296 deletions(-)`。后续提交建议拆为 5 包：文档口径与工作树清理、后端双轨 route/service 与旧通用入口删除、素材/Wiki 显式标类边界、前端 business/technical workspace 拆分与旧页面删除、测试契约迁移与回归记录。

路由与文档口径复核补充：

```bash
PYTHONPATH=. .venv/bin/python - <<'PY'
from app.main import app
paths = sorted(route.path for route in app.routes)
legacy = [p for p in paths if p.startswith('/api/projects') or p.startswith('/api/materials') or p.startswith('/api/audit')]
technical = [p for p in paths if p.startswith('/api/technical')]
business = [p for p in paths if p.startswith('/api/business')]
print(f'legacy={len(legacy)}')
print(f'technical={len(technical)}')
print(f'business={len(business)}')
PY
```

结果：当前 FastAPI app 路由表为 `legacy=0`、`technical=99`、`business=105`。已同步修正 `doc/31` 中旧的技术标/商务标注册数量，旧 `/api/projects...`、`/api/materials...`、`/api/audit...` 仍未重新注册。

工作树拆包清单复核：

```bash
git -c core.quotePath=false status --porcelain=v1 | awk '...按 01-docs / 02-backend-core / 03-material-wiki / 04-frontend / 05-tests 分类...'
```

结果：当前 `git status --short` 为 266 个压缩条目；按 `--untracked-files=all` 或 `git add -n` 展开后为 267 个 stage 行，均已归类，无 `UNMATCHED`。建议后续 staging 继续按 5 包推进：

| 包 | 数量 | 状态构成 | 主范围 |
|---|---:|---|---|
| 01-docs | 40 | 19 M / 17 D / 4 ?? | 根 README、`code/AGENT.md`、`code/plan.md`、`code/progress.md`、`doc/`、API/前后端 README 与 API 文档、`.gitignore` |
| 02-backend-core | 91 | 22 M / 15 D / 54 ?? | 后端双轨 route、business/technical service、项目/解析/目录/生成/文档/缺口/覆盖/导出 flow、store 持久化边界和 worker |
| 03-material-wiki | 38 | 5 M / 1 D / 32 ?? | `material_store` 薄 facade、素材 raw/Wiki operations、双轨素材 facade、素材分类/目录/上传/移动/运行表/Wiki 导入导出和机型候选 |
| 04-frontend | 77 | 34 M / 34 D / 9 ?? | 前端 business/technical workspace、旧共享业务页/组件删除、双轨 API client、导航、阶段流和 workspace helper 防回退测试 |
| 05-tests | 21 | 19 M / 2 ?? | 后端测试契约迁移、防回退测试和 Wiki 导出测试 |

`01-docs` 包提交前审计：

```bash
rg -n "18-S3缺口处理重组路线|19-评测体系与S3重组开发记录|20-商务标素材库执行计划|23-商务标S3缺口处理预计方案计划|24-商务标S3缺口处理执行步骤|25-商务标S4生成标书执行计划|26-UI统一优化与Figma沉淀执行计划|27-UI现状扫描与问题清单|28-UI轻量设计规范|29-UI统一改造验收记录|archive/01-需求与目标|archive/02-技术选型与架构|archive/03-UI设计|archive/04-路线备选与功能盘点|archive/07-FastAPI承接与前端改造|archive/09-二阶段分工与第一周里程碑" README.md code/AGENT.md code/plan.md code/progress.md doc code/sewpg-bid-api/*.md code/sewpg-bid-backend/README.md code/sewpg-bid-frontend/README.md code/sewpg-bid-frontend/docs
rg -n "/workspace/business/materials/structured|商务标结构化素材库|/materials/structured" README.md code/AGENT.md code/plan.md code/progress.md doc code/sewpg-bid-api/*.md code/sewpg-bid-backend/README.md code/sewpg-bid-frontend/README.md code/sewpg-bid-frontend/docs
rg -n "<relative-time-keywords>" README.md code/AGENT.md code/plan.md code/progress.md doc code/sewpg-bid-api/*.md code/sewpg-bid-backend/README.md code/sewpg-bid-frontend/README.md code/sewpg-bid-frontend/docs
git diff --check
```

结果：修正 `doc/27` 中已删除历史文档引用，改为指向仍存在的 `doc/17` 与 `doc/31`；修正 `doc/29` 中商务标素材库路由，从旧 `/workspace/business/materials/structured` 改为当前 `/workspace/business/materials/raw`，页面名称从“结构化素材库”改为“原始素材库”。复扫后已删除文档名无命中；相对时间词无命中；另用本地 Markdown 链接存在性脚本检查得到 `broken_links=0`；`git diff --check` 通过。`/materials/structured` 剩余命中均为旧入口已删除的说明记录。

`02-backend-core` 包提交前审计：

```bash
rg -n "include_router|from app\\.api\\.routes|app\\.api\\.routes\\.|routes\\.(projects|parse|directory|generation|document|export|audit|coverage|materials|ocr|outline|review|gaps)" code/sewpg-bid-backend/app -g '*.py'
rg -n "from app\\.services\\.store import store" code/sewpg-bid-backend/app/services code/sewpg-bid-backend/app/api/routes code/sewpg-bid-backend/app/workers -g '*.py'
rg -n "from app\\.api\\.utils|import app\\.api\\.utils|app\\.api\\.utils" code/sewpg-bid-backend/app/services code/sewpg-bid-backend/app/workers -g '*.py'
rg -n "app\\.services\\.(gap_planning|draft_generation|bid_flow_service)|from app\\.services import (gap_planning|draft_generation|bid_flow_service)|bid_flow_service" code/sewpg-bid-backend/app -g '*.py'
PYTHONPATH=. .venv/bin/python - <<'PY'
from app.main import app
paths = sorted(route.path for route in app.routes)
print(f"legacy={len([p for p in paths if p.startswith('/api/projects') or p.startswith('/api/materials') or p.startswith('/api/audit')])}")
print(f"technical={len([p for p in paths if p.startswith('/api/technical')])}")
print(f"business={len([p for p in paths if p.startswith('/api/business')])}")
PY
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_draft_generation_uses_workspace_specific_modules tests/test_bid_material_scope_services.py::test_business_and_technical_routes_import_workspace_flow_services tests/test_bid_material_scope_services.py::test_bid_project_persistence_is_outside_store tests/test_bid_material_scope_services.py::test_services_use_public_project_state_mutation_api tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards tests/test_bid_material_scope_services.py::test_bid_runtime_recovery_rules_are_outside_store tests/test_bid_material_scope_services.py::test_bid_parse_state_rules_are_outside_store tests/test_bid_material_scope_services.py::test_bid_outline_state_rules_are_outside_store tests/test_bid_material_scope_services.py::test_bid_document_state_rules_are_outside_store tests/test_bid_material_scope_services.py::test_bid_fill_generation_state_rules_are_outside_store tests/test_project_material_scope.py::ProjectMaterialScopeRouteTests::test_legacy_project_materials_path_endpoint_is_not_registered tests/test_project_material_scope.py::ProjectMaterialScopeRouteTests::test_legacy_project_ocr_endpoint_is_not_registered tests/test_project_material_scope.py::ProjectMaterialScopeRouteTests::test_legacy_project_parse_result_endpoints_are_not_registered tests/test_project_material_scope.py::ProjectMaterialScopeRouteTests::test_legacy_material_endpoints_are_not_registered -q
PYTHONPATH=. .venv/bin/python -m compileall app
git diff --check
```

结果：后端 route 文件当前只剩 `auth.py`、`business.py`、`business_gaps.py`、`dashboard.py`、`settings.py`、`system.py`、`technical.py`；`api_router` 只注册这些当前入口。直接 `store` 依赖只剩 `workspace_project_access.py`；service/worker 不再反向 import `app.api.utils`；精确扫描无旧 `gap_planning.py`、`draft_generation.py`、`bid_flow_service.py` 引用。当前 FastAPI app 路由表保持 `legacy=0` / `technical=99` / `business=105`。后端核心边界聚焦测试 `14 passed`；`compileall app` 与 `git diff --check` 通过。

`03-material-wiki` 包提交前审计：

```bash
rg -n "from sqlalchemy|from app\\.models\\.materials import|from app\\.services\\.minio_client import minio_client|async with async_session|session\\.execute|select\\(|session\\.execute\\((insert|update|delete)\\(|minio_client\\.|RawFile\\(|RawFile\\.|RawFolder\\(|RawFolder\\.|WikiNode|WikiDoc|WikiAttachment|CREATE TABLE|ALTER TABLE|Jsonb|psycopg" code/sewpg-bid-backend/app/services/material_store.py
rg -n "from app\\.services\\.material_store import material_store" code/sewpg-bid-backend/app -g '*.py'
rg -n "\"/api/materials|'/api/materials|/api/materials" code/sewpg-bid-backend/app code/sewpg-bid-backend/tests -g '*.py'
rg -n "bid_type\\s*:\\s*str\\s*=|bid_type\\s*=\\s*\"\"|destination_bid_type\\s*=\\s*\"\"|item_bid_type\\s*=\\s*\"\"" code/sewpg-bid-backend/app/services/material*.py code/sewpg-bid-backend/app/services/*material*.py code/sewpg-bid-backend/app/services/wiki_generation.py code/sewpg-bid-backend/app/services/identity.py
PYTHONPATH=. .venv/bin/python -m pytest tests/test_wiki_generation.py::WikiGenerationTests::test_unscoped_legacy_material_profiles_as_common_not_technical -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_material_store_is_thin_operation_facade tests/test_bid_material_scope_services.py::test_material_file_display_helpers_are_outside_material_store tests/test_bid_material_scope_services.py::test_material_runtime_tables_are_outside_material_store tests/test_bid_material_scope_services.py::test_raw_tree_display_rules_are_outside_material_store tests/test_bid_material_scope_services.py::test_wiki_attachment_operations_are_outside_material_store tests/test_bid_material_scope_services.py::test_wiki_import_rules_are_outside_material_store tests/test_bid_material_scope_services.py::test_raw_folder_move_scope_rules_are_outside_material_store tests/test_bid_material_scope_services.py::test_raw_lifecycle_operations_are_outside_material_store tests/test_bid_material_scope_services.py::test_legacy_structured_material_store_api_is_removed tests/test_bid_material_scope_services.py::test_store_does_not_bypass_workspace_material_facades tests/test_bid_material_scope_services.py::test_wiki_generation_import_uses_workspace_material_stores tests/test_wiki_generation.py tests/test_wiki_export_routes.py tests/test_business_material_library_rules.py tests/test_material_identity_options.py -q
PYTHONPATH=. .venv/bin/python -m compileall app
git diff --check
```

结果：修正 Wiki inventory 中完全缺标类的历史通用素材兜底，不再经 `TECHNICAL_BID_TYPE` 偏向技术标；缺标类且路径为 `通用素材/...` 的素材会归为 `通用`，并新增防回退测试。`material_store.py` 重型依赖扫描无命中，仍是薄 facade；app 里只有 `business_material_store.py` 与 `technical_material_store.py` 直接导入通用 `material_store`；旧 `/api/materials...` 只剩防回退测试和 `scoped_material_urls.py` 兼容替换。新增单测 `1 passed`；素材/Wiki 聚焦组合 `61 passed`；`compileall app` 与 `git diff --check` 通过。

`04-frontend` 包提交前审计：

```bash
rg -n "from ['\"](\\.\\./)*\\.\\./pages|from ['\"].*src/pages|ProjectPathRedirect|LegacyProjectPathRedirect|BusinessGapRecognitionPage|BusinessTenderReviewPage|BusinessCoverageHeatmap|BusinessGenerateProgress|BusinessFinalExport|TechnicalStageGroupNav|MaterialsViewSwitch|ProjectStageProgress|StageGroupNav|FakeProgress|StreamingText|HighlightedText|ExportModal|MaterialSelectModal" code/sewpg-bid-frontend/src
rg -n "path=\"/(projects|materials|audit)|to=\{?['\"]/(projects|materials|audit)|request\(['\"]/(projects|materials|audit)|createEventStream\(['\"]/(projects|materials|audit)|href=\{?['\"]/(projects|materials|audit)|/materials/structured|/structured" code/sewpg-bid-frontend/src
rg -n "technical[A-Za-z]*API|/technical|Technical[A-Z]|technical-" code/sewpg-bid-frontend/src/workspaces/business
rg -n "business[A-Za-z]*API|/business|Business[A-Z]|business-" code/sewpg-bid-frontend/src/workspaces/technical
npm run lint
npm run build
```

结果：旧根路由、旧共享业务页/组件、旧 workspace 兼容跳转和 `/materials/structured` 扫描无回流；business workspace 未命中 technical API/类/样式，technical workspace 未命中 business API/类/样式。同步收紧 `AppShell.jsx` 导航高亮正则，只匹配当前 `/parse/business|technical`、`/workspace/business|tech/projects`、`/workspace/business|tech/materials` 和 `/workspace/business|tech/logs`，不再宽容匹配旧根 `/projects`、`/materials`、`/audit` 或旧 `/review`。前端 `npm run lint` 通过；`npm run build` 通过，仅保留 Vite 大 chunk 警告。

`05-tests` 包提交前审计：

```bash
git -c core.quotePath=false diff --name-status -- code/sewpg-bid-backend/tests
git -c core.quotePath=false ls-files --others --exclude-standard -- code/sewpg-bid-backend/tests
rg -n "\/api\/(projects|materials|audit)|routes\.(projects|parse|directory|generation|document|export|audit|coverage|materials|ocr|outline|review|gaps)|app\.services\.(gap_planning|draft_generation|bid_flow_service)|from app\.services import (gap_planning|draft_generation|bid_flow_service)|businessGapTask|商务待填写字段" code/sewpg-bid-backend/tests
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest -q
```

结果：测试包当前为 19 个已修改测试文件、2 个新增测试文件；旧 `/api/projects`、`/api/materials`、`/api/audit` 仅保留在 404 防回退断言里，旧 `gap_planning`、`draft_generation`、`bid_flow_service` 仅保留在“不应再引用”的源码断言里，技术事实表不再沿用 `businessGapTask` / `商务待填写字段` 的防回退断言也在测试中保留。后端 `compileall app` 通过；后端完整测试 `484 passed, 17 skipped`。

本轮全量回归补充：

```bash
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest -q
npm run lint
npm run build
```

结果：后端编译通过；后端完整测试 `484 passed, 17 skipped`；前端 lint 通过；前端 build 通过，仅保留 Vite 大 chunk 警告。

OCR 审计标类补充：

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_ocr_service_injects_workspace_audit_metadata -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py::test_bid_ocr_service_injects_workspace_audit_metadata tests/test_bid_material_scope_services.py::test_ocr_routes_are_workspace_scoped tests/test_project_material_scope.py::ProjectMaterialScopeRouteTests::test_workspace_ocr_task_routes_are_split tests/test_project_material_scope.py::ProjectMaterialScopeRouteTests::test_legacy_project_ocr_endpoint_is_not_registered -q
PYTHONPATH=. .venv/bin/python -m compileall app
PYTHONPATH=. .venv/bin/python -m pytest tests/test_bid_material_scope_services.py tests/test_project_material_scope.py tests/test_security_settings_ocr_routes.py -q
```

结果：`BidOcrService` 已从 business/technical 项目 service 获取已 guard 的项目，并把 `projectId`、`projectName`、`projectCode`、`customerName`、`bidType` 注入底层 OCR 审计 metadata；OCR 执行、候选确认和候选忽略写入审计时都会携带标类信息，便于 `/api/business/audit` 与 `/api/technical/audit` 按标类过滤。新增非集成防回退测试 `1 passed`；OCR/项目范围聚焦组合 `4 passed`；后端边界扩展组合 `99 passed, 8 skipped`；`compileall app` 通过；随后完整后端回归 `484 passed, 17 skipped`。

前端共享项目弹窗 API 边界补充：

```bash
rg -n "from ['\"]\\.\\./\\.\\./api|businessProjectsAPI|businessMaterialsAPI|technicalProjectsAPI|technicalMaterialsAPI|workspaceApisForBidType|workspaceKind" code/sewpg-bid-frontend/src/components/modals/ProjectWizardModal.jsx code/sewpg-bid-frontend/src/components/shared code/sewpg-bid-frontend/src/components/ui
rg -n "<ProjectWizardModal" -g "*.jsx" code/sewpg-bid-frontend/src
npm run lint
npm run build
```

结果：`ProjectWizardModal.jsx` 已移除 business/technical API 直接 import 和 `workspaceApisForBidType` 分流函数，改为由调用页显式传入 `projectsApi`、`materialsApi` 和技术标专用 `turbineModelOptionsApi`；技术标项目列表、技术标解析审核和商务标解析审核三个调用点都已注入各自 workspace API。共享 modal/API 依赖扫描无命中；前端 `npm run lint` 通过；前端 `npm run build` 通过，仅保留 Vite 大 chunk 警告。

前端共享项目弹窗机型字段配置化补充：

```bash
rg -n "form\\.bidType === '技术标'|form\\.bidType !== '技术标'|defaultBidType \\|\\| '技术标'|<option>技术标|<option>商务标|businessProjectsAPI|businessMaterialsAPI|technicalProjectsAPI|technicalMaterialsAPI|workspaceApisForBidType|workspaceKind" code/sewpg-bid-frontend/src/components/modals/ProjectWizardModal.jsx code/sewpg-bid-frontend/src/components/shared code/sewpg-bid-frontend/src/components/ui
npm run lint
npm run build
```

结果：`ProjectWizardModal.jsx` 不再通过 `form.bidType === '技术标'` 判断是否加载/校验/提交投标机型，也不再内置技术标/商务标下拉选项；机型字段改为由调用页显式传入 `requiresTurbineModel`，技术标项目列表和技术标解析审核页传入该配置，商务标解析审核页不传。共享 modal 技术/商务硬编码扫描无命中；前端 `npm run lint` 与 `npm run build` 通过，build 仅保留 Vite 大 chunk 警告。

素材无标类兜底补充：

```bash
PYTHONPATH=. pytest tests/test_material_identity_options.py tests/test_business_material_library_rules.py::BusinessMaterialLibraryRulesTests::test_raw_upload_target_plan_handles_auto_project_target tests/test_business_material_library_rules.py::BusinessMaterialLibraryRulesTests::test_raw_upload_target_plan_requires_explicit_bid_type tests/test_business_material_library_rules.py::BusinessMaterialLibraryRulesTests::test_raw_upload_target_plan_infers_business_customer_subfolder tests/test_business_material_library_rules.py::BusinessMaterialLibraryRulesTests::test_raw_upload_target_plan_keeps_legacy_customer_aliases_canonicalizable tests/test_bid_material_scope_services.py::test_bid_type_rules_have_single_source_of_truth tests/test_bid_material_scope_services.py::test_material_scope_helpers_require_explicit_bid_type -q
python -m compileall app/services/material_identity_options.py app/services/material_upload_target.py app/services/material_upload_operations.py
git diff --check
```

结果：`material_identity_options.py`、`material_upload_metadata.py` 和 `material_folder_scope.py` 中无标类旧素材身份、上传元数据和规范目录 metadata 不再默认为技术标，完全缺标类的旧 `项目素材/...` 记录会归为 `通用`；`material_upload_target.py` 不再把缺失或非法上传标类默认为技术标，而是返回 `BID_TYPE_REQUIRED`，上传执行层对应抛出 `RAW_UPLOAD_BID_TYPE_REQUIRED`。`normalize_material_bid_type` 也不再带 `TECHNICAL_BID_TYPE` 默认值，目录层级 specs 和项目素材根路径必须显式传入技术标或商务标，旧目录迁移也不再用技术标作为最后兜底。`technical_turbine_material_options.py` 读取机型候选时也不再把缺标类素材默认为技术标，而是按 ext/folder/path 推断真实标类，缺标类的商务路径素材不会混入技术标机型选项。新增防回退测试确认旧无标类项目素材不偏向技术标、上传目标和目录 helper 都必须显式传入技术标或商务标、缺标类商务素材不进入技术标机型候选；素材身份/素材规则/标类源码契约组合 `46 passed`；相关文件编译通过；`git diff --check` 通过。当时工作树仍未 stage、未 commit，快照为 `100 ??` / `99 M` / `67 D`，tracked diff 为 `166 files changed, 15096 insertions(+), 48296 deletions(-)`。

项目/运行态默认标类补充：

```bash
PYTHONPATH=. pytest tests/test_bid_material_scope_services.py::test_bid_type_rules_have_single_source_of_truth tests/test_bid_material_scope_services.py::test_bid_project_state_rules_are_outside_store tests/test_bid_material_scope_services.py::test_bid_runtime_recovery_rules_are_outside_store tests/test_stage_progress.py -q
python -m compileall app/services/bid_type.py app/services/bid_project_state.py app/services/bid_runtime_state.py
PYTHONPATH=. pytest tests/test_bid_material_scope_services.py tests/test_fill_generation.py tests/test_parse_pipeline.py::ParsePipelineTests::test_parse_inputs_do_not_use_legacy_template_when_project_has_no_template tests/test_parse_pipeline.py::ParsePipelineTests::test_parse_inputs_use_settings_default_template_when_project_has_no_template tests/test_parse_pipeline.py::ParsePipelineTests::test_project_template_overrides_fallback_template tests/test_directory_generation.py::DirectoryGenerationTests::test_run_directory_generation_returns_running_state_immediately -q
PYTHONPATH=. pytest tests/test_stage_progress.py tests/test_onlyoffice_document.py tests/test_peripheral_routes.py -q
git diff --check
```

结果：`bid_type.py` 新增 `require_bid_type`，`is_technical_bid_type("unknown")` 不再因为默认值误判为技术标；`bid_project_state.py` 的项目新建、项目标类读取、项目更新和解析产物推广必须显式拿到技术标或商务标，不再通过 `TECHNICAL_BID_TYPE` 兜底；`bid_runtime_state.py` 的解析结果恢复、解析存储恢复和项目运行态补齐也必须显式传入标类。`tests/test_stage_progress.py`、`tests/test_store_persistence.py` 中直接走 store 的历史测试已改为显式传入技术标，新增防回退断言确认缺标类项目创建、项目更新和运行态恢复会抛错。聚焦组合 `8 passed`；解析/生成/目录/状态扩展组合 `109 passed`；阶段/OnlyOffice/外围组合 `19 passed, 5 skipped`；相关文件编译通过；`git diff --check` 通过。当时工作树仍未 stage、未 commit，快照为 `100 ??` / `99 M` / `67 D`，tracked diff 为 `166 files changed, 15096 insertions(+), 48296 deletions(-)`。

身份/素材范围默认标类补充：

```bash
PYTHONPATH=. pytest tests/test_bid_material_scope_services.py::test_bid_type_rules_have_single_source_of_truth tests/test_bid_material_scope_services.py::test_material_scope_helpers_require_explicit_bid_type tests/test_material_identity_options.py tests/test_project_material_scope.py tests/test_business_material_library_rules.py tests/test_wiki_generation.py -q
python -m compileall app/services/identity.py app/services/material_identity_options.py app/services/material_upload_metadata.py app/services/wiki_generation.py
git diff --check
```

结果：`identity.py` 的 `build_project_identity`、`build_project_material_scope`、`classify_material_path` 和 `material_identity` 不再把缺失或未知标类默认为技术标；项目身份和项目素材范围必须显式传入技术标或商务标，素材路径分类和素材身份只在调用方显式传入时允许 `通用`。新增防回退断言确认缺标类项目身份、项目素材范围、路径分类和素材身份都会抛错；身份/素材范围/Wiki 组合 `59 passed`；相关文件编译通过；`git diff --check` 通过。当时工作树仍未 stage、未 commit，快照为 `100 ??` / `99 M` / `67 D`，tracked diff 为 `166 files changed, 15096 insertions(+), 48296 deletions(-)`。

目录/技术标生成 manifest 默认标类补充：

```bash
PYTHONPATH=. pytest tests/test_bid_material_scope_services.py::test_bid_type_rules_have_single_source_of_truth tests/test_directory_generation.py tests/test_fill_generation.py tests/test_gap_review_flow.py -q
PYTHONPATH=. pytest tests/test_bid_material_scope_services.py tests/test_business_assembly.py tests/test_turbine_model_selection.py -q
python -m compileall app/services/outline_generation.py app/services/tech_assembly.py app/services/technical_gap_planner.py app/services/technical_gap_review.py
git diff --check
```

结果：`outline_generation.py` 的目录 prompt 和 S2 工作区标类必须显式传入技术标或商务标，不再用 `TECHNICAL_BID_TYPE` 或“投标文件”兜底；`tech_assembly.py` 的 S7 manifest 与 Wiki 导出、`technical_gap_planner.py` 的 S4 manifest、`technical_gap_review.py` 的 review payload 都改为从已 guard 项目读取显式标类，缺标类时直接抛错。新增源码防回退断言覆盖 `outline_generation`、`tech_assembly`、`technical_gap_planner`、`technical_gap_review`；目录/生成/review 组合 `72 passed`；标类边界/商务装配/机型组合 `107 passed`；相关文件编译通过；`git diff --check` 通过。补充把 `technical_material_store.py` 的技术标根目录 fallback 收口为 `ensure_root_path` 后，共享层默认技术标扫描无命中；技术标 facade 仍通过显式 `TECHNICAL_BID_TYPE` 表达领域入口。技术素材边界补充组合 `4 passed`，相关文件编译通过，`git diff --check` 通过。当时工作树仍未 stage、未 commit，快照为 `100 ??` / `99 M` / `67 D`，tracked diff 为 `166 files changed, 15096 insertions(+), 48296 deletions(-)`。

文档表格口径收敛补充：

```bash
rg -n -- 'business_project_service` -> `store|business_parse_service\.py` -> `store|business_directory_service` -> `store|technical_project_service` -> `store|technical_parse_service` -> `store|technical_directory_service\.py` -> .*`store`|后续再拆底层 store|后续继续拆解析底层 store|后续继续拆文档底层 store|后续继续拆底层 outline store' doc/31-技术标与商务标双轨独立化实施计划.md
git diff --check
```

结果：`doc/31` 的商务标/技术标 API 与后端复用表已改成当前真实边界：项目、解析、目录不再写成直接 `-> store`，而是标明 `workspace_project_access.py`、`bid_project_state.py`、`bid_parse_state.py`、`bid_outline_state.py` 和 `bid_directory_flow.py` 等实际访问层；“后续拆底层 store”改成“防止业务规则回流到通用持久化 facade / 复扫共享工具边界”。旧表格口径扫描无命中，`git diff --check` 通过。当时工作树仍未 stage、未 commit，快照为 `100 ??` / `99 M` / `67 D`，tracked diff 为 `166 files changed, 15096 insertions(+), 48296 deletions(-)`。

全量回归补充：

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q
npm run lint
npm run build
git diff --check
```

结果：后端完整回归通过，`484 passed, 17 skipped`；前端 `npm run lint` 通过；前端 `npm run build` 通过，仅保留 Vite 大 chunk 警告；`git diff --check` 通过。当时工作树仍未 stage、未 commit，快照为 `100 ??` / `99 M` / `67 D`，tracked diff 为 `166 files changed, 15096 insertions(+), 48296 deletions(-)`。

核心标类默认收口补充：

```bash
PYTHONPATH=. pytest tests/test_bid_material_scope_services.py::test_bid_type_rules_have_single_source_of_truth tests/test_stage_progress.py tests/test_parse_pipeline.py::ParsePipelineTests::test_parse_inputs_do_not_use_legacy_template_when_project_has_no_template tests/test_parse_pipeline.py::ParsePipelineTests::test_parse_inputs_use_settings_default_template_when_project_has_no_template tests/test_parse_pipeline.py::ParsePipelineTests::test_project_template_overrides_fallback_template tests/test_wiki_generation.py -q
python -m compileall app/services/bid_type.py app/services/parse_profiles.py app/services/project_fact_materials.py app/services/project_stage_flow.py app/services/workspace_project_access.py app/services/peripheral.py app/services/wiki_generation.py app/services/outline_generation.py app/services/bid_generation_flow.py
PYTHONPATH=. pytest tests/test_bid_material_scope_services.py tests/test_directory_generation.py tests/test_fill_generation.py tests/test_project_material_scope.py tests/test_peripheral_routes.py tests/test_wiki_generation.py tests/test_business_material_library_rules.py -q
PYTHONPATH=. .venv/bin/python -m pytest -q
git diff --check
```

结果：`normalize_bid_type` 默认值从技术标改为空字符串，未知标类不再天然归入技术标；`parse_profiles.py`、`workspace_project_access.py`、`project_stage_flow.py`、`project_fact_materials.py`、`peripheral.py`、`outline_generation.py`、`wiki_generation.py` 和 `bid_generation_flow.py` 改为通过 `require_bid_type` 显式要求技术标/商务标。新增 AST 防回退断言，确认 app 侧除 `bid_type.py` 内部外不再出现无显式默认的 `normalize_bid_type(...)` 调用；相关文件编译通过，标类核心聚焦组合 `17 passed`，共享边界扩展组合 `187 passed, 5 skipped`，后端完整回归 `484 passed, 17 skipped`，`git diff --check` 通过。当时工作树仍未 stage、未 commit，快照为 `100 ??` / `99 M` / `67 D`，tracked diff 为 `166 files changed, 15096 insertions(+), 48296 deletions(-)`。

前端 workspace 与 Wiki 导出默认标类补充：

```bash
node --test src/utils/workspace.test.mjs
PYTHONPATH=. pytest tests/test_wiki_export_routes.py -q
python -m compileall app/services/business_document_service.py app/services/business_gap_service.py app/services/outline_generation.py app/services/tech_assembly.py app/services/wiki_export.py
PYTHONPATH=. pytest tests/test_wiki_export_routes.py tests/test_fill_generation.py tests/test_bid_material_scope_services.py tests/test_business_document_editing.py tests/test_business_gap_planner.py tests/test_directory_generation.py -q
PYTHONPATH=. .venv/bin/python -m pytest -q
npm run lint
npm run build
git diff --check
```

结果：`src/utils/workspace.js` 中 `normalizeBidType`、`slugFromBidType` 和 `parseRouteFromBidType` 不再把未知标类归为技术标，非法 workspace slug 不再回退旧根 `/projects...` 路径；技术标/商务标解析审核页过滤项目时不再用当前页面标类补齐缺失 `bidType`，新建项目后跳转使用当前 workspace 显式 slug。`wiki_export.py` 的 Wiki API 路径选择改为 `require_bid_type`，未知标类不再落到技术标 Wiki；`business_document_service.py`、`business_gap_service.py`、`outline_generation.py` 和 `tech_assembly.py` 中的业务 payload/manifest/运行态素材卡片也改为显式标类。新增前端 workspace helper 防回退测试和 Wiki 导出未知标类测试；前端工具测试 `3 passed`，Wiki 导出测试 `4 passed`，相关后端组合 `153 passed`，后端完整回归 `484 passed, 17 skipped`，前端 `npm run lint` / `npm run build` 通过，残留默认路由扫描无命中，`git diff --check` 通过。当时工作树仍未 stage、未 commit，快照为 `100 ??` / `99 M` / `67 D`，tracked diff 为 `166 files changed, 15096 insertions(+), 48296 deletions(-)`。

项目素材路径标类兜底补充：

```bash
PYTHONPATH=. pytest tests/test_bid_material_scope_services.py::test_bid_type_rules_have_single_source_of_truth tests/test_project_material_scope.py::ProjectMaterialScopeRouteTests::test_materials_path_returns_project_readable_scopes tests/test_project_material_scope.py::ProjectMaterialScopeRouteTests::test_business_materials_path_returns_business_scopes -q
python -m compileall app/services/bid_project_service.py
python - <<'PY'
from app.main import app
routes = [getattr(r, "path", "") for r in app.routes]
legacy_prefixes = ["/api/projects", "/api/materials", "/api/audit", "/api/parse", "/api/directory", "/api/gaps", "/api/generation", "/api/document", "/api/export", "/api/coverage", "/api/ocr", "/api/outline", "/api/review"]
legacy = [p for p in routes if any(p.startswith(prefix) for prefix in legacy_prefixes)]
technical = [p for p in routes if p.startswith("/api/technical")]
business = [p for p in routes if p.startswith("/api/business")]
print(f"legacy={len(legacy)} technical={len(technical)} business={len(business)}")
PY
git diff --check
```

结果：`bid_project_service.materials_path` 不再使用 `or self.bid_type` 兜底素材路径标类，而是从已 guard 项目/素材范围里显式 `require_bid_type`；新增源码防回退断言确认项目 service 不再靠自身领域常量补缺失标类。项目素材路径聚焦组合 `3 passed`，相关文件编译通过，后端路由表保持 `legacy=0` / `technical=99` / `business=105`，前端旧根路由/API 名扫描无命中，旧通用后端 route/service 扫描无命中，`git diff --check` 通过。随后完整后端回归 `484 passed, 17 skipped`，前端 `npm run lint` / `npm run build` 通过，build 仅保留 Vite 大 chunk 警告。

5 包 staging dry-run 补充：

```bash
git add -A -n -- .gitignore README.md code/AGENT.md code/plan.md code/progress.md code/sewpg-bid-api code/sewpg-bid-backend/README.md code/sewpg-bid-frontend/README.md code/sewpg-bid-frontend/docs doc
git add -A -n -- code/sewpg-bid-backend/app ':!code/sewpg-bid-backend/app/models/materials.py' ':!code/sewpg-bid-backend/app/api/routes/materials.py' ':!code/sewpg-bid-backend/app/services/material*' ':!code/sewpg-bid-backend/app/services/business_material*' ':!code/sewpg-bid-backend/app/services/technical_material*' ':!code/sewpg-bid-backend/app/services/scoped_material_urls.py' ':!code/sewpg-bid-backend/app/services/technical_turbine_material_options.py' ':!code/sewpg-bid-backend/app/services/wiki_*'
git add -A -n -- code/sewpg-bid-backend/app/models/materials.py code/sewpg-bid-backend/app/api/routes/materials.py 'code/sewpg-bid-backend/app/services/material*' 'code/sewpg-bid-backend/app/services/business_material*' 'code/sewpg-bid-backend/app/services/technical_material*' code/sewpg-bid-backend/app/services/scoped_material_urls.py code/sewpg-bid-backend/app/services/technical_turbine_material_options.py 'code/sewpg-bid-backend/app/services/wiki_*'
git add -A -n -- code/sewpg-bid-frontend/src
git add -A -n -- code/sewpg-bid-backend/tests
```

结果：dry-run stage 行数分别为 `01-docs=40`、`02-backend-core=91`、`03-material-wiki=38`、`04-frontend=77`、`05-tests=21`，合计 `267`；与 `git status --porcelain=v1 --untracked-files=all` 展开口径一致。未执行真实 `git add`，当前 index 仍未 stage。

## 下一步

- 如需开始真实提交，按上面的 5 包 dry-run 命令去掉 `-n` 分包 stage：文档口径、后端核心、素材/Wiki、前端 workspace、测试契约。
- 真实 stage 后再做提交前最终审计：工作树分类、旧入口扫描、完整后端回归、前端 lint/build 和 `git diff --check`。
- 对仍保留的共享前端组件继续分层判断：通用 UI 零件可以保留，带业务路线、阶段、API 语义的组件继续拆成 business/technical 两套。

Redis worker 标类兜底与最新口径补充：

```bash
PYTHONPATH=. pytest tests/test_bid_material_scope_services.py::test_workspace_project_access_owns_bid_type_guards tests/test_bid_material_scope_services.py::test_bid_type_rules_have_single_source_of_truth -q
PYTHONPATH=. .venv/bin/python -m pytest -q
npm run lint
npm run build
git diff --shortstat
git status --short
git diff --cached --name-only
```

结果：`redis_worker.py` 的正文生成任务不再把缺失 `__bidType` 默认归到技术标，而是从项目运行态读取标类并通过 `require_bid_type` 校验；源码防回退断言确认 `redis_worker.py` 中不再出现 `or TECHNICAL_BID_TYPE`，聚焦组合 `2 passed`。最新完整回归为后端 `484 passed, 17 skipped`；前端 `npm run lint` 与 `npm run build` 通过，build 仅保留 Vite 大 chunk 警告。当前工作树仍未 stage、未 commit；最新盘点为 `101 ??` / `99 M` / `67 D`，tracked diff 为 `166 files changed, 15204 insertions(+), 48294 deletions(-)`；index 仍为空。

Agent 交接口径与 Markdown 自检补充：

```bash
rg -n "兼容跳转|/projects/:id/parse|/projects/:id/template-directory" README.md code/AGENT.md code/plan.md doc code/sewpg-bid-backend/README.md code/sewpg-bid-frontend/README.md code/sewpg-bid-frontend/docs -g '*.md'
# 相对时间词扫描使用固定中英文列表，忽略 fenced code 内容。
python - <<'PY'
from pathlib import Path
import re
roots = [Path('README.md'), Path('code/AGENT.md'), Path('code/plan.md'), Path('code/progress.md'), Path('doc'), Path('code/sewpg-bid-api'), Path('code/sewpg-bid-backend/README.md'), Path('code/sewpg-bid-frontend/README.md'), Path('code/sewpg-bid-frontend/docs')]
files = []
for root in roots:
    if root.is_file():
        files.append(root)
    elif root.is_dir():
        files.extend(p for p in root.rglob('*.md') if '.git' not in p.parts and 'node_modules' not in p.parts)
link_re = re.compile(r'!?\[([^\]]*)\]\(([^)]+)\)')
broken = []
for path in sorted(set(files)):
    raw = path.read_text(encoding='utf-8', errors='ignore').splitlines()
    kept = []
    in_fence = False
    for line in raw:
        if line.lstrip().startswith('```'):
            in_fence = not in_fence
            continue
        if not in_fence:
            kept.append(line)
    text = '\n'.join(kept)
    for m in link_re.finditer(text):
        target = m.group(2).strip()
        if not target or re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', target) or target.startswith('#'):
            continue
        target = target.split('#', 1)[0].strip()
        if not target or target.startswith('mailto:'):
            continue
        if target.startswith('<') and target.endswith('>'):
            target = target[1:-1]
        if not (path.parent / target).resolve().exists():
            broken.append((str(path), target))
print(f'checked_files={len(set(files))} broken_links={len(broken)}')
PY
git diff --check
```

结果：`code/AGENT.md` 已修正旧根项目 URL 说明，明确 `/projects/:id/parse` 与 `/projects/:id/template-directory` 不再作为当前入口或兼容跳转；技术标和商务标 `S1 模板与目录` 分别以 `/workspace/tech/projects/:id/template-directory` 与 `/workspace/business/projects/:id/template-directory` 为准。旧根项目路径扫描仅剩“已删除/不再兼容”的说明和当前 workspace 路径；相对时间词扫描无命中；忽略 fenced code 后 Markdown 链接检查为 `checked_files=32 broken_links=0`；`git diff --check` 通过。

S3 交接口径补充：

结果：`code/AGENT.md` 已清理 2026-05-04 的旧 S3 验收说法，不再把缺口处理写成只完成一个 Skill。当前交接口径改为：技术标和商务标 S3 的缺口识别、补料、AI 填写、素材选择、预览、完整性复查和审核入口已按双轨 service 边界实现；是否对外宣称业务验收通过，必须以带具体日期的真实回归和人工验收记录为准。旧说法复扫无命中，`git diff --check` 通过。

真实 staging 前最终审计补充：

```bash
PYTHONPATH=. python - <<'PY'
from app.main import app
routes = [getattr(r, 'path', '') for r in app.routes]
legacy_prefixes = ['/api/projects', '/api/materials', '/api/audit', '/api/parse', '/api/directory', '/api/gaps', '/api/generation', '/api/document', '/api/export', '/api/coverage', '/api/ocr', '/api/outline', '/api/review']
legacy = [p for p in routes if any(p.startswith(prefix) for prefix in legacy_prefixes)]
technical = [p for p in routes if p.startswith('/api/technical')]
business = [p for p in routes if p.startswith('/api/business')]
print(f'legacy={len(legacy)} technical={len(technical)} business={len(business)} total={len(routes)}')
PY
rg -n "app\.services\.(gap_planning|draft_generation|bid_flow_service)|from app\.services import (gap_planning|draft_generation|bid_flow_service)|routes\.(projects|parse|directory|generation|document|export|audit|coverage|materials|ocr|outline|review|gaps)|include_router\((projects|parse|directory|generation|document|export|audit|coverage|materials|ocr|outline|review|gaps)" code/sewpg-bid-backend/app -g '*.py'
rg --pcre2 -n "path=\"/(projects|materials|audit|review)|to=\{?['\"]/(projects|materials|audit|review)|navigate\(['\"]/(projects|materials|audit|review)|/api/(projects|materials|audit)(?!-)|projectsAPI|materialsAPI|auditAPI|parseAPI|directoryAPI|gapsAPI|generateAPI|coverageAPI|documentAPI|exportAPI|reviewAPI|ocrAPI" code/sewpg-bid-frontend/src -g '*.{js,jsx,mjs}'
rg -n "from app\.services import store|from app\.services\.store import|app\.services\.store|\bstore\." code/sewpg-bid-backend/app -g '*.py'
rg -n "or TECHNICAL_BID_TYPE|or BUSINESS_BID_TYPE|or self\.bid_type|default: str = TECHNICAL_BID_TYPE|bid_type: str = TECHNICAL_BID_TYPE|bid_type: str = \"技术标\"|bidType\": \"技术标\"|/api/projects|/api/materials|/api/audit" code/sewpg-bid-backend/app code/sewpg-bid-frontend/src -g '*.{py,js,jsx,mjs}'
PYTHONPATH=. .venv/bin/python -m pytest -q
npm run lint
npm run build
git diff --check
```

结果：当前仍未执行真实 `git add`，index 为空；后端 FastAPI 路由表保持 `legacy=0` / `technical=99` / `business=105`；旧通用后端 route/service 引用扫描无命中；前端旧根 API/路由名扫描无命中；直接 `store` 依赖只剩 `workspace_project_access.py`；隐式标类兜底扫描只剩商务素材 facade 内部固定商务域兜底和 `scoped_material_urls.py` 兼容替换。后端完整回归 `484 passed, 17 skipped`；前端 `npm run lint` 与 `npm run build` 通过，build 仅保留 Vite 大 chunk 警告；`git diff --check` 通过。当前工作树仍未 stage、未 commit；最新盘点为 `101 ??` / `99 M` / `67 D`，tracked diff 为 `166 files changed, 15204 insertions(+), 48294 deletions(-)`。

临时 index 分包 staging 模拟：

```bash
tmp_index=$(mktemp /tmp/bid-project-index.XXXXXX)
cp .git/index "$tmp_index"
GIT_INDEX_FILE="$tmp_index" git add -A -- .gitignore README.md code/AGENT.md code/plan.md code/progress.md code/sewpg-bid-api code/sewpg-bid-backend/README.md code/sewpg-bid-frontend/README.md code/sewpg-bid-frontend/docs doc
GIT_INDEX_FILE="$tmp_index" git add -A -- code/sewpg-bid-backend/app ':!code/sewpg-bid-backend/app/models/materials.py' ':!code/sewpg-bid-backend/app/api/routes/materials.py' ':!code/sewpg-bid-backend/app/services/material*' ':!code/sewpg-bid-backend/app/services/business_material*' ':!code/sewpg-bid-backend/app/services/technical_material*' ':!code/sewpg-bid-backend/app/services/scoped_material_urls.py' ':!code/sewpg-bid-backend/app/services/technical_turbine_material_options.py' ':!code/sewpg-bid-backend/app/services/wiki_*'
GIT_INDEX_FILE="$tmp_index" git add -A -- code/sewpg-bid-backend/app/models/materials.py code/sewpg-bid-backend/app/api/routes/materials.py 'code/sewpg-bid-backend/app/services/material*' 'code/sewpg-bid-backend/app/services/business_material*' 'code/sewpg-bid-backend/app/services/technical_material*' code/sewpg-bid-backend/app/services/scoped_material_urls.py code/sewpg-bid-backend/app/services/technical_turbine_material_options.py 'code/sewpg-bid-backend/app/services/wiki_*'
GIT_INDEX_FILE="$tmp_index" git add -A -- code/sewpg-bid-frontend/src
GIT_INDEX_FILE="$tmp_index" git add -A -- code/sewpg-bid-backend/tests
GIT_INDEX_FILE="$tmp_index" git status --porcelain=v1 --untracked-files=all
GIT_INDEX_FILE="$tmp_index" git diff --cached --name-status
rm -f "$tmp_index"
```

结果：五包命令在临时 index 上执行后覆盖完整当前工作树，模拟暂存后 `unstaged_paths=0`、`untracked_paths=0`；临时 index 识别为 `99 M` / `95 A` / `61 D` / `6 R`，共 `261` 个暂存路径。真实 index 仍为空，未执行真实 `git add`。
