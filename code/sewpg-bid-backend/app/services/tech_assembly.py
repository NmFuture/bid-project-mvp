from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

from app.core.config import BASE_DIR, settings
from app.services.material_store import material_store
from app.services.minio_client import minio_client
from app.services.onlyoffice_documents import document_path
from app.services.opencode_client import OpencodeClient
from app.services.store import now_iso, store
from app.services.workspace_artifacts import legacy_workspace_roots, technical_workspace_stage_dir
from app.services.wiki_export import export_wiki


ASSEMBLER_SKILL_NAME = "bid-tech-assembler"
ASSEMBLER_SKILL_COMMAND = "s7assemble"
ASSEMBLER_SKILL_DIR = BASE_DIR / "opencode" / "skill" / "bid-tech-assembler"
ASSEMBLER_RUNNER = ASSEMBLER_SKILL_DIR / "scripts" / "run_from_manifest.py"
WORD_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def assemble_tech_bid_for_project_with_progress(
    project_id: str,
    data: dict[str, Any] | None = None,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    project = store.get_project(project_id)
    outline_state = store.get_outline_state(project_id)
    review_state = store.get_review_items(project_id)
    parse_storage = store.get_parse_storage(project_id)
    _, template_file_records = store.get_parse_inputs(project_id)

    if outline_state.get("reviewStatus") != "confirmed":
        raise ValueError("请先完成目录确认后再生成标书。")
    if not review_state.get("confirmed"):
        raise ValueError("请先完成缺口处理确认后再生成标书。")

    started_at = time.monotonic()
    work_dir = _prepare_work_dir(project_id, parse_storage)
    toc_json_path = _prepare_toc_json(project_id, project, outline_state, parse_storage, work_dir)
    gap_plan_path = _prepare_gap_plan(project_id, work_dir)
    wiki_dir = _prepare_wiki_dir(project, parse_storage, work_dir)
    gap_plan_card_count = _augment_wiki_with_gap_plan_cards(gap_plan_path, wiki_dir) if gap_plan_path else 0
    synthesized_card_count = _augment_wiki_with_material_cards(toc_json_path, wiki_dir, project)
    material_library_dir, material_cards = _export_material_library(wiki_dir, work_dir / "素材库")
    template_file = _select_template_file(template_file_records)
    project_params = _build_project_params(project, toc_json_path)

    if progress_callback:
        progress_callback(
            "inputs_ready",
            {
                "tocJsonPath": str(toc_json_path),
                "wikiCardCount": len(material_cards),
                "exportedMaterialCount": len([item for item in material_cards if item.get("available")]),
                "synthesizedMaterialCardCount": synthesized_card_count,
                "gapPlanMaterialCardCount": gap_plan_card_count,
            },
        )

    output_file = work_dir / f"{_safe_filename(str(project.get('name') or project_id), project_id)}_正文.docx"
    manifest_path = work_dir / "s7_assembly_input.json"
    manifest = {
        "projectId": project_id,
        "projectName": str(project.get("name") or project_id),
        "bidType": str(project.get("bidType") or "技术标"),
        "workDir": str(work_dir),
        "tocJsonPath": str(toc_json_path),
        "gapPlanPath": str(gap_plan_path) if gap_plan_path else "",
        "wikiDir": str(wiki_dir),
        "materialLibraryDir": str(material_library_dir),
        "templateFile": str(template_file) if template_file else "",
        "projectParamsPath": str(work_dir / "project_params.json"),
        "projectParams": project_params,
        "outputFile": str(output_file),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    if progress_callback:
        progress_callback(
            "calling_assembler",
            {
                "manifestPath": str(manifest_path),
                "workDir": str(work_dir),
            },
        )

    result = _run_assembler_manifest(manifest_path, progress_callback=progress_callback)
    assembled_path = Path(str(result.get("outputFile") or output_file))
    if not assembled_path.exists():
        raise RuntimeError(f"S7 正文拼装未生成输出文件：{assembled_path}")

    target_path = document_path(project_id)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(assembled_path, target_path)
    file_size_bytes = target_path.stat().st_size

    plan_path = Path(str(result.get("planFile") or work_dir / "assembly_plan.json"))
    report_path = Path(str(result.get("assemblyReport") or work_dir / "assembly_report.md"))
    review_path = Path(str(result.get("needsReview") or work_dir / "needs_review.md"))
    plan = _load_json_list(plan_path)
    coverage = _build_material_coverage(plan, material_cards)
    sections = _sections_from_plan(plan)
    content = _build_fallback_content(report_path, review_path)
    run_duration_sec = max(1, int(round(time.monotonic() - started_at)))
    filled_at = now_iso()
    file_name = assembled_path.name

    if progress_callback:
        progress_callback(
            "assembling_result",
            {
                "sectionCount": len(sections),
                "usedMaterialCount": coverage["fullCover"],
                "unassembledMaterialCount": coverage["noCover"],
            },
        )

    opencode_output = result.get("opencodeOutput") if isinstance(result.get("opencodeOutput"), dict) else {}
    opencode_output.update(
        {
            "skill": ASSEMBLER_SKILL_NAME,
            "workDir": str(work_dir),
            "manifestPath": str(manifest_path),
            "outputFile": str(assembled_path),
            "assemblyReport": str(report_path),
            "needsReview": str(review_path),
            "coverage": {
                "usedMaterialCount": coverage["fullCover"],
                "unassembledMaterialCount": coverage["noCover"],
            },
        }
    )
    if not opencode_output.get("parts"):
        opencode_output["status"] = "received"
        opencode_output["sessionId"] = ""
        opencode_output["providerId"] = "futurecode"
        opencode_output["modelId"] = ASSEMBLER_SKILL_NAME
        opencode_output["receivedAt"] = filled_at
        opencode_output["parts"] = [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "skill": ASSEMBLER_SKILL_NAME,
                        "manifestPath": str(manifest_path),
                        "outputFile": str(assembled_path),
                        "assemblyReport": str(report_path),
                        "needsReview": str(review_path),
                    },
                    ensure_ascii=False,
                ),
            }
        ]

    return store.save_fill_generation_result(
        project_id=project_id,
        summary="技术标正文拼装完成。",
        sections=sections,
        content=content,
        filled_at=filled_at,
        run_duration_sec=run_duration_sec,
        file_size_bytes=file_size_bytes,
        opencode_output=opencode_output,
        file_name=file_name,
        coverage=coverage,
        assembly={
            "skill": "bid-tech-assembler",
            "workDir": str(work_dir),
            "manifestPath": str(manifest_path),
            "tocJsonPath": str(toc_json_path),
            "gapPlanPath": str(gap_plan_path) if gap_plan_path else "",
            "wikiDir": str(wiki_dir),
            "materialLibraryDir": str(material_library_dir),
            "outputFile": str(assembled_path),
            "documentPath": str(target_path),
            "assemblyReport": str(report_path),
            "needsReview": str(review_path),
            "planFile": str(plan_path),
        },
    )


def _prepare_work_dir(project_id: str, parse_storage: dict[str, Any]) -> Path:
    work_dir = technical_workspace_stage_dir(project_id, "s7_assembly_workdir")
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def _runtime_path(path_text: str) -> Path:
    path = Path(path_text).expanduser()
    if path.exists():
        return path
    if path_text.startswith("/data/parsed/"):
        mapped = settings.parsed_dir / path_text.removeprefix("/data/parsed/")
        if mapped.exists():
            return mapped
        project_id, _, suffix = path_text.removeprefix("/data/parsed/").partition("/")
        remapped = settings.documents_dir / project_id / "technical-workspace" / suffix
        if remapped.exists():
            return remapped
    if path_text.startswith("/data/documents/"):
        mapped = settings.documents_dir / path_text.removeprefix("/data/documents/")
        if mapped.exists():
            return mapped
    if path_text.startswith("/data/uploads/"):
        mapped = settings.uploads_dir / path_text.removeprefix("/data/uploads/")
        if mapped.exists():
            return mapped
    return path


def _prepare_toc_json(
    project_id: str,
    project: dict[str, Any],
    outline_state: dict[str, Any],
    parse_storage: dict[str, Any],
    work_dir: Path,
) -> Path:
    directory_state = store.get_directory_state(project_id)
    opencode_output = directory_state.get("opencodeOutput") or {}
    candidates = [
        str(opencode_output.get("tocJsonPath") or ""),
        str(opencode_output.get("outputFile") or ""),
    ]
    for root in legacy_workspace_roots(project_id, parse_storage):
        s2_work_dir = root / "s2_toc_workdir"
        candidates.extend(str(path) for path in sorted(s2_work_dir.glob("*.json")) if "evidence" not in path.name.lower())

    for candidate in candidates:
        if not candidate:
            continue
        path = _runtime_path(candidate)
        if path.exists() and path.suffix.lower() == ".json":
            target = work_dir / settings.s2_toc_output_file_name
            shutil.copy2(path, target)
            return target

    nodes = list(outline_state.get("nodes") or [])
    if not nodes:
        raise ValueError("S2 目录 JSON 不存在，且 S3 当前目录为空，暂时无法拼装正文。")

    output = {
        "schema_version": "bid-toc-json-v1",
        "document_title": f"{project.get('name') or project_id}投标文件总目录",
        "project": {
            "owner": project.get("customerName") or "",
            "name": project.get("name") or project_id,
            "code": project.get("projectCode") or project_id,
        },
        "items": _outline_nodes_to_toc_items(nodes),
    }
    target = work_dir / settings.s2_toc_output_file_name
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _prepare_gap_plan(project_id: str, work_dir: Path) -> Path | None:
    review_state = store.get_review_items(project_id)
    gap_state = store._require(project_id).get("gap_state") or {}
    plan = gap_state.get("plan") if isinstance(gap_state.get("plan"), dict) else {}
    if not plan:
        return None
    if not bool(review_state.get("confirmed")):
        raise ValueError("请先完成缺口处理确认后再生成标书。")
    integrity = gap_state.get("integrity") if isinstance(gap_state.get("integrity"), dict) else {}
    if integrity and str(integrity.get("status") or "") != "passed":
        raise ValueError("缺口完整性校验未通过，暂不可生成标书。")
    target = work_dir / "gap_plan.json"
    target.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _outline_nodes_to_toc_items(nodes: list[dict[str, Any]], prefix: str = "", level: int = 1) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, node in enumerate(nodes, start=1):
        number = f"{prefix}.{index}" if prefix else str(index)
        items.append(
            {
                "order": len(items),
                "level": level,
                "number": number,
                "title": str(node.get("title") or "").strip(),
                "annotation": str(node.get("annotation") or "保留"),
                "source": "outline_state",
                "reason": "",
            }
        )
        children = node.get("children") or []
        if isinstance(children, list):
            items.extend(_outline_nodes_to_toc_items(children, number, level + 1))
    return items


def _prepare_wiki_dir(project: dict[str, Any], parse_storage: dict[str, Any], work_dir: Path) -> Path:
    target = work_dir / "wiki"
    project_id = str(project.get("id") or "")
    candidates = [_runtime_path(str(root / "s2_toc_workdir" / "wiki")) for root in legacy_workspace_roots(project_id, parse_storage)]
    for candidate in candidates:
        if (candidate / "卡片").exists():
            shutil.copytree(candidate, target, dirs_exist_ok=True)
            return target

    target.mkdir(parents=True, exist_ok=True)
    export_wiki(
        api_base=settings.bid_internal_api_base_url or "http://fastapi:8000",
        bid_type=str(project.get("bidType") or "投标文件"),
        out_dir=target,
    )
    if not (target / "卡片").exists():
        raise RuntimeError("当前项目没有可用 Wiki 卡片，无法按素材库拼装正文。")
    return target


def _select_template_file(template_file_records: list[dict[str, Any]]) -> Path | None:
    for record in template_file_records:
        path = _runtime_path(str(record.get("path") or ""))
        if path.exists() and path.suffix.lower() == ".docx" and "附表" not in str(record.get("name") or path.name):
            return path
    for record in template_file_records:
        path = _runtime_path(str(record.get("path") or ""))
        if path.exists() and path.suffix.lower() == ".docx":
            return path
    return None


def _build_project_params(project: dict[str, Any], toc_json_path: Path) -> dict[str, Any]:
    data = json.loads(toc_json_path.read_text(encoding="utf-8"))
    toc_project = data.get("project") if isinstance(data, dict) else {}
    if not isinstance(toc_project, dict):
        toc_project = {}
    return {
        "project_name": str(toc_project.get("name") or project.get("name") or project.get("id") or ""),
        "project_short": str(project.get("name") or project.get("id") or "项目")[:24],
        "client_name": str(toc_project.get("owner") or project.get("customerName") or ""),
        "tender_no": str(toc_project.get("code") or project.get("projectCode") or ""),
    }


def _augment_wiki_with_material_cards(toc_json_path: Path, wiki_dir: Path, project: dict[str, Any]) -> int:
    """S7 needs one filesystem card per source material.

    The platform Wiki API currently exports useful root pages plus aggregate
    card pages. The legacy assembler, however, matches `卡片/*.md` by
    frontmatter. This adapter writes project-scoped, per-material cards without
    changing the database Wiki itself.
    """

    cards_dir = wiki_dir / "卡片"
    cards_dir.mkdir(parents=True, exist_ok=True)
    toc_entries = _load_toc_match_entries(toc_json_path)
    if not toc_entries:
        return 0

    raw_payload = _run_async(
        material_store.raw_files(
            bid_type=str(project.get("bidType") or "技术标"),
            page=1,
            page_size=1000,
        )
    )
    raw_items = [item for item in raw_payload.get("items") or [] if isinstance(item, dict)]
    identity = _project_identity_from_toc(toc_json_path, project)

    written = 0
    for item in raw_items:
        if not _material_is_assemblable(item):
            continue
        if not _material_matches_project(item, identity):
            continue
        section, score = _best_toc_section_for_material(item, toc_entries)
        if not section or score < 8:
            continue
        card_path = cards_dir / f"RAW-{str(item.get('id') or '').replace('/', '-')}-{_safe_filename(str(item.get('name') or 'material'), 'material')}.md"
        card_path.write_text(_render_runtime_material_card(item, section), encoding="utf-8")
        written += 1
    return written


def _augment_wiki_with_gap_plan_cards(gap_plan_path: Path | None, wiki_dir: Path) -> int:
    if not gap_plan_path or not gap_plan_path.exists():
        return 0
    plan = json.loads(gap_plan_path.read_text(encoding="utf-8"))
    items = plan.get("items") if isinstance(plan, dict) else []
    if not isinstance(items, list):
        return 0
    cards_dir = wiki_dir / "卡片"
    cards_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        section = str(item.get("number") or item.get("tocItemId") or "").strip()
        title = str(item.get("title") or "缺口补料").strip()
        sources: list[dict[str, Any]] = []
        sources.extend(source for source in item.get("matchedMaterials") or [] if isinstance(source, dict))
        sources.extend(source for source in item.get("resolvedArtifacts") or [] if isinstance(source, dict))
        for index, source in enumerate(sources, start=1):
            material_id = str(source.get("id") or "")
            path = str(source.get("path") or source.get("docx") or "").strip()
            if not material_id and not path:
                continue
            card_name = _safe_filename(str(source.get("title") or source.get("fileName") or title), f"{title}-{index}")
            card_path = cards_dir / f"gap-plan-{_safe_filename(section, 'section')}-{index}-{card_name}.md"
            card_path.write_text(
                _render_gap_plan_material_card(
                    item=item,
                    source=source,
                    section=section,
                    title=card_name,
                ),
                encoding="utf-8",
            )
            written += 1
    return written


def _render_gap_plan_material_card(
    *,
    item: dict[str, Any],
    source: dict[str, Any],
    section: str,
    title: str,
) -> str:
    source_type = str(source.get("source") or "gap_plan")
    scope = "定制" if source_type in {"ai_fill", "manual"} else "通用"
    path = str(source.get("path") or source.get("docx") or "").strip()
    material_id = str(source.get("id") or "")
    file_name = str(source.get("fileName") or Path(path).name or f"{title}.docx")
    lines = [
        "---",
        f"name: {json.dumps(title, ensure_ascii=False)}",
        f"path: {json.dumps(path or file_name, ensure_ascii=False)}",
        f"scope: {json.dumps(scope, ensure_ascii=False)}",
        'category: "缺口处理"',
        f"material_id: {json.dumps(material_id if material_id.startswith('RAW-') else '', ensure_ascii=False)}",
        f"cleaned_file_name: {json.dumps(file_name, ensure_ascii=False)}",
        f"skeleton_section: {json.dumps(section, ensure_ascii=False)}",
        'skeleton_level: "section"',
        'material_level_range: "none"',
        "heading_count: 0",
        "shift: 0",
        'attach_mode: "normal"',
        "deprecated: false",
        "---",
        "",
        f"# {title}",
        "",
        "## Gap Plan 信息",
        f"- toc_title: {item.get('title') or ''}",
        f"- source: {source_type}",
        f"- path: {path}",
        f"- material_id: {material_id}",
        f"- skeleton_section: {section}",
    ]
    return "\n".join(lines).strip() + "\n"


def _load_toc_match_entries(toc_json_path: Path) -> list[dict[str, str]]:
    data = json.loads(toc_json_path.read_text(encoding="utf-8"))
    items = data.get("items") if isinstance(data, dict) else []
    entries: list[dict[str, str]] = []
    if not isinstance(items, list):
        return entries
    for item in items:
        if not isinstance(item, dict):
            continue
        number = str(item.get("number") or "").strip()
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        flat = _toc_number_to_flat(number)
        if not flat and not number.startswith("第"):
            continue
        entries.append(
            {
                "section": flat,
                "number": number,
                "title": title,
                "text": f"{number} {title}".strip(),
            }
        )
    return entries


def _toc_number_to_flat(number: str) -> str:
    text = str(number or "").strip()
    if re.fullmatch(r"\d+(?:\.\d+){0,6}", text):
        return text
    chapter_match = re.fullmatch(r"第([一二三四五六七八九十百千万0-9]+)章", text)
    if chapter_match:
        return str(_chinese_number_to_int(chapter_match.group(1)))
    return ""


def _chinese_number_to_int(value: str) -> int:
    text = str(value or "").strip()
    if text.isdigit():
        return int(text)
    digits = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if text == "十":
        return 10
    if "十" in text:
        left, _, right = text.partition("十")
        tens = digits.get(left, 1) if left else 1
        ones = digits.get(right, 0) if right else 0
        return tens * 10 + ones
    return digits.get(text, 0)


def _project_identity_from_toc(toc_json_path: Path, project: dict[str, Any]) -> dict[str, Any]:
    data = json.loads(toc_json_path.read_text(encoding="utf-8"))
    toc_project = data.get("project") if isinstance(data, dict) else {}
    identity = toc_project.get("identity") if isinstance(toc_project, dict) else {}
    if not isinstance(identity, dict):
        identity = {}
    aliases = identity.get("customerAliases") if isinstance(identity.get("customerAliases"), list) else []
    return {
        "customerId": str(identity.get("customerId") or ""),
        "customerName": str(
            identity.get("customerCanonicalName")
            or identity.get("customerName")
            or project.get("customerName")
            or ""
        ),
        "customerAliases": {str(item) for item in aliases if str(item).strip()},
        "projectId": str(identity.get("projectId") or project.get("projectId") or ""),
        "projectCode": str(identity.get("projectCode") or project.get("projectCode") or ""),
        "workspaceProjectId": str(identity.get("workspaceProjectId") or project.get("id") or ""),
    }


def _material_is_assemblable(item: dict[str, Any]) -> bool:
    name = str(item.get("name") or "")
    cleaned_name = str(item.get("cleanedFileName") or "")
    ext = Path(name).suffix.lower()
    if bool(item.get("hasCleanedWord")) or cleaned_name.lower().endswith(".docx"):
        return True
    return ext == ".docx"


def _material_matches_project(item: dict[str, Any], identity: dict[str, Any]) -> bool:
    scope = str(item.get("identityScope") or "").strip().lower()
    tier = str(item.get("materialTier") or "").strip().lower()
    if scope in {"", "general"} and tier in {"", "standard", "general"}:
        return True
    if scope == "customer" or tier == "customer":
        material_customer_id = str(item.get("customerId") or "")
        if material_customer_id and material_customer_id == str(identity.get("customerId") or ""):
            return True
        names = {
            str(item.get("customerName") or ""),
            str(item.get("customerCanonicalName") or ""),
            *[str(alias) for alias in item.get("customerAliases") or []],
        }
        project_names = {
            str(identity.get("customerName") or ""),
            *[str(alias) for alias in identity.get("customerAliases") or []],
        }
        return bool({name for name in names if name} & {name for name in project_names if name})
    if scope == "project" or tier == "project":
        project_keys = {
            str(identity.get("projectId") or ""),
            str(identity.get("projectCode") or ""),
            str(identity.get("workspaceProjectId") or ""),
        }
        material_keys = {
            str(item.get("projectId") or ""),
            str(item.get("projectCode") or ""),
        }
        return bool({key for key in project_keys if key} & {key for key in material_keys if key})
    return True


def _best_toc_section_for_material(item: dict[str, Any], toc_entries: list[dict[str, str]]) -> tuple[str, int]:
    material_name_text = " ".join(
        [
            str(item.get("name") or ""),
            str(item.get("cleanedFileName") or ""),
        ]
    )
    material_text = " ".join([material_name_text, str(item.get("folderPath") or "")])
    best_section = ""
    best_score = 0
    best_rank: tuple[int, int, int] = (0, 0, 0)
    for entry in toc_entries:
        title = str(entry.get("title") or "")
        score = _title_match_score(material_text, title)
        direct_score = _title_match_score(material_name_text, title)
        depth = len(str(entry.get("section") or "").split("."))
        rank = (score, direct_score, depth)
        if rank > best_rank:
            best_rank = rank
            best_score = score
            best_section = str(entry.get("section") or "")
    return best_section, best_score


def _title_match_score(material_text: str, toc_title: str) -> int:
    material = _normalize_match_text(material_text)
    title = _normalize_match_text(toc_title)
    if not material or not title:
        return 0
    score = 0
    if title in material or material in title:
        score += 100
    for n in (6, 5, 4, 3, 2):
        seen: set[str] = set()
        for index in range(max(0, len(title) - n + 1)):
            token = title[index : index + n]
            if token in seen or token not in material:
                continue
            seen.add(token)
            score += n
    return score


def _normalize_match_text(value: str) -> str:
    text = re.sub(r"\.(docx|doc|pdf|xlsx|xlsm|xls)$", "", str(value or ""), flags=re.IGNORECASE)
    text = re.sub(r"技术标|商务标|专题|方案|报告|情况|一览表|相关|项目|投标|文件", "", text)
    return re.sub(r"[\s:：，,。.！!？?\\\-_/'\"“”‘’·（）()【】\[\]/]+", "", text)


def _render_runtime_material_card(item: dict[str, Any], section: str) -> str:
    name = str(item.get("name") or item.get("cleanedFileName") or "未命名素材")
    card_name = Path(str(item.get("cleanedFileName") or name)).stem
    scope = "通用" if str(item.get("materialTier") or "") == "standard" else "定制"
    category = str(item.get("group") or Path(str(item.get("folderPath") or "素材")).name or "素材")
    cleaned_name = str(item.get("cleanedFileName") or "")
    lines = [
        "---",
        f"name: {json.dumps(card_name, ensure_ascii=False)}",
        f"path: {json.dumps(str(item.get('folderPath') or '') + '/' + name, ensure_ascii=False)}",
        f"scope: {json.dumps(scope, ensure_ascii=False)}",
        f"category: {json.dumps(category, ensure_ascii=False)}",
        f"material_id: {json.dumps(str(item.get('id') or ''), ensure_ascii=False)}",
        f"identity_scope: {json.dumps(str(item.get('identityScope') or 'general'), ensure_ascii=False)}",
        f"material_scope: {json.dumps(str(item.get('materialScope') or item.get('identityScope') or 'general'), ensure_ascii=False)}",
        f"bid_type: {json.dumps(str(item.get('bidType') or '技术标'), ensure_ascii=False)}",
        f"customer_id: {json.dumps(str(item.get('customerId') or ''), ensure_ascii=False)}",
        f"customer_name: {json.dumps(str(item.get('customerCanonicalName') or item.get('customerName') or ''), ensure_ascii=False)}",
        f"customer_aliases: {json.dumps('、'.join(str(alias) for alias in item.get('customerAliases') or []), ensure_ascii=False)}",
        f"project_id: {json.dumps(str(item.get('projectId') or ''), ensure_ascii=False)}",
        f"project_code: {json.dumps(str(item.get('projectCode') or ''), ensure_ascii=False)}",
        f"cleaned_file_name: {json.dumps(cleaned_name, ensure_ascii=False)}",
        f"skeleton_section: {json.dumps(section, ensure_ascii=False)}",
        'skeleton_level: "section"',
        'material_level_range: "none"',
        "heading_count: 0",
        "shift: 0",
        'attach_mode: "normal"',
        "deprecated: false",
        "---",
        "",
        f"# {Path(cleaned_name or name).stem}",
        "",
        "## Merge 信息",
        f"- path: {str(item.get('folderPath') or '').strip('/')}/{name}",
        f"- material_id: {str(item.get('id') or '')}",
        f"- skeleton_section: {section}",
        f"- cleaned_file_name: {cleaned_name}",
    ]
    return "\n".join(lines).strip() + "\n"


def _export_material_library(wiki_dir: Path, library_dir: Path) -> tuple[Path, list[dict[str, Any]]]:
    if library_dir.exists():
        shutil.rmtree(library_dir)
    library_dir.mkdir(parents=True, exist_ok=True)

    cards: list[dict[str, Any]] = []
    for card_path in sorted((wiki_dir / "卡片").rglob("*.md")):
        text = card_path.read_text(encoding="utf-8")
        fields = _parse_card_fields(text)
        if not fields:
            continue
        material_id = str(fields.get("material_id") or "").strip()
        title = _card_title(text, card_path)
        scope = str(fields.get("scope") or "通用").strip() or "通用"
        category = str(fields.get("category") or "素材").strip() or "素材"
        original_path = str(fields.get("path") or "").strip()
        file_name = _material_file_name(fields, original_path, title)
        relative_path = _material_relative_path(scope, category, file_name)
        target_path = library_dir / relative_path
        card = {
            "id": material_id or original_path or str(card_path),
            "title": title,
            "path": relative_path,
            "originalPath": original_path,
            "scope": scope,
            "category": category,
            "cardFile": str(card_path),
            "available": False,
        }

        try:
            _copy_material_to_library(material_id, original_path, target_path)
            card["available"] = target_path.exists()
        except Exception as exc:
            card["error"] = str(exc)

        updated_fields = {"path": relative_path}
        if not card["available"]:
            updated_fields["deprecated"] = "true"
            updated_fields["condition"] = f"素材文件未导出：{card.get('error') or 'unknown'}"
        card_path.write_text(_replace_frontmatter_fields(text, updated_fields), encoding="utf-8")
        cards.append(card)
    return library_dir, cards


def _copy_material_to_library(material_id: str, original_path: str, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    path = _runtime_path(original_path)
    if path.exists() and path.suffix.lower() == ".docx":
        shutil.copy2(path, target_path)
        return

    if material_id:
        try:
            payload = _run_async(material_store.raw_download_cleaned_content(material_id))
        except Exception:
            payload = _run_async(material_store.raw_download_content(material_id))
        mime_type = str(payload.get("mimeType") or "")
        file_name = str(payload.get("fileName") or "")
        if "wordprocessingml" not in mime_type and not file_name.lower().endswith(".docx"):
            raise RuntimeError(f"素材 {material_id} 不是可拼装 docx。")
        minio_client.download_file(str(payload["bucket"]), str(payload["key"]), target_path)
        return
    raise RuntimeError("卡片缺少 material_id，且 path 不是可读 docx。")


def _run_async(awaitable):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    raise RuntimeError("素材导出不能在已运行的 asyncio event loop 中同步执行。")


def _parse_card_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end >= 0:
            for raw_line in text[3:end].strip().splitlines():
                if ":" not in raw_line:
                    continue
                key, _, value = raw_line.partition(":")
                fields[key.strip()] = _clean_field_value(value)
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("- ") or ":" not in line:
            continue
        key, _, value = line[2:].partition(":")
        key = key.strip()
        if key in {
            "path",
            "material_id",
            "scope",
            "category",
            "skeleton_section",
            "cleaned_file_name",
            "cleanedFileName",
            "deprecated",
            "condition",
        }:
            fields.setdefault(key, _clean_field_value(value))
    return fields


def _replace_frontmatter_fields(text: str, updates: dict[str, str]) -> str:
    if not text.startswith("---"):
        lines = ["---", *[f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in updates.items()], "---", "", text]
        return "\n".join(lines)
    end = text.find("\n---", 3)
    if end < 0:
        return text
    body = text[end + len("\n---") :]
    lines = text[3:end].strip().splitlines()
    seen: set[str] = set()
    out_lines: list[str] = ["---"]
    for raw_line in lines:
        if ":" not in raw_line:
            out_lines.append(raw_line)
            continue
        key, _, _ = raw_line.partition(":")
        clean_key = key.strip()
        if clean_key in updates:
            out_lines.append(f"{clean_key}: {json.dumps(str(updates[clean_key]), ensure_ascii=False)}")
            seen.add(clean_key)
        else:
            out_lines.append(raw_line)
    for key, value in updates.items():
        if key not in seen:
            out_lines.append(f"{key}: {json.dumps(str(value), ensure_ascii=False)}")
    out_lines.append("---")
    return "\n".join(out_lines) + body


def _clean_field_value(value: str) -> str:
    return str(value or "").strip().strip('"').strip("'")


def _card_title(text: str, card_path: Path) -> str:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("# "):
            return line[2:].strip() or card_path.stem
    return card_path.stem


def _material_file_name(fields: dict[str, str], original_path: str, title: str) -> str:
    name = str(fields.get("cleaned_file_name") or fields.get("cleanedFileName") or "").strip()
    if not name:
        name = Path(original_path).name if original_path else f"{title}.docx"
    if not name.lower().endswith(".docx"):
        name = f"{Path(name).stem}.docx"
    return _safe_filename(name, "material.docx")


def _material_relative_path(scope: str, category: str, file_name: str) -> str:
    root = "投标资料库-通用" if scope == "通用" else "投标资料库-定制"
    return str(Path(root) / _safe_filename(category, "素材") / _safe_filename(file_name, "material.docx"))


def _run_assembler_manifest(
    manifest_path: Path,
    progress_callback: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    prompt = _build_assembler_prompt(manifest_path)
    result = OpencodeClient().run_bid_tech_assembler_with_trace(
        prompt,
        session_ready_callback=(
            (lambda details: progress_callback("assembler_session_ready", details))
            if progress_callback
            else None
        ),
        stream_callback=(
            (lambda details: progress_callback("assembler_delta", details))
            if progress_callback
            else None
        ),
    )
    return result


def _build_assembler_prompt(manifest_path: Path) -> str:
    return f"""
Use the {ASSEMBLER_SKILL_NAME} skill.

你现在在做 S7 技术标正文拼装。后端已经准备好 manifest、S2 目录 JSON、Wiki 文件系统副本、素材库导出目录和输出路径。

manifest：{manifest_path}

请直接调用一次 Bash 工具执行下面命令，Bash 工具 timeout 必须设置为 1800000 毫秒或更高。不要先检查工作目录，不要先执行 pwd/ls/cat/read/glob，不要拆成多条命令，不要改写命令或路径。命令会把完整正文 docx、assembly_report.md、needs_review.md 和 assembly_plan.json 写入 manifest 指定路径，并只在 stdout 打印小型摘要 JSON：

{ASSEMBLER_SKILL_COMMAND} {manifest_path}

只返回命令 stdout 中的小型 JSON，不要返回解释文字，不要使用 Markdown 代码块。
返回格式必须是：
{{
  "schema_version": "bid-tech-assembly-v1",
  "outputFile": "/data/documents/PRJ-0001/technical-workspace/s7_assembly_workdir/投标文件-正文.docx",
  "assemblyReport": "/data/documents/PRJ-0001/technical-workspace/s7_assembly_workdir/assembly_report.md",
  "needsReview": "/data/documents/PRJ-0001/technical-workspace/s7_assembly_workdir/needs_review.md",
  "planFile": "/data/documents/PRJ-0001/technical-workspace/s7_assembly_workdir/assembly_plan.json",
  "summary": {{"total": 0, "byStatus": {{}}, "usedPathCount": 0}}
}}
""".strip()


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def _sections_from_plan(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for item in plan:
        if int(item.get("level") or 0) != 1 or str(item.get("status") or "") == "OUT_OF_SCOPE":
            continue
        status = str(item.get("status") or "")
        if status in {"MATCHED", "ADAPTED", "COVER", "STRUCTURAL"}:
            generation_mode = "generated"
            risk_flags: list[str] = []
        elif status == "NEEDS_REVIEW":
            generation_mode = "generated_with_placeholder"
            risk_flags = ["FACT_REQUIRED"]
        else:
            generation_mode = "placeholder"
            risk_flags = ["MATERIAL_UNMATCHED"]
        title = str(item.get("title") or "未命名章节")
        sections.append(
            {
                "nodeId": f"TOC-{item.get('toc_idx')}",
                "title": title,
                "generationMode": generation_mode,
                "content": f"已按目录拼装：{title}",
                "riskFlags": risk_flags,
            }
        )
    return sections


def _build_material_coverage(plan: list[dict[str, Any]], cards: list[dict[str, Any]]) -> dict[str, Any]:
    used_paths: set[str] = set()
    partial_items: list[dict[str, Any]] = []
    for item in plan:
        status = str(item.get("status") or "")
        if status in {"MATCHED", "ADAPTED", "COVER"}:
            used_paths.update(str(path) for path in item.get("paths") or [] if str(path).strip())
        elif status in {"UNMATCHED", "NEEDS_REVIEW"}:
            partial_items.append(
                {
                    "id": f"TOC-{item.get('toc_idx')}",
                    "title": str(item.get("title") or "未命名目录项"),
                    "nodeTitle": f"目录项未匹配素材：{item.get('chapter_no') or ''}".strip(),
                }
            )

    material_cards = [card for card in cards if card.get("available")]
    no_cover_items = [
        {
            "id": str(card.get("id") or card.get("path") or ""),
            "title": str(card.get("title") or card.get("path") or "未命名素材"),
            "nodeTitle": f"素材未出现在 S2 目录 JSON 或拼装计划中：{card.get('scope') or ''}/{card.get('category') or ''}",
        }
        for card in material_cards
        if str(card.get("path") or "") not in used_paths
    ]

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for card in material_cards:
        scope = str(card.get("scope") or "通用")
        category = str(card.get("category") or "素材")
        grouped[f"{scope}/{category}"].append(card)

    tree: list[dict[str, Any]] = []
    for group_name, group_cards in sorted(grouped.items()):
        children = []
        for card in sorted(group_cards, key=lambda item: str(item.get("title") or "")):
            used = str(card.get("path") or "") in used_paths
            children.append(
                {
                    "id": str(card.get("id") or card.get("path") or ""),
                    "title": str(card.get("title") or card.get("path") or "未命名素材"),
                    "coverage": 100 if used else 0,
                    "status": "full" if used else "none",
                    "children": [],
                }
            )
        used_count = sum(1 for child in children if child["status"] == "full")
        coverage = 100 if not children else round(used_count / len(children) * 100)
        tree.append(
            {
                "id": group_name,
                "title": group_name,
                "coverage": coverage,
                "status": "full" if coverage == 100 else "partial" if coverage else "none",
                "children": children,
            }
        )

    full_cover = len(used_paths)
    no_cover = len(no_cover_items)
    partial_cover = len(partial_items)
    total_materials = len(material_cards)
    percentage = 100 if total_materials == 0 else round((total_materials - no_cover) / total_materials * 100)
    return {
        "percentage": percentage,
        "fullCover": full_cover,
        "partialCover": partial_cover,
        "noCover": no_cover,
        "tree": tree,
        "partialItems": partial_items,
        "noCoverItems": no_cover_items,
        "basis": "assembly_materials_vs_s2_toc_json",
    }


def _build_fallback_content(report_path: Path, review_path: Path) -> str:
    lines = ["# 技术标正文拼装报告", ""]
    for label, path in (("assembly_report", report_path), ("needs_review", review_path)):
        lines.append(f"## {label}")
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="replace").strip()
            lines.append(text[:6000] if text else "无内容。")
        else:
            lines.append("未生成。")
        lines.append("")
    return "\n".join(lines).strip()


def _safe_filename(value: str, fallback: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "-", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or fallback
