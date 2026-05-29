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
    (output_dir / "review.md").write_text("\n".join(lines), encoding="utf-8")
