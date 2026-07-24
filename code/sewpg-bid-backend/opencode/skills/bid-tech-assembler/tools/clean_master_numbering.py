#!/usr/bin/env python3
"""
母版去 numbering 绑定：剥掉 Heading 1-6 style 的 w:numPr，
这样段落用 Heading 样式时不再被多级列表自动编号（方案 B 核心）。

可幂等多次运行。

用法：
    python3 tools/clean_master_numbering.py [--template 母版.docx]
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import zipfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATE = SKILL_DIR / "templates" / "技术投标母版模板.docx"

# Heading 样式的 styleId（在我们的母版里）
HEADING_STYLE_IDS = ["10", "2", "3", "4", "5", "6", "7", "8", "9"]


def strip_numPr_from_heading_styles(docx_path: Path) -> int:
    """剥掉 Heading 1-9 style 块里的 w:numPr。返回剥掉数。"""
    with zipfile.ZipFile(docx_path, "r") as zin:
        names = zin.namelist()
        data = {n: zin.read(n) for n in names}

    styles_xml = data["word/styles.xml"].decode("utf-8", errors="replace")

    stripped = 0
    for sid in HEADING_STYLE_IDS:
        # 定位 style 块
        pat = re.compile(
            rf'(<w:style[^>]*w:styleId="{re.escape(sid)}"[^>]*>)(.*?)(</w:style>)',
            re.DOTALL,
        )

        def _repl(m: "re.Match") -> str:
            nonlocal stripped
            head, body, tail = m.group(1), m.group(2), m.group(3)
            new_body, n = re.subn(r'<w:numPr>.*?</w:numPr>', "", body, flags=re.DOTALL)
            if n:
                stripped += n
            return head + new_body + tail

        styles_xml = pat.sub(_repl, styles_xml, count=1)

    data["word/styles.xml"] = styles_xml.encode("utf-8")

    tmp = docx_path.with_suffix(".tmp.docx")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for name in names:
            zout.writestr(name, data[name])
    shutil.move(str(tmp), str(docx_path))

    return stripped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    args = ap.parse_args()

    if not args.template.exists():
        print(f"[ERR] template not found: {args.template}", file=sys.stderr)
        sys.exit(1)

    n = strip_numPr_from_heading_styles(args.template)
    print(f"[OK] stripped {n} numPr from Heading styles in {args.template}")


if __name__ == "__main__":
    main()
