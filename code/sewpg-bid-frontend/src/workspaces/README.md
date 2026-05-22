# Workspace frontend split

The frontend is split by bid workspace at the route and page-entry level.

- `technical/`: technical bid routes and page entry files.
- `business/`: business bid routes and page entry files.
- `shared/`: routing helpers that must stay bid-type neutral.

Rules for future changes:

1. Put technical-bid UI changes under `technical/` unless the code is genuinely reusable.
2. Put business-bid UI changes under `business/` unless the code is genuinely reusable.
3. Keep `src/pages` as a compatibility/shared implementation layer while extracting pages gradually.
4. Do not add new `if 商务标 / if 技术标` branches to shared pages when a workspace-specific entry can own the difference.
