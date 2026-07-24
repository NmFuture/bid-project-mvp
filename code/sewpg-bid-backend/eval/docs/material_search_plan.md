# Material Search Fallback Plan

This is a historical implementation note for the former H13-H15 plan. It is
intentionally not enabled in production yet.

## Decision

Keep Wiki as the primary material routing source. Add a Postgres `tsvector`
BM25-style keyword fallback before considering vector RAG.

## Candidate Table Shape

Use existing material metadata and cleaned text. The eventual searchable view
should expose:

| column | purpose |
|---|---|
| `material_id` | raw file id |
| `bid_type` | technical/business boundary |
| `material_tier` | standard/customer/project |
| `folder_path` | identity and category boundary |
| `file_name` | display and tie breaker |
| `chunk_id` | stable paragraph/chunk id |
| `chunk_text` | searchable text |
| `search_vector` | generated `tsvector` |

## Query Contract

Future service:

```python
search_material_chunks(
    query: str,
    bid_type: str,
    readable_paths: list[str],
    turbine_model: str = "",
    limit: int = 10,
) -> list[MaterialSearchHit]
```

Each hit should include original text, score, material id, folder path, and
chunk id. The S3 planner can use it only when Wiki card confidence is missing
or low.

## Health Signals

`app/services/wiki_health.py` now exposes lightweight Wiki directory health:

- card count
- markdown count
- total bytes
- estimated token count
- warnings for missing cards or token limit overflow
