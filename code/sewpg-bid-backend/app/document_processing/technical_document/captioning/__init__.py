"""技术标图表题注编号入口。"""

from .captions import CaptionNumberer, number_captions, verify_numbered_docx
from .runner import run_manifest

__all__ = ["CaptionNumberer", "number_captions", "run_manifest", "verify_numbered_docx"]
