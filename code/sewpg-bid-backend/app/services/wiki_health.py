from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WikiHealth:
    wiki_dir: str
    card_count: int
    markdown_count: int
    total_bytes: int
    estimated_tokens: int
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "wikiDir": self.wiki_dir,
            "cardCount": self.card_count,
            "markdownCount": self.markdown_count,
            "totalBytes": self.total_bytes,
            "estimatedTokens": self.estimated_tokens,
            "warnings": list(self.warnings),
        }


def inspect_wiki_dir(wiki_dir: Path, *, token_limit: int = 120_000) -> WikiHealth:
    # 线上 Wiki 是 DB 形态（WikiNode/WikiDoc），从不落磁盘 .md。
    # 若目标目录不存在，说明就是 DB 形态，跳过文件系统检查而不是恒定告警。
    if not wiki_dir.exists():
        return WikiHealth(
            wiki_dir=str(wiki_dir),
            card_count=0,
            markdown_count=0,
            total_bytes=0,
            estimated_tokens=0,
            warnings=["db_backed_wiki_filesystem_check_skipped"],
        )
    markdown_files = list(wiki_dir.rglob("*.md"))
    card_dir = wiki_dir / "卡片"
    card_count = len(list(card_dir.glob("*.md"))) if card_dir.exists() else 0
    total_bytes = 0
    for path in markdown_files:
        try:
            total_bytes += path.stat().st_size
        except OSError:
            continue
    estimated_tokens = max(0, total_bytes // 2)
    warnings: list[str] = []
    if card_count == 0:
        warnings.append("no_wiki_cards")
    if estimated_tokens > token_limit:
        warnings.append("estimated_tokens_exceed_limit")
    return WikiHealth(
        wiki_dir=str(wiki_dir),
        card_count=card_count,
        markdown_count=len(markdown_files),
        total_bytes=total_bytes,
        estimated_tokens=estimated_tokens,
        warnings=warnings,
    )
