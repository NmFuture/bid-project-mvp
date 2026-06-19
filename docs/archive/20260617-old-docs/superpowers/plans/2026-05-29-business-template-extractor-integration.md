# 商务标模板提取 Skill 集成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将独立原型 `C:\Users\99065\Documents\商务标V2\模版提取切片` 集成到后端 S1 商务标解析链路，使 `http://localhost/parse/business` 点击解析时能够先精准切出招标文件“投标文件格式/商务附件模板”章节内的模板 `.docx`，再由现有商务结构化 skill 解析字段，最终页面继续从统一的 `structured.appendices[]` 读取模板产物。

**Architecture:** 新增独立 skill `bid-business-template-extractor`，只负责模板边界识别、标题簇保留、模板 `.docx` 切片和 `business_template_extraction.json` 输出；保留现有 `bid-business-tender-structured-parser` 只负责商务评分、响应要求、资格要求、承诺事项等结构化字段。后端 S1 business 分支内部顺序执行：抽文本/保存源文件 -> 调用模板 extractor -> 调用结构化 parser -> reducer 合并，且 `structured.appendices` 优先采用 extractor 产物，旧脚本仅作为 feature flag/fallback 保留。

**Tech Stack:** Python 3、FastAPI 后端、`python-docx`、现有 `app.services.parsing` S1 pipeline、`opencode/skill` 本地 skill runner、`unittest`、现有 `ParseProfile`/appendix materialization 约定。

---

## 现状与边界

当前后端主链路在 `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\app\services\parsing.py` 的 `parse_tender_documents(...)` 中完成：

- 抽取上传文件文本并写入 `combined.txt`；
- 调用 `_extract_structured_requirements(...)` 生成本地结构化兜底；
- 通过 `_extract_markdown_appendices(...)`、`_extract_docx_appendices(...)`、business 分支的 `_extract_text_business_appendices(...)` 做旧模板/附表提取；
- `_prepare_appendix_outputs(...)` 生成/搬运 `.docx`；
- business 分支 `_apply_business_template_semantic_review(...)` 做语义复核；
- 写入 `structured_result["structured"]["appendices"]`；
- 写 `s1_parse_manifest.json` 并通过 `_run_parse_skill(...)` 调用 `s1parse_router.py`；
- `s1parse_router.py` 当前按 `parseProfile: business` 路由到 `opencode/skill/bid-business-tender-structured-parser/scripts/run_from_manifest.py`；
- skill 返回后，后端再次合并并可能重新 `_prepare_appendix_outputs(...)`。

独立原型在 `C:\Users\99065\Documents\商务标V2\模版提取切片` 中，已验证能切出测试招标文件格式章节模板，核心文件包括：

- `run_template_extraction.py`
- `SKILL.md`
- `scripts/docx_blocks.py`
- `scripts/region_detector.py`
- `scripts/text_rules.py`
- `scripts/anchor_detector.py`
- `scripts/header_cluster_detector.py`
- `scripts/boundary_planner.py`
- `scripts/boundary_validator.py`
- `scripts/docx_slicer.py`
- `scripts/pipeline.py`
- `scripts/report_writer.py`
- `tests/test_business_template_extraction.py`

关键设计约束：

- 不合并 `bid-business-template-extractor` 与 `bid-business-tender-structured-parser`。两个 skill 共享 S1 业务目标，但职责不同。
- 不让两个 skill 并发写 `s1_structured_result.json`。
- 新 extractor 输出独立文件 `business_template_extraction.json`，后端 reducer 负责把其中 `appendices[]` 写入最终 `structured.appendices`。
- 旧商务模板提取脚本先保留为 fallback，稳定后再单独删除。
- 不用“法定代表人或其委托代理人(签字)”一类特例补丁。边界判断必须来自“格式章节区域 + 页首/分页符附近标题簇 + 模板候选 anchor + 后续内容有效性 + 边界验证”的通用机制。

## 目标文件结构

### 新增 skill

- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-template-extractor\SKILL.md`
  - 说明该 skill 只负责商务模板边界和切片，不负责评分/字段结构化。
- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-template-extractor\scripts\__init__.py`
- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-template-extractor\scripts\run_from_manifest.py`
  - 读取后端 manifest，逐个 `.docx` 招标文件运行 pipeline，写 `business_template_extraction.json`。
- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-template-extractor\scripts\docx_blocks.py`
- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-template-extractor\scripts\region_detector.py`
- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-template-extractor\scripts\text_rules.py`
- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-template-extractor\scripts\anchor_detector.py`
- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-template-extractor\scripts\header_cluster_detector.py`
- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-template-extractor\scripts\boundary_planner.py`
- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-template-extractor\scripts\boundary_validator.py`
- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-template-extractor\scripts\docx_slicer.py`
- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-template-extractor\scripts\pipeline.py`
- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-template-extractor\scripts\report_writer.py`

### 新增后端 wrapper

- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\app\services\business_template_extractor.py`
  - 构造 extractor manifest。
  - 调用新 skill 本地 runner。
  - 读取 `business_template_extraction.json`。
  - 转换为后端兼容 `appendices[]`。
  - 失败时返回 warning 和空结果，由 `parsing.py` fallback 旧逻辑。

### 修改后端 pipeline

- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\app\services\parsing.py`
  - 在 business 分支优先调用 `run_business_template_extractor(...)`。
  - extractor 成功时跳过旧的 `_extract_docx_appendices(...)`/`_extract_text_business_appendices(...)` 对商务模板的提取结果。
  - 给 `s1_parse_manifest.json` 增加只读字段 `businessTemplateExtractionPath`、`businessTemplateExtractionSummary`。
  - 最终合并时保证 `structured.appendices` 来源优先级为 extractor > skill returned appendices > legacy appendices。

### 修改/新增测试

- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\tests\test_business_template_extractor_skill_script.py`
  - 脚本级验证新 skill runner。
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\tests\test_parse_pipeline.py`
  - 添加 pipeline 级集成测试，验证 business S1 使用 extractor 产物。
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\tests\test_business_parse_skill_script.py`
  - 验证现有结构化 skill 不覆盖 `appendices`。
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\tests\test_s1parse_router_script.py`
  - 验证 `s1parse_router.py` 仍只路由结构化 parser，不直接路由模板 extractor。

---

### Task 1: 迁移独立原型为后端 opencode skill

**Files:**
- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-template-extractor\SKILL.md`
- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-template-extractor\scripts\*.py`
- Source: `C:\Users\99065\Documents\商务标V2\模版提取切片\SKILL.md`
- Source: `C:\Users\99065\Documents\商务标V2\模版提取切片\scripts\*.py`

- [ ] **Step 1: 创建 skill 目录并复制原型脚本**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
New-Item -ItemType Directory -Force -Path .\opencode\skill\bid-business-template-extractor\scripts
Copy-Item -LiteralPath 'C:\Users\99065\Documents\商务标V2\模版提取切片\scripts\*.py' -Destination .\opencode\skill\bid-business-template-extractor\scripts -Force
Copy-Item -LiteralPath 'C:\Users\99065\Documents\商务标V2\模版提取切片\SKILL.md' -Destination .\opencode\skill\bid-business-template-extractor\SKILL.md -Force
```

Expected:

```text
命令无错误退出；opencode\skill\bid-business-template-extractor\scripts 下存在 pipeline.py、docx_slicer.py 等文件。
```

- [ ] **Step 2: 修正 `SKILL.md` 职责说明**

Edit `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-template-extractor\SKILL.md`，确保开头为：

```markdown
---
name: bid-business-template-extractor
description: Extract business tender attachment/template slices from S1 tender DOCX files, preserving header clusters and producing backend-compatible appendix artifacts.
---

# Bid Business Template Extractor

Use this skill in S1 business tender parsing before `bid-business-tender-structured-parser`.

This skill is responsible only for:

- locating the business tender format chapter, such as `第六章 投标文件格式`;
- detecting template header clusters near page starts or page breaks;
- validating template boundaries with local document context;
- slicing each template into an independent `.docx`;
- writing `business_template_extraction.json`, `boundaries.json`, `review.md`, and `templates/*.docx`.

This skill must not parse scoring criteria, qualification requirements, bidder instructions, commitment requirements, or project core fields. Those remain owned by `bid-business-tender-structured-parser`.

## Invocation

```bash
python scripts/run_from_manifest.py <manifest>
```

The manifest is generated by the backend wrapper and contains `projectId`, `outputDir`, and `documents[]`.

## Output Contract

The runner writes one JSON file at `<outputDir>/business_template_extraction.json`:

```json
{
  "schemaVersion": "bid-business-template-extractor-v1",
  "skillName": "bid-business-template-extractor",
  "projectId": "project-id",
  "outputDir": "absolute-output-dir",
  "summary": {
    "documentCount": 1,
    "templateCount": 0,
    "warningCount": 0
  },
  "documents": [],
  "appendices": [],
  "warnings": []
}
```
```

- [ ] **Step 3: 检查复制后的脚本导入能被 Python 解析**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
python -m py_compile .\opencode\skill\bid-business-template-extractor\scripts\*.py
```

Expected:

```text
无 SyntaxError。
```

- [ ] **Step 4: Commit**

Run:

```powershell
git add opencode/skill/bid-business-template-extractor
git commit -m "feat: add business template extractor skill"
```

Expected:

```text
提交成功；如果当前工作树已有无关改动，只提交本 task 新增的 skill 文件。
```

---

### Task 2: 新增 skill runner，输出稳定 JSON 合同

**Files:**
- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-template-extractor\scripts\run_from_manifest.py`
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-template-extractor\scripts\pipeline.py`
- Test: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\tests\test_business_template_extractor_skill_script.py`

- [ ] **Step 1: Write the failing test**

Create `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\tests\test_business_template_extractor_skill_script.py`:

```python
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from docx import Document


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "opencode" / "skill" / "bid-business-template-extractor" / "scripts" / "run_from_manifest.py"


def build_business_format_docx(path: Path) -> None:
    doc = Document()
    doc.add_paragraph("第一章 招标公告")
    doc.add_paragraph("这里不是模板。")
    doc.add_page_break()
    doc.add_paragraph("第六章 投标文件格式")
    doc.add_paragraph("投标函的格式(1A)")
    doc.add_paragraph("致：招标人")
    doc.add_paragraph("投标人(盖公章)：")
    doc.add_paragraph("法定代表人或其委托代理人(签字)：")
    doc.add_paragraph("地址：")
    doc.add_paragraph("电话：")
    doc.add_paragraph("传真：")
    doc.add_paragraph("日期：       年    月   日")
    doc.add_page_break()
    doc.add_paragraph("法定代表人（单位负责人）身份证明：B")
    doc.add_paragraph("姓名：")
    doc.save(path)


def docx_text(path: Path) -> str:
    doc = Document(str(path))
    return "\n".join(paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip())


class BusinessTemplateExtractorSkillScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="business-template-extractor-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_runner_writes_appendices_and_preserves_bid_letter_tail(self) -> None:
        source = self.temp_dir / "招标文件.docx"
        output_dir = self.temp_dir / "output"
        manifest = self.temp_dir / "manifest.json"
        build_business_format_docx(source)
        manifest.write_text(
            json.dumps(
                {
                    "projectId": "proj-test",
                    "outputDir": str(output_dir),
                    "documents": [
                        {
                            "id": "DOC-1",
                            "name": "招标文件.docx",
                            "sourcePath": str(source),
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        completed = subprocess.run(
            [sys.executable, str(RUNNER), str(manifest)],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads((output_dir / "business_template_extraction.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["schemaVersion"], "bid-business-template-extractor-v1")
        self.assertEqual(payload["skillName"], "bid-business-template-extractor")
        self.assertEqual(payload["summary"]["templateCount"], len(payload["appendices"]))
        bid_letter = next(item for item in payload["appendices"] if "投标函" in item["title"])
        self.assertEqual(bid_letter["artifactType"], "business_attachment_template")
        self.assertEqual(bid_letter["sourceDocumentId"], "DOC-1")
        self.assertTrue(Path(bid_letter["docxPath"]).is_file())
        text = docx_text(Path(bid_letter["docxPath"]))
        self.assertIn("投标人(盖公章)：", text)
        self.assertIn("法定代表人或其委托代理人(签字)：", text)
        self.assertIn("日期：       年    月   日", text)
        self.assertNotIn("法定代表人（单位负责人）身份证明：B", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
python -m unittest tests.test_business_template_extractor_skill_script -v
```

Expected:

```text
FAIL 或 ERROR，原因是 run_from_manifest.py 尚未存在或未写出 business_template_extraction.json。
```

- [ ] **Step 3: Implement `run_from_manifest.py`**

Create `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-template-extractor\scripts\run_from_manifest.py`:

```python
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

CURRENT_DIR = Path(__file__).resolve().parent
SKILL_DIR = CURRENT_DIR.parent
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from scripts.pipeline import run_pipeline  # noqa: E402


SCHEMA_VERSION = "bid-business-template-extractor-v1"
SKILL_NAME = "bid-business-template-extractor"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_name(value: str, fallback: str) -> str:
    text = "".join(ch if ch not in '<>:"/\\|?*' else "_" for ch in value).strip()
    return text or fallback


def _build_empty_result(project_id: str, output_dir: Path) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "skillName": SKILL_NAME,
        "projectId": project_id,
        "outputDir": str(output_dir),
        "summary": {
            "documentCount": 0,
            "templateCount": 0,
            "warningCount": 0,
        },
        "documents": [],
        "appendices": [],
        "warnings": [],
    }


def _normalize_appendix(raw: dict[str, Any], *, document: dict[str, Any], index: int, output_dir: Path) -> dict[str, Any]:
    title = str(raw.get("title") or raw.get("evidence") or f"商务附件模板{index}").strip()
    docx_path = Path(str(raw.get("docxPath") or raw.get("outputPath") or ""))
    if not docx_path.is_absolute():
        docx_path = output_dir / docx_path
    return {
        "id": f"APPX-{index:04d}",
        "title": title,
        "evidence": title,
        "artifactType": "business_attachment_template",
        "templateType": str(raw.get("templateType") or "business_template"),
        "templateSectionTitle": str(raw.get("templateSectionTitle") or raw.get("regionTitle") or ""),
        "status": "generated",
        "rowCount": int(raw.get("rowCount") or 0),
        "docxPath": str(docx_path),
        "workspacePath": "",
        "sourceDocumentId": str(document.get("id") or ""),
        "sourceDocumentName": str(document.get("name") or ""),
        "sourcePath": str(document.get("sourcePath") or ""),
        "extractionMode": "business_template_extractor_skill",
        "startBlockIndex": raw.get("startBlockIndex"),
        "endBlockIndex": raw.get("endBlockIndex"),
        "quality": raw.get("quality") if isinstance(raw.get("quality"), dict) else {},
    }


def run_from_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    project_id = str(manifest.get("projectId") or "")
    output_dir = Path(str(manifest.get("outputDir") or manifest_path.parent / "business_template_extraction")).resolve()
    documents = manifest.get("documents") if isinstance(manifest.get("documents"), list) else []
    output_dir.mkdir(parents=True, exist_ok=True)

    result = _build_empty_result(project_id, output_dir)
    result["summary"]["documentCount"] = len(documents)

    appendices: list[dict[str, Any]] = []
    for document in documents:
        if not isinstance(document, dict):
            continue
        source = Path(str(document.get("sourcePath") or ""))
        if source.suffix.lower() != ".docx" or not source.is_file():
            continue
        document_output = output_dir / _safe_name(str(document.get("id") or source.stem), f"document-{len(result['documents']) + 1}")
        try:
            pipeline_result = run_pipeline(source, document_output)
            boundaries_path = document_output / "boundaries.json"
            boundaries = json.loads(boundaries_path.read_text(encoding="utf-8")) if boundaries_path.is_file() else {"templates": []}
            result["documents"].append(
                {
                    "id": str(document.get("id") or ""),
                    "name": str(document.get("name") or source.name),
                    "sourcePath": str(source),
                    "outputDir": str(document_output),
                    "summary": pipeline_result.get("summary") or {},
                }
            )
            for raw in boundaries.get("templates") or []:
                if isinstance(raw, dict):
                    appendices.append(_normalize_appendix(raw, document=document, index=len(appendices) + 1, output_dir=document_output))
        except Exception as exc:
            result["warnings"].append(
                {
                    "documentId": str(document.get("id") or ""),
                    "documentName": str(document.get("name") or source.name),
                    "message": f"商务模板提取失败：{exc}",
                }
            )

    result["appendices"] = appendices
    result["summary"]["templateCount"] = len(appendices)
    result["summary"]["warningCount"] = len(result["warnings"])
    _write_json(output_dir / "business_template_extraction.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: run_from_manifest.py <manifest>", file=sys.stderr)
        return 2
    result = run_from_manifest(Path(args[0]).resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Ensure `pipeline.py` exposes docx paths in `boundaries.json`**

Open `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-template-extractor\scripts\pipeline.py` and verify the copied implementation already does this:

```python
sliced_boundaries = slice_docx_by_boundaries(source_docx, blocks, boundaries, output_dir)
boundaries = {"templates": sliced_boundaries["templates"]}
write_json(output_dir / "boundaries.json", boundaries)
```

If the copied code differs, replace only that section with the snippet above so `boundaries.json` contains each template `outputPath`.

- [ ] **Step 5: Run test to verify it passes**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
python -m unittest tests.test_business_template_extractor_skill_script -v
```

Expected:

```text
Ran 1 test
OK
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add opencode/skill/bid-business-template-extractor tests/test_business_template_extractor_skill_script.py
git commit -m "feat: add business template extractor runner"
```

Expected:

```text
提交成功；只包含新 runner、必要 pipeline 调整和脚本级测试。
```

---

### Task 3: 新增后端 wrapper，把 extractor JSON 转为 appendices

**Files:**
- Create: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\app\services\business_template_extractor.py`
- Test: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\tests\test_business_template_extractor_skill_script.py`

- [ ] **Step 1: Write failing wrapper tests**

Append to `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\tests\test_business_template_extractor_skill_script.py`:

```python
from app.services.business_template_extractor import (
    build_business_template_extractor_manifest,
    convert_extractor_appendices,
)


class BusinessTemplateExtractorWrapperTests(unittest.TestCase):
    def test_build_manifest_keeps_only_docx_sources_and_output_dir(self) -> None:
        output_dir = Path("C:/tmp/business-template-output")
        manifest = build_business_template_extractor_manifest(
            project_id="proj-1",
            documents=[
                {"id": "DOC-1", "name": "招标.docx", "sourcePath": "C:/tmp/招标.docx"},
                {"id": "DOC-2", "name": "说明.txt", "sourcePath": "C:/tmp/说明.txt"},
            ],
            output_dir=output_dir,
        )

        self.assertEqual(manifest["projectId"], "proj-1")
        self.assertEqual(manifest["outputDir"], str(output_dir))
        self.assertEqual(len(manifest["documents"]), 1)
        self.assertEqual(manifest["documents"][0]["id"], "DOC-1")

    def test_convert_extractor_appendices_preserves_docx_path_for_prepare_outputs(self) -> None:
        payload = {
            "appendices": [
                {
                    "id": "APPX-0007",
                    "title": "附件2 投标价格表\nA投标价格总表\n表1 A-1  标段一",
                    "artifactType": "business_attachment_template",
                    "templateType": "business_template",
                    "templateSectionTitle": "第六章 投标文件格式",
                    "status": "generated",
                    "docxPath": "C:/tmp/TPL-0001.docx",
                    "sourceDocumentId": "DOC-1",
                    "sourceDocumentName": "招标.docx",
                }
            ]
        }

        appendices = convert_extractor_appendices(payload)

        self.assertEqual(len(appendices), 1)
        self.assertEqual(appendices[0]["id"], "APPX-0007")
        self.assertEqual(appendices[0]["title"], "附件2 投标价格表\nA投标价格总表\n表1 A-1  标段一")
        self.assertEqual(appendices[0]["artifactType"], "business_attachment_template")
        self.assertEqual(appendices[0]["extractionMode"], "business_template_extractor_skill")
        self.assertEqual(appendices[0]["docxPath"], "C:/tmp/TPL-0001.docx")
        self.assertEqual(appendices[0]["workspacePath"], "")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
python -m unittest tests.test_business_template_extractor_skill_script.BusinessTemplateExtractorWrapperTests -v
```

Expected:

```text
ERROR: No module named app.services.business_template_extractor
```

- [ ] **Step 3: Implement wrapper service**

Create `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\app\services\business_template_extractor.py`:

```python
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


SKILL_NAME = "bid-business-template-extractor"
SCHEMA_VERSION = "bid-business-template-extractor-v1"


def backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def skill_runner_path() -> Path:
    return backend_root() / "opencode" / "skill" / SKILL_NAME / "scripts" / "run_from_manifest.py"


def build_business_template_extractor_manifest(
    *,
    project_id: str,
    documents: list[dict[str, Any]],
    output_dir: Path,
) -> dict[str, Any]:
    manifest_documents: list[dict[str, Any]] = []
    for document in documents:
        source_path = Path(str(document.get("sourcePath") or ""))
        if source_path.suffix.lower() != ".docx":
            continue
        manifest_documents.append(
            {
                "id": str(document.get("id") or ""),
                "name": str(document.get("name") or source_path.name),
                "sourcePath": str(source_path),
                "textPath": str(document.get("textPath") or ""),
            }
        )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "skillName": SKILL_NAME,
        "projectId": project_id,
        "outputDir": str(output_dir),
        "documents": manifest_documents,
    }


def convert_extractor_appendices(payload: dict[str, Any]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for raw in payload.get("appendices") or []:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or raw.get("evidence") or "").strip()
        docx_path = str(raw.get("docxPath") or "").strip()
        if not title or not docx_path:
            continue
        converted.append(
            {
                "id": str(raw.get("id") or f"APPX-{len(converted) + 1:04d}"),
                "title": title,
                "evidence": str(raw.get("evidence") or title),
                "artifactType": "business_attachment_template",
                "templateType": str(raw.get("templateType") or "business_template"),
                "templateSectionTitle": str(raw.get("templateSectionTitle") or ""),
                "status": str(raw.get("status") or "generated"),
                "rowCount": int(raw.get("rowCount") or 0),
                "docxPath": docx_path,
                "workspacePath": str(raw.get("workspacePath") or ""),
                "sourceDocumentId": str(raw.get("sourceDocumentId") or ""),
                "sourceDocumentName": str(raw.get("sourceDocumentName") or ""),
                "sourcePath": str(raw.get("sourcePath") or ""),
                "extractionMode": "business_template_extractor_skill",
                "startBlockIndex": raw.get("startBlockIndex"),
                "endBlockIndex": raw.get("endBlockIndex"),
                "quality": raw.get("quality") if isinstance(raw.get("quality"), dict) else {},
            }
        )
    return converted


def run_business_template_extractor(
    *,
    project_id: str,
    documents: list[dict[str, Any]],
    project_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str]:
    output_dir = project_dir / "business_template_extraction"
    manifest_path = project_dir / "business_template_extraction_manifest.json"
    manifest = build_business_template_extractor_manifest(
        project_id=project_id,
        documents=documents,
        output_dir=output_dir,
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if not manifest["documents"]:
        return [], None, "未找到可用于商务模板提取的 DOCX 招标文件。"

    runner = skill_runner_path()
    completed = subprocess.run(
        [sys.executable, str(runner), str(manifest_path)],
        cwd=str(backend_root()),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or f"退出码 {completed.returncode}"
        return [], None, f"商务模板提取 skill 调用失败，已回退旧逻辑：{message}"

    result_path = output_dir / "business_template_extraction.json"
    if not result_path.is_file():
        return [], None, "商务模板提取 skill 未生成 business_template_extraction.json，已回退旧逻辑。"
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    appendices = convert_extractor_appendices(payload)
    if not appendices:
        return [], payload, "商务模板提取 skill 未识别到模板，已回退旧逻辑。"
    return appendices, payload, ""
```

- [ ] **Step 4: Run wrapper tests**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
python -m unittest tests.test_business_template_extractor_skill_script.BusinessTemplateExtractorWrapperTests -v
```

Expected:

```text
Ran 2 tests
OK
```

- [ ] **Step 5: Run full skill script tests**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
python -m unittest tests.test_business_template_extractor_skill_script -v
```

Expected:

```text
Ran 3 tests
OK
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add app/services/business_template_extractor.py tests/test_business_template_extractor_skill_script.py
git commit -m "feat: add business template extractor backend wrapper"
```

Expected:

```text
提交成功。
```

---

### Task 4: 修改 S1 business pipeline，优先采用 extractor 产物并保留旧逻辑 fallback

**Files:**
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\app\services\parsing.py`
- Test: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\tests\test_parse_pipeline.py`

- [ ] **Step 1: Write failing pipeline test**

Append this helper near the existing docx fixture builders in `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\tests\test_parse_pipeline.py`:

```python
def build_business_multilevel_template_cluster_docx_bytes() -> bytes:
    doc = Document()
    doc.add_paragraph("第一章 招标公告")
    doc.add_paragraph("投标文件格式目录")
    doc.add_paragraph("附件2 投标价格表 ........ 12")
    doc.add_page_break()
    doc.add_paragraph("第六章 投标文件格式")
    doc.add_paragraph("附件2 投标价格表")
    doc.add_paragraph("A投标价格总表")
    doc.add_paragraph("表1 A-1  标段一")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "序号"
    table.cell(0, 1).text = "价格"
    table.cell(1, 0).text = "1"
    table.cell(1, 1).text = ""
    doc.add_page_break()
    doc.add_paragraph("D 技术服务的分项报价")
    doc.add_paragraph("D-1除质保期服务外的技术指导")
    next_table = doc.add_table(rows=1, cols=2)
    next_table.cell(0, 0).text = "服务"
    next_table.cell(0, 1).text = "报价"
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
```

Append this test method inside `ParsePipelineTests`:

```python
def test_business_bid_uses_template_extractor_and_keeps_header_cluster(self) -> None:
    project_id = self.create_business_project()
    response = self.client.post(
        self.parse_url(project_id),
        files=[
            (
                "tenderFiles",
                (
                    "商务招标文件.docx",
                    build_business_multilevel_template_cluster_docx_bytes(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ),
            )
        ],
    )
    self.assertEqual(response.status_code, 200)
    payload = response.json()
    structured = payload["structured"]
    appendices = structured["appendices"]
    self.assertGreaterEqual(len(appendices), 2)
    first = next(item for item in appendices if "表1 A-1" in item["title"])
    self.assertEqual(first["extractionMode"], "business_template_extractor_skill")
    self.assertIn("附件2 投标价格表", first["title"])
    self.assertIn("A投标价格总表", first["title"])
    self.assertTrue(Path(first["docxPath"]).is_file())
    first_doc = Document(str(Path(first["docxPath"])))
    first_text = "\n".join(paragraph.text for paragraph in first_doc.paragraphs if paragraph.text.strip())
    self.assertTrue(first_text.startswith("附件2 投标价格表\nA投标价格总表\n表1 A-1  标段一"))
    self.assertNotIn("D 技术服务的分项报价", first_text)
    parse_dir = settings.parsed_dir / project_id
    extraction_path = parse_dir / "business_template_extraction" / "business_template_extraction.json"
    self.assertTrue(extraction_path.is_file())
    skill_manifest = json.loads((parse_dir / "s1_parse_manifest.json").read_text(encoding="utf-8"))
    self.assertEqual(skill_manifest["businessTemplateExtractionPath"], str(extraction_path))
    self.assertEqual(skill_manifest["businessTemplateExtractionSummary"]["templateCount"], len(appendices))
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
python -m unittest tests.test_parse_pipeline.ParsePipelineTests.test_business_bid_uses_template_extractor_and_keeps_header_cluster -v
```

Expected:

```text
FAIL，原因是 extractionMode 仍来自旧逻辑，或 s1_parse_manifest.json 没有 businessTemplateExtractionPath。
```

- [ ] **Step 3: Import wrapper in `parsing.py`**

Add near other service imports in `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\app\services\parsing.py`:

```python
from app.services.business_template_extractor import run_business_template_extractor
```

- [ ] **Step 4: Replace appendix extraction block in `parse_tender_documents`**

Find the current block:

```python
structured_result = _extract_structured_requirements(documents, texts_by_id)
appendices = _extract_markdown_appendices(project_id, documents, texts_by_id, profile=profile)
appendices.extend(_extract_docx_appendices(project_id, documents, start_index=len(appendices), profile=profile))
if profile.key == "business":
    appendices.extend(
        _extract_text_business_appendices(
            project_id,
            documents,
            texts_by_id,
            start_index=len(appendices),
            profile=profile,
        )
    )
appendices = _prepare_appendix_outputs(project_id, appendices, renumber=True, profile=profile)
if profile.key == "business":
    appendices = _apply_business_template_semantic_review(
        appendices,
        run_semantic_review=not settings.s1_parse_opencode_enabled,
    )
```

Replace it with:

```python
structured_result = _extract_structured_requirements(documents, texts_by_id)
template_extraction_payload: dict[str, Any] | None = None
template_extraction_warning = ""
template_extraction_path = project_dir / "business_template_extraction" / "business_template_extraction.json"

if profile.key == "business":
    extractor_appendices, template_extraction_payload, template_extraction_warning = run_business_template_extractor(
        project_id=project_id,
        documents=documents,
        project_dir=project_dir,
    )
    if extractor_appendices:
        appendices = extractor_appendices
    else:
        if template_extraction_warning:
            warnings.append(template_extraction_warning)
        appendices = _extract_markdown_appendices(project_id, documents, texts_by_id, profile=profile)
        appendices.extend(_extract_docx_appendices(project_id, documents, start_index=len(appendices), profile=profile))
        appendices.extend(
            _extract_text_business_appendices(
                project_id,
                documents,
                texts_by_id,
                start_index=len(appendices),
                profile=profile,
            )
        )
else:
    appendices = _extract_markdown_appendices(project_id, documents, texts_by_id, profile=profile)
    appendices.extend(_extract_docx_appendices(project_id, documents, start_index=len(appendices), profile=profile))

appendices = _prepare_appendix_outputs(project_id, appendices, renumber=True, profile=profile)
if profile.key == "business" and not template_extraction_payload:
    appendices = _apply_business_template_semantic_review(
        appendices,
        run_semantic_review=not settings.s1_parse_opencode_enabled,
    )
```

Rationale for the conditional semantic review:

- extractor 已经完成边界判断和切片，不再让旧 `_apply_business_template_semantic_review(...)` 按旧规则二次过滤边界；
- fallback 旧逻辑时仍保留旧 review 行为。

- [ ] **Step 5: Add extractor references to `s1_parse_manifest.json`**

Find the `skill_manifest = { ... }` block and add these keys:

```python
"businessTemplateExtractionPath": str(template_extraction_path) if profile.key == "business" and template_extraction_path.is_file() else "",
"businessTemplateExtractionSummary": (
    template_extraction_payload.get("summary")
    if profile.key == "business" and isinstance(template_extraction_payload, dict)
    else {}
),
```

The full manifest block should include:

```python
skill_manifest = {
    "projectId": project_id,
    "bidType": profile.bid_type,
    "parseProfile": profile.key,
    "targetSkill": profile.skill_name,
    "combinedTextPath": str(combined_text_path),
    "structuredResultPath": str(structured_path),
    "businessTemplateExtractionPath": str(template_extraction_path) if profile.key == "business" and template_extraction_path.is_file() else "",
    "businessTemplateExtractionSummary": (
        template_extraction_payload.get("summary")
        if profile.key == "business" and isinstance(template_extraction_payload, dict)
        else {}
    ),
    "documents": documents,
    "targets": list(profile.targets),
}
```

- [ ] **Step 6: Run pipeline test**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
python -m unittest tests.test_parse_pipeline.ParsePipelineTests.test_business_bid_uses_template_extractor_and_keeps_header_cluster -v
```

Expected:

```text
Ran 1 test
OK
```

- [ ] **Step 7: Run existing business template parse tests**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
python -m unittest tests.test_parse_pipeline.ParsePipelineTests.test_business_bid_docx_attachment_templates_are_sliced_with_quality_metadata -v
python -m unittest tests.test_parse_pipeline.ParsePipelineTests.test_business_bid_docx_attachment_templates_ignore_toc_and_keep_following_table -v
python -m unittest tests.test_parse_pipeline.ParsePipelineTests.test_business_bid_text_attachment_template_docx_keeps_template_body -v
```

Expected:

```text
三条命令均 OK。若旧测试断言 extractionMode 或 templateType 与新 extractor 不一致，只更新断言到新合同，不放宽标题簇、docxPath 存在、正文不吞下一模板这些核心断言。
```

- [ ] **Step 8: Commit**

Run:

```powershell
git add app/services/parsing.py tests/test_parse_pipeline.py
git commit -m "feat: use business template extractor in s1 pipeline"
```

Expected:

```text
提交成功。
```

---

### Task 5: 固化 reducer 规则，防止结构化 skill 覆盖 extractor appendices

**Files:**
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\app\services\parsing.py`
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\tests\test_business_parse_skill_script.py`
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\tests\test_parse_pipeline.py`

- [ ] **Step 1: Write reducer-focused pipeline test**

Append inside `ParsePipelineTests`:

```python
def test_business_template_extractor_appendices_survive_skill_result_merge(self) -> None:
    project_id = self.create_business_project()
    response = self.client.post(
        self.parse_url(project_id),
        files=[
            (
                "tenderFiles",
                (
                    "商务招标文件.docx",
                    build_business_multilevel_template_cluster_docx_bytes(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ),
            )
        ],
    )
    self.assertEqual(response.status_code, 200)
    appendices = response.json()["structured"]["appendices"]
    self.assertTrue(appendices)
    self.assertTrue(all(item["extractionMode"] == "business_template_extractor_skill" for item in appendices))
    self.assertTrue(any("表1 A-1" in item["title"] and "附件2 投标价格表" in item["title"] for item in appendices))
```

- [ ] **Step 2: Run test to verify current behavior**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
python -m unittest tests.test_parse_pipeline.ParsePipelineTests.test_business_template_extractor_appendices_survive_skill_result_merge -v
```

Expected:

```text
如果 Task 4 的初步合并已足够，测试可能直接 OK；仍然执行 Step 3 固化代码，使优先级清晰可维护。
```

- [ ] **Step 3: Modify final merge block in `parse_tender_documents`**

Find:

```python
resolved_structured = structured_result.setdefault("structured", {})
if not resolved_structured.get("appendices"):
    resolved_structured["appendices"] = appendices
elif isinstance(resolved_structured.get("appendices"), list):
    resolved_structured["appendices"] = _prepare_appendix_outputs(
        project_id,
        resolved_structured["appendices"],
        renumber=True,
        profile=profile,
    )
```

Replace with:

```python
resolved_structured = structured_result.setdefault("structured", {})
extractor_appendices_are_authoritative = (
    profile.key == "business"
    and bool(appendices)
    and all(
        isinstance(item, dict)
        and str(item.get("extractionMode") or "") == "business_template_extractor_skill"
        for item in appendices
    )
)
if extractor_appendices_are_authoritative:
    resolved_structured["appendices"] = appendices
elif not resolved_structured.get("appendices"):
    resolved_structured["appendices"] = appendices
elif isinstance(resolved_structured.get("appendices"), list):
    resolved_structured["appendices"] = _prepare_appendix_outputs(
        project_id,
        resolved_structured["appendices"],
        renumber=True,
        profile=profile,
    )
```

- [ ] **Step 4: Ensure the existing business structured parser preserves appendices**

Open `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-tender-structured-parser\scripts\business_contract.py` and verify the builder already reads local `structuredResultPath` or manifest context and preserves existing `structured.appendices`.

If it currently replaces appendices with its own extraction, change only the final result assembly so it does:

```python
existing_appendices = []
structured_result_path = manifest.get("structuredResultPath")
if structured_result_path:
    path = Path(str(structured_result_path))
    if path.is_file():
        local_payload = json.loads(path.read_text(encoding="utf-8"))
        local_structured = local_payload.get("structured") if isinstance(local_payload, dict) else {}
        if isinstance(local_structured, dict) and isinstance(local_structured.get("appendices"), list):
            existing_appendices = local_structured["appendices"]

structured["appendices"] = existing_appendices
```

Do not make this skill call the template extractor.

- [ ] **Step 5: Add/adjust script test for structured parser preserving appendices**

In `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\tests\test_business_parse_skill_script.py`, add a test that writes a manifest with `structuredResultPath` containing extractor appendices and asserts the runner output keeps them:

```python
def test_business_parser_preserves_template_extractor_appendices(self) -> None:
    with tempfile.TemporaryDirectory() as temp:
        temp_dir = Path(temp)
        structured_path = temp_dir / "s1_structured_result.json"
        manifest_path = temp_dir / "manifest.json"
        structured_path.write_text(
            json.dumps(
                {
                    "structured": {
                        "appendices": [
                            {
                                "id": "APPX-0001",
                                "title": "附件2 投标价格表\nA投标价格总表\n表1 A-1  标段一",
                                "artifactType": "business_attachment_template",
                                "extractionMode": "business_template_extractor_skill",
                                "docxPath": "C:/tmp/TPL-0001.docx",
                            }
                        ]
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        combined_path = temp_dir / "combined.txt"
        combined_path.write_text("第六章 投标文件格式\n商务评分 企业业绩 5分", encoding="utf-8")
        manifest_path.write_text(
            json.dumps(
                {
                    "projectId": "proj-1",
                    "parseProfile": "business",
                    "combinedTextPath": str(combined_path),
                    "structuredResultPath": str(structured_path),
                    "documents": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        completed = subprocess.run(
            [sys.executable, str(RUNNER), str(manifest_path)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        appendices = payload["structured"]["appendices"]
        self.assertEqual(len(appendices), 1)
        self.assertEqual(appendices[0]["extractionMode"], "business_template_extractor_skill")
        self.assertIn("表1 A-1", appendices[0]["title"])
```

Use the existing constants/import style in that test file; if `RUNNER`, `tempfile`, `subprocess`, or `sys` already exist, reuse them.

- [ ] **Step 6: Run reducer and script tests**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
python -m unittest tests.test_parse_pipeline.ParsePipelineTests.test_business_template_extractor_appendices_survive_skill_result_merge -v
python -m unittest tests.test_business_parse_skill_script -v
```

Expected:

```text
两条命令均 OK。
```

- [ ] **Step 7: Commit**

Run:

```powershell
git add app/services/parsing.py opencode/skill/bid-business-tender-structured-parser/scripts/business_contract.py tests/test_business_parse_skill_script.py tests/test_parse_pipeline.py
git commit -m "fix: preserve extractor appendices during business parse merge"
```

Expected:

```text
提交成功；如果 business_contract.py 没有改动，不要把它加入提交。
```

---

### Task 6: 验证路由关系，确保两个 skill 同页顺序协作而非互相替代

**Files:**
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\tests\test_s1parse_router_script.py`
- Inspect: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\s1parse_router.py`

- [ ] **Step 1: Write router behavior test**

Open `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\tests\test_s1parse_router_script.py` and add a test matching the file’s current subprocess helper style:

```python
def test_business_s1parse_router_still_targets_structured_parser_when_template_extraction_path_exists(self) -> None:
    with tempfile.TemporaryDirectory() as temp:
        temp_dir = Path(temp)
        combined_path = temp_dir / "combined.txt"
        structured_path = temp_dir / "structured.json"
        extraction_path = temp_dir / "business_template_extraction.json"
        manifest_path = temp_dir / "s1_parse_manifest.json"
        combined_path.write_text("第六章 投标文件格式\n商务评分 企业业绩 5分", encoding="utf-8")
        structured_path.write_text(json.dumps({"structured": {"appendices": []}}, ensure_ascii=False), encoding="utf-8")
        extraction_path.write_text(
            json.dumps(
                {
                    "schemaVersion": "bid-business-template-extractor-v1",
                    "appendices": [],
                    "summary": {"templateCount": 0},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        manifest_path.write_text(
            json.dumps(
                {
                    "projectId": "proj-1",
                    "parseProfile": "business",
                    "combinedTextPath": str(combined_path),
                    "structuredResultPath": str(structured_path),
                    "businessTemplateExtractionPath": str(extraction_path),
                    "documents": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        completed = subprocess.run(
            [sys.executable, str(ROUTER), str(manifest_path)],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["structured"]["targetSkill"], "bid-business-tender-structured-parser")
        self.assertEqual(payload["structured"]["schemaVersion"], "bid-business-tender-structured-v1")
```

Use the existing `ROUTER` constant and imports in the file. If names differ, adapt only the variable names, not the assertion intent.

- [ ] **Step 2: Run router test**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
python -m unittest tests.test_s1parse_router_script -v
```

Expected:

```text
OK；如果失败，修正 s1parse_router.py 只按 parseProfile 路由到结构化 parser，不把 businessTemplateExtractionPath 当作路由目标。
```

- [ ] **Step 3: Inspect router mapping**

Open `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\s1parse_router.py` and confirm mapping remains:

```python
RUNNERS = {
    "技术标": SKILL_ROOT / "bid-tech-tender-structured-parser" / "scripts" / "run_from_manifest.py",
    "商务标": SKILL_ROOT / "bid-business-tender-structured-parser" / "scripts" / "run_from_manifest.py",
}
```

Do not add `bid-business-template-extractor` to this router. The extractor is invoked by backend wrapper before `_run_parse_skill(...)`.

- [ ] **Step 4: Commit**

Run:

```powershell
git add tests/test_s1parse_router_script.py opencode/skill/s1parse_router.py
git commit -m "test: document business s1 skill routing boundaries"
```

Expected:

```text
提交成功；如果 s1parse_router.py 未修改，不要加入提交。
```

---

### Task 7: 添加回归测试覆盖曾经失败的边界类型

**Files:**
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\tests\test_business_template_extractor_skill_script.py`

- [ ] **Step 1: Add regression fixture builder**

Append near existing fixture helpers:

```python
def build_boundary_regression_docx(path: Path) -> None:
    doc = Document()
    doc.add_paragraph("第六章 投标文件格式")
    doc.add_paragraph("附件3 货物规格一览表")
    doc.add_paragraph("表3 A")
    doc.add_table(rows=1, cols=2).cell(0, 0).text = "货物名称"
    doc.add_page_break()
    doc.add_paragraph("附件4 商务条款偏差表")
    doc.add_table(rows=1, cols=2).cell(0, 0).text = "条款号"
    doc.add_page_break()
    doc.add_paragraph("附件6 履约保证函格式")
    doc.add_paragraph("履约保证函正文")
    doc.add_page_break()
    doc.add_paragraph("附件7 资格证明文件")
    doc.add_paragraph("附件7A 商务部分摘要表")
    doc.add_table(rows=1, cols=2).cell(0, 0).text = "摘要"
    doc.add_page_break()
    doc.add_paragraph("7D-4表 现金流量表")
    doc.add_table(rows=1, cols=2).cell(0, 0).text = "现金流量"
    doc.add_page_break()
    doc.add_paragraph("附件7E")
    doc.add_paragraph("7E-1表 企业资信等级证书情况")
    doc.add_table(rows=1, cols=2).cell(0, 0).text = "资信"
    doc.add_page_break()
    doc.add_paragraph("开标价格表")
    doc.add_table(rows=1, cols=2).cell(0, 0).text = "开标价"
    doc.add_page_break()
    doc.add_page_break()
    doc.add_paragraph("特殊附件1")
    doc.add_paragraph("保密承诺书")
    doc.add_paragraph("承诺正文")
    doc.save(path)
```

- [ ] **Step 2: Add regression test**

Append inside `BusinessTemplateExtractorSkillScriptTests`:

```python
def test_runner_regression_boundaries_do_not_swallow_next_template_clusters(self) -> None:
    source = self.temp_dir / "边界回归.docx"
    output_dir = self.temp_dir / "regression-output"
    manifest = self.temp_dir / "regression-manifest.json"
    build_boundary_regression_docx(source)
    manifest.write_text(
        json.dumps(
            {
                "projectId": "proj-regression",
                "outputDir": str(output_dir),
                "documents": [
                    {
                        "id": "DOC-1",
                        "name": "边界回归.docx",
                        "sourcePath": str(source),
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, str(RUNNER), str(manifest)],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )

    self.assertEqual(completed.returncode, 0, completed.stderr)
    payload = json.loads((output_dir / "business_template_extraction.json").read_text(encoding="utf-8"))
    titles = [item["title"] for item in payload["appendices"]]
    self.assertTrue(any("附件3 货物规格一览表" in title and "表3 A" in title for title in titles))
    self.assertTrue(any("附件4 商务条款偏差表" in title for title in titles))
    self.assertTrue(any("附件7 资格证明文件" in title for title in titles))
    self.assertTrue(any("7D-4" in title for title in titles))
    self.assertTrue(any("7E-1" in title for title in titles))
    self.assertTrue(any("保密承诺书" in title for title in titles))

    def item_text(title_part: str) -> str:
        item = next(item for item in payload["appendices"] if title_part in item["title"])
        return docx_text(Path(item["docxPath"]))

    self.assertNotIn("附件4 商务条款偏差表", item_text("表3 A"))
    self.assertNotIn("附件7 资格证明文件", item_text("履约保证函格式"))
    self.assertNotIn("附件7E", item_text("7D-4"))
    self.assertNotIn("特殊附件1", item_text("开标价格表"))
    self.assertTrue(item_text("保密承诺书").startswith("特殊附件1\n保密承诺书"))
```

- [ ] **Step 3: Run regression test**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
python -m unittest tests.test_business_template_extractor_skill_script.BusinessTemplateExtractorSkillScriptTests.test_runner_regression_boundaries_do_not_swallow_next_template_clusters -v
```

Expected:

```text
OK。若失败，修复 extractor 通用边界逻辑，不写针对某个标题文本的特例。
```

- [ ] **Step 4: If regression fails, fix only the generic boundary modules**

Allowed files for this step:

```text
C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-template-extractor\scripts\text_rules.py
C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-template-extractor\scripts\anchor_detector.py
C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-template-extractor\scripts\header_cluster_detector.py
C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-template-extractor\scripts\boundary_planner.py
C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\opencode\skill\bid-business-template-extractor\scripts\boundary_validator.py
```

The fix must follow these principles:

- A boundary candidate is promoted by structural evidence: format chapter region, page-start/page-break proximity, heading-like style/short line, numbering pattern, and following body/table evidence.
- Header clusters are kept with the child template when they are immediately before the child title and are part of the same page-start cluster.
- A new candidate anchor starts the next template before slicing; it must not remain as the previous template tail.
- Container headings such as `附件7 资格证明文件` can be emitted as their own template only when they own meaningful following content or group the next child cluster; they must not be swallowed by the previous template.
- Do not add code that checks for one concrete problem string such as `法定代表人或其委托代理人(签字)`、`D 技术服务的分项报价`、`附件7E`、`特殊附件1` as a one-off exclusion.

- [ ] **Step 5: Run full extractor tests**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
python -m unittest tests.test_business_template_extractor_skill_script -v
```

Expected:

```text
全部 OK。
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add opencode/skill/bid-business-template-extractor tests/test_business_template_extractor_skill_script.py
git commit -m "test: cover business template boundary regressions"
```

Expected:

```text
提交成功。
```

---

### Task 8: 跑端到端验证并记录人工验收路径

**Files:**
- Verify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend`
- Verify output: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\data\parsed\<project_id>\business_template_extraction`
- Verify output: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\data\parsed\<project_id>\s1_appendices`

- [ ] **Step 1: Run targeted tests**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
python -m unittest tests.test_business_template_extractor_skill_script -v
python -m unittest tests.test_business_parse_skill_script -v
python -m unittest tests.test_s1parse_router_script -v
python -m unittest tests.test_parse_pipeline.ParsePipelineTests.test_business_bid_uses_template_extractor_and_keeps_header_cluster -v
python -m unittest tests.test_parse_pipeline.ParsePipelineTests.test_business_template_extractor_appendices_survive_skill_result_merge -v
```

Expected:

```text
所有命令 OK。
```

- [ ] **Step 2: Run existing business parse regression subset**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
python -m unittest tests.test_parse_pipeline.ParsePipelineTests.test_business_bid_parse_returns_business_contract_without_technical_groups -v
python -m unittest tests.test_parse_pipeline.ParsePipelineTests.test_business_bid_participating_promotes_parse_json_to_business_workspace -v
python -m unittest tests.test_parse_pipeline.ParsePipelineTests.test_business_bid_docx_attachment_templates_are_sliced_with_quality_metadata -v
python -m unittest tests.test_parse_pipeline.ParsePipelineTests.test_business_bid_docx_attachment_templates_ignore_toc_and_keep_following_table -v
python -m unittest tests.test_parse_pipeline.ParsePipelineTests.test_business_bid_text_attachment_template_docx_keeps_template_body -v
```

Expected:

```text
所有命令 OK。
```

- [ ] **Step 3: Run full unit suite when local time budget allows**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
python -m unittest discover -s tests -v
```

Expected:

```text
OK。若全量测试因环境依赖失败，记录具体失败测试名、错误信息和已通过的 targeted tests。
```

- [ ] **Step 4: Manual output inspection**

After running the business parse API test, inspect one generated project directory. Use the actual `project_id` printed or infer from test temp data:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
Get-ChildItem .\data\parsed -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 3 FullName
```

Open the latest business project parse directory and verify:

```text
business_template_extraction\business_template_extraction.json exists
business_template_extraction\<document-id>\boundaries.json exists
business_template_extraction\<document-id>\review.md exists
s1_appendices\APPX-*.docx exists
s1_parse_manifest.json contains businessTemplateExtractionPath
s1_structured_result.json structured.appendices[].extractionMode is business_template_extractor_skill
```

- [ ] **Step 5: Commit final verification-only test adjustments**

Run:

```powershell
git status --short
```

Expected:

```text
只剩本计划范围内文件变更；没有误改 data/、output/、__pycache__/、临时 docx。
```

If tests created ignored artifacts only, do not commit them. If tracked tests needed assertion updates during verification, commit them:

```powershell
git add tests/test_parse_pipeline.py tests/test_business_parse_skill_script.py tests/test_s1parse_router_script.py tests/test_business_template_extractor_skill_script.py
git commit -m "test: verify business template extractor integration"
```

Expected:

```text
有测试变更时提交成功；无测试变更时跳过提交。
```

---

### Task 9: Feature flag 与旧逻辑清理边界

**Files:**
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\app\core\config.py`
- Modify: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\app\services\parsing.py`
- Test: `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\tests\test_parse_pipeline.py`

- [ ] **Step 1: Add feature flag test for fallback path**

Append inside `ParsePipelineTests`:

```python
def test_business_template_extractor_can_fallback_to_legacy_when_disabled(self) -> None:
    project_id = self.create_business_project()
    with patch("app.services.parsing.settings.business_template_extractor_enabled", False):
        response = self.client.post(
            self.parse_url(project_id),
            files=[
                (
                    "tenderFiles",
                    (
                        "商务招标文件.docx",
                        build_business_attachment_templates_docx_bytes(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
        )
    self.assertEqual(response.status_code, 200)
    appendices = response.json()["structured"]["appendices"]
    self.assertTrue(appendices)
    self.assertFalse(all(item.get("extractionMode") == "business_template_extractor_skill" for item in appendices))
```

- [ ] **Step 2: Run test to verify it fails before flag exists**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
python -m unittest tests.test_parse_pipeline.ParsePipelineTests.test_business_template_extractor_can_fallback_to_legacy_when_disabled -v
```

Expected:

```text
ERROR 或 FAIL，原因是 settings.business_template_extractor_enabled 不存在或 parsing.py 未读取它。
```

- [ ] **Step 3: Add setting**

Open `C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend\app\core\config.py` and add to the settings class near other S1 parse flags:

```python
business_template_extractor_enabled: bool = Field(default=True, alias="BUSINESS_TEMPLATE_EXTRACTOR_ENABLED")
```

Use the exact field declaration style already used in that file. If the project uses plain class attributes instead of `Field(...)` for booleans, use:

```python
business_template_extractor_enabled: bool = True
```

- [ ] **Step 4: Read setting in `parse_tender_documents`**

In the Task 4 block, change:

```python
if profile.key == "business":
```

to:

```python
if profile.key == "business" and settings.business_template_extractor_enabled:
```

Then add an explicit legacy branch:

```python
elif profile.key == "business":
    appendices = _extract_markdown_appendices(project_id, documents, texts_by_id, profile=profile)
    appendices.extend(_extract_docx_appendices(project_id, documents, start_index=len(appendices), profile=profile))
    appendices.extend(
        _extract_text_business_appendices(
            project_id,
            documents,
            texts_by_id,
            start_index=len(appendices),
            profile=profile,
        )
    )
else:
    appendices = _extract_markdown_appendices(project_id, documents, texts_by_id, profile=profile)
    appendices.extend(_extract_docx_appendices(project_id, documents, start_index=len(appendices), profile=profile))
```

Do not remove old functions in this task.

- [ ] **Step 5: Run feature flag and normal extractor tests**

Run:

```powershell
cd C:\Users\99065\Documents\商务标V2\code\sewpg-bid-backend
python -m unittest tests.test_parse_pipeline.ParsePipelineTests.test_business_template_extractor_can_fallback_to_legacy_when_disabled -v
python -m unittest tests.test_parse_pipeline.ParsePipelineTests.test_business_bid_uses_template_extractor_and_keeps_header_cluster -v
```

Expected:

```text
两条命令均 OK。
```

- [ ] **Step 6: Commit**

Run:

```powershell
git add app/core/config.py app/services/parsing.py tests/test_parse_pipeline.py
git commit -m "feat: gate business template extractor with fallback flag"
```

Expected:

```text
提交成功。
```

---

## 最终验收标准

- `http://localhost/parse/business` 页面仍只触发一次 S1 解析请求。
- 后端内部先运行 `bid-business-template-extractor`，再运行 `bid-business-tender-structured-parser`。
- `bid-business-template-extractor` 写出：
  - `business_template_extraction/business_template_extraction.json`
  - `business_template_extraction/<document-id>/boundaries.json`
  - `business_template_extraction/<document-id>/review.md`
  - `business_template_extraction/<document-id>/templates/*.docx`
- 最终 `s1_structured_result.json` 中：
  - `structured.appendices[]` 来源优先级为 extractor > skill returned appendices > legacy appendices；
  - extractor 成功时 `structured.appendices[].extractionMode == "business_template_extractor_skill"`；
  - `docxPath` 指向 `data/parsed/<project_id>/s1_appendices/APPX-*.docx`；
  - `workspacePath` 可被后续参与投标流程提升到 `business-workspace/appendices`。
- `s1_parse_manifest.json` 中包含只读引用：
  - `businessTemplateExtractionPath`
  - `businessTemplateExtractionSummary`
- 现有 `bid-business-tender-structured-parser` 不负责模板边界切片，不覆盖 extractor appendices。
- `s1parse_router.py` 仍只把 business S1 路由到 `bid-business-tender-structured-parser`，不直接路由 extractor。
- 曾经出现的问题均有回归覆盖：
  - `投标函的格式(1A)` 保留尾部签字、地址、电话、传真、日期字段；
  - `附件2 投标价格表 / A投标价格总表 / 表1 A-1 标段一` 标题簇完整保留；
  - `表2 C` 不吞 `D 技术服务的分项报价`；
  - `履约保证函格式` 不吞 `附件7 资格证明文件`；
  - `7D-4表 现金流量表` 不吞 `附件7E`；
  - `开标价格表` 不吞 `特殊附件1`，`特殊附件1` 归入 `保密承诺书` 标题簇。

## 执行注意事项

- 本仓库可能已有用户或其他 agent 的未提交改动；执行计划时不要回滚无关改动。
- 每个 task 提交前运行 `git status --short`，只 stage 本 task 涉及文件。
- 不要提交 `data/`、`output/`、`__pycache__/`、临时 `.docx`、测试运行生成物。
- 如果某个旧测试依赖旧 `extractionMode` 文案，更新测试到新合同，但不能放松模板正文完整性和“不吞下一模板标题”的断言。
- 如果 extractor 在真实样本上失败，优先检查 `boundaries.draft.json`、`boundaries.json`、`candidate_windows.json`、`review.md`，然后修改通用边界规则；禁止写针对单个标题文本的补丁。

## Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-29-business-template-extractor-integration.md`.

Two execution options:

1. **Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - execute tasks in this session using executing-plans, batch execution with checkpoints.
