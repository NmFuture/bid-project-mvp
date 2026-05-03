# Material Library Top-Level Scope Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote 素材库 to a top-level preparation module and make project-scoped material lookup explicit for S3/S4.

**Architecture:** Keep the platform material/Wiki library global, but store each bid project's selected customer and material-project identity. Expose a small backend material-scope payload so frontend search and later Agent manifests consistently use `通用素材 + 当前客户素材 + 当前项目素材`.

**Tech Stack:** React/Vite frontend, FastAPI backend, PostgreSQL/MinIO material store, existing project JSON state.

---

### Task 1: Top-Level Material Navigation

**Files:**
- Modify: `code/sewpg-bid-frontend/src/components/layout/AppShell.jsx`
- Modify: `code/sewpg-bid-frontend/src/App.jsx`

- [x] **Step 1: Move 素材库 to first-level navigation**

Add a top-level `/materials/structured` nav item between `解析` and `技术标`; remove the workspace-level `素材库` item so material maintenance reads as pre-project preparation.

- [x] **Step 2: Keep existing material routes**

Keep `/materials/structured`, `/materials/wiki`, `/workspace/:workspace/materials/structured`, and `/workspace/:workspace/materials/wiki` routes working so old links do not break.

- [x] **Step 3: Run frontend check**

Run: `npm run check` in `code/sewpg-bid-frontend`

Expected: command succeeds; only existing Vite chunk-size warnings are acceptable.

### Task 2: Explicit Project Material Scope

**Files:**
- Modify: `code/sewpg-bid-backend/app/api/routes/projects.py`
- Modify: `code/sewpg-bid-backend/app/services/identity.py`
- Test: `code/sewpg-bid-backend/tests/test_store_persistence.py`

- [x] **Step 1: Add a pure helper for material scope paths**

Create `build_project_material_scope(project)` in `identity.py`. It must return `bidType`, `identity`, and three readable scopes: `standard`, `customer`, `project`.

- [x] **Step 2: Use the helper from `/api/projects/{project_id}/materials-path`**

Return the legacy fields plus `readableScopes`, `paths`, and `summary`, so the frontend can display and search with the same source of truth.

- [x] **Step 3: Add backend test**

Add a test proving a project with selected `materialCustomerId` and `materialProjectId` produces:

```text
通用素材/技术标
客户素材/华能集团/技术标
项目素材/MAT-HN-001/技术标
```

- [x] **Step 4: Run targeted backend test**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_store_persistence.py -q` in `code/sewpg-bid-backend`

Expected: pass.

### Task 3: S3 Material Search Uses Project Scope

**Files:**
- Modify: `code/sewpg-bid-frontend/src/pages/GapRecognition.jsx`

- [x] **Step 1: Load project material scope**

On S3 load, call `projectsAPI.materialsPath(projectId)` and keep it in state.

- [x] **Step 2: Search across scoped folders only**

When searching existing material, query raw files for each readable scope path with the same keyword and bid type, merge by material id, and show only scoped results.

- [x] **Step 3: Add scope hint to the page**

Show the current readable scope near the search box so the operator understands why unrelated customer/project files are hidden.

- [x] **Step 4: Run frontend check**

Run: `npm run check` in `code/sewpg-bid-frontend`

Expected: command succeeds; only existing Vite chunk-size warnings are acceptable.

### Task 4: Docs, Runtime, and Progress

**Files:**
- Modify: `code/AGENT.md`
- Modify: `doc/12-数据存储与素材库数据说明.md`
- Modify: `code/progress.md`

- [x] **Step 1: Update project wording**

Document that 素材库 is now a first-level preparation module and project workflows read a scoped material set.

- [x] **Step 2: Append progress record**

Add a dated entry to `code/progress.md` with changed behavior and verification commands.

- [x] **Step 3: Run backend and frontend checks**

Run targeted backend tests and frontend check again.

- [x] **Step 4: Rebuild and restart frontend Docker**

Run from `code`: `docker compose build web && docker compose up -d web`

Expected: web container is recreated and `curl -I http://127.0.0.1/` returns HTTP 200.
