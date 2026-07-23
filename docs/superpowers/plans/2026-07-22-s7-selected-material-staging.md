# S7 选中素材暂存与清理实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让技术标 S7 只暂存并组装 gap plan 最终选中的 Word，同时保证重复组装和异常退出不会遗留临时素材。

**Architecture:** S4 gap plan 继续作为只读输入，S7 在自己的工作目录内复制计划并将最终选中素材下载到 `selected_materials/`，随后仅改写该 S7 副本中的素材路径。合并器继续消费“素材根目录 + 相对路径”契约；正文组装结束或失败后通过 `finally` 删除暂存目录。

**Tech Stack:** Python 3、FastAPI service、MinIO、python-docx、pytest/unittest

---

### Task 1: 仅暂存 gap plan 最终选中素材

**Files:**
- Modify: `code/sewpg-bid-backend/tests/test_fill_generation.py`
- Modify: `code/sewpg-bid-backend/app/services/tech_assembly.py`

- [ ] **Step 1: 写入失败测试**

新增 `test_stage_selected_gap_plan_materials_rewrites_s7_copy_and_clears_stale_files`：构造一个包含父章节已选 Word、被父章节覆盖的子节点素材及旧暂存文件的 gap plan。断言只复制父章节 Word，旧文件被清除，S7 gap plan 副本中的父素材路径改成暂存相对路径，子节点不下载，原始输入对象和文件不变。

- [ ] **Step 2: 运行红灯测试**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_fill_generation.py -k "stage_selected_gap_plan_materials" -q
```

预期：因 `_stage_selected_gap_plan_materials` 尚不存在而失败。

- [ ] **Step 3: 实现最小暂存逻辑**

在 `tech_assembly.py` 新增 `_stage_selected_gap_plan_materials(gap_plan_path, staging_dir)`：

```python
def _stage_selected_gap_plan_materials(gap_plan_path: Path, staging_dir: Path) -> tuple[Path, list[dict[str, Any]]]:
    _clear_selected_materials(staging_dir)
    plan = json.loads(gap_plan_path.read_text(encoding="utf-8"))
    staged_cards: list[dict[str, Any]] = []
    for item in plan.get("items") or []:
        if item.get("coverageRole") == "covered_by_parent":
            continue
        source_key = "resolvedArtifacts" if item.get("resolvedArtifacts") else "matchedMaterials"
        for index, source in enumerate(item.get(source_key) or [], start=1):
            if source_key == "resolvedArtifacts" and not technical_gap_artifact_is_s7_ready(source):
                continue
            relative_path = Path(_safe_filename(str(item.get("id") or "gap"), "gap")) / (
                f"{index:02d}-{_safe_filename(Path(str(source.get('path') or source.get('docx') or 'material.docx')).name, 'material.docx')}"
            )
            _copy_material_to_library(
                str(source.get("id") or ""),
                str(source.get("path") or source.get("docx") or ""),
                staging_dir / relative_path,
            )
            source["path"] = relative_path.as_posix()
            staged_cards.append(
                {
                    "id": str(source.get("id") or ""),
                    "title": Path(relative_path).name,
                    "path": relative_path.as_posix(),
                    "available": True,
                }
            )
    gap_plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return staging_dir, staged_cards
```

复用现有 `_copy_material_to_library` 获取本地文件或按素材 ID 从 MinIO 下载，不调用 Wiki 素材扫描，不修改素材匹配模块。

- [ ] **Step 4: 验证绿灯**

运行 Task 1 聚焦测试，预期通过。

### Task 2: 接入 S7 并确保退出清理

**Files:**
- Modify: `code/sewpg-bid-backend/tests/test_fill_generation.py`
- Modify: `code/sewpg-bid-backend/app/services/tech_assembly.py`

- [ ] **Step 1: 写入成功与失败清理测试**

扩充 S7 service 测试：在 assembler 调用期间断言 `selected_materials/` 和已选 Word 存在；在完整流程返回后断言目录不存在。再增加 assembler 抛错场景，断言异常向上抛出且目录同样被删除。

- [ ] **Step 2: 运行红灯测试**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_fill_generation.py -k "selected_materials_cleanup" -q
```

预期：当前主流程仍调用全量 `_export_material_library`，且没有退出清理，测试失败。

- [ ] **Step 3: 最小接入正文组装**

主流程停止调用 `_augment_wiki_with_gap_plan_cards` 和 `_export_material_library`，改为 `_stage_selected_gap_plan_materials`。从素材准备开始到结果持久化结束使用 `try/finally`，最终调用：

```python
finally:
    _clear_selected_materials(selected_materials_dir)
```

若已选素材无法取得，素材准备阶段直接抛出包含 gap 编号、素材名称和原始错误的 `RuntimeError`，不进入合并器生成占位内容。

- [ ] **Step 4: 运行聚焦回归**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_fill_generation.py tests/test_technical_final_assembly.py -q
git diff --check
```

预期：全部测试通过，差异检查无错误；变更文件不包含任何素材匹配 service、API 或前端页面。

- [ ] **Step 5: 提交正文组装修复**

只暂存 `tech_assembly.py`、两份相关测试及本计划文件，不暂存用户已有的 `tests/test_toc_skill_scripts.py` 或其他未跟踪文件。
