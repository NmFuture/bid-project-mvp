from __future__ import annotations

from pathlib import Path


def write_review(output_dir: Path, source_docx: Path, regions: list[dict], boundaries: dict) -> None:
    lines = [
        "# 商务模板提取初步验收报告",
        "",
        f"- 源文件：`{source_docx.name}`",
        f"- 格式章节数量：{len(regions)}",
        f"- 模板切片数量：{len(boundaries.get('templates') or [])}",
        "",
        "## 格式章节",
        "",
    ]
    for region in regions:
        lines.append(
            f"- `{region['id']}` {region['title']}：B{region['startBlockId']} - B{region['endBlockId']}"
        )
    lines.extend(["", "## 模板切片", ""])
    for template in boundaries.get("templates") or []:
        lines.extend(
            [
                f"### {template['id']} {template['title']}",
                "",
                f"- 类型：`{template.get('templateType') or ''}`",
                f"- 边界：B{template['startBlockId']} - B{template['endBlockId']}",
                f"- 输出：`{template.get('outputPath') or ''}`",
                f"- 置信度：{template.get('confidence')}",
                f"- 信号：{', '.join(template.get('signals') or [])}",
                f"- 理由：{template.get('reason') or ''}",
                "",
                "预览：",
                "",
                "```text",
                str(template.get("preview") or "").strip(),
                "```",
                "",
            ]
        )
    rejected = boundaries.get("rejectedTemplates") or []
    section_containers = [item for item in rejected if item.get("headingRole") == "section_container" or item.get("rejectCode") == "section_container"]
    boundary_only = [item for item in rejected if item.get("headingRole") == "boundary_only" or item.get("rejectCode") == "boundary_only"]
    hard_rejected = [item for item in rejected if item not in section_containers and item not in boundary_only]
    if boundaries.get("templates"):
        lines.extend(["", "## 被输出模板", ""])
        for template in boundaries.get("templates") or []:
            lines.append(f"- {template.get('title') or template.get('templateTitle') or template.get('candidateId')}：B{template.get('startBlockId')} - B{template.get('endBlockId')}")
    if section_containers:
        lines.extend(["", "## 父级章节标题", ""])
        for item in section_containers:
            lines.append(f"- {item.get('templateTitle') or item.get('candidateId')}：B{item.get('candidateBlockId') or ''}，{item.get('rejectReason') or ''}")
    if boundary_only:
        lines.extend(["", "## 只作为边界的标题", ""])
        for item in boundary_only:
            lines.append(f"- {item.get('templateTitle') or item.get('candidateId')}：B{item.get('candidateBlockId') or ''}，{item.get('rejectReason') or ''}")
    if hard_rejected:
        lines.extend(["", "## 被拒绝标题", ""])
        for item in hard_rejected:
            lines.append(f"- {item.get('templateTitle') or item.get('candidateId')}：B{item.get('candidateBlockId') or ''}，`{item.get('rejectCode') or ''}`，{item.get('rejectReason') or ''}")
    if rejected:
        lines.extend(["", "## 需复核或已拒绝候选", ""])
    for item in rejected:
        lines.extend(
            [
                f"### {item.get('templateTitle') or item.get('candidateId') or '未命名候选'}",
                "",
                f"- 候选：`{item.get('candidateId') or ''}` / B{item.get('candidateBlockId') or ''}",
                f"- 边界：B{item.get('startBlockId') or ''} - B{item.get('endBlockId') or ''}",
                f"- 置信度：{item.get('confidence')}",
                f"- 拒绝代码：`{item.get('rejectCode') or ''}`",
                f"- 原因：{item.get('rejectReason') or ''}",
                "",
            ]
        )
    (output_dir / "review.md").write_text("\n".join(lines), encoding="utf-8")
