# Groww Product Operations Ecosystem

Single-repo dashboard (Next.js + FastAPI + Supabase) for **Groww** product operations: customer chat (MF + fee), weekly pulse from Play Store reviews, advisor approvals, and governed Google integrations.

- **Architecture & phases:** `Docs/Architecture.md`  
- **Implementation rules:** `Docs/Rules.md`  
- **Canonical URLs & Playwright rules:** `Deliverables/Resources.md`  
- **Ops:** `Docs/Runbook.md`  
- **Full E2E without voice:** use **End-to-end test (text-only, before voice / Phase 8)** in the runbook before depending on STT/TTS.

### Production (hosted)

| Surface | URL |
| --- | --- |
| Dashboard (Vercel) | [groww-product-ops-ecosystem.vercel.app](https://groww-product-ops-ecosystem.vercel.app) |
| API origin (Railway) | [loving-art-production-d433.up.railway.app](https://loving-art-production-d433.up.railway.app) |
| Health | [GET /api/v1/health](https://loving-art-production-d433.up.railway.app/api/v1/health) |
| Google OAuth redirect (`GOOGLE_REDIRECT_URI` + GCP) | `https://loving-art-production-d433.up.railway.app/api/v1/auth/google/callback` |

Operational detail: [Docs/DeploymentGuide.md](Docs/DeploymentGuide.md). Eval snapshot: [Evals.md](Evals.md).

### RAG + MF metrics index (Phase 4)

Full BM25/embedding retrieval and structured MF answers need on-disk indexes generated from the fixture corpus (or a live scrape). **Run this once per clone** (or after changing sources):

```powershell
# Repository root (e.g. Groww_ProductOperationsEcosystem\)
backend\.venv\Scripts\python.exe scripts\rebuild_index.py
```

That writes `backend/app/rag/index/chunks.json` and `backend/app/rag/index/mf_metrics.json`. For live Groww pages with JS-rendered NAV/AUM/holdings, use `scripts/rebuild_index.py --scrape` (network + Chromium; run `playwright install chromium` if needed). Set `SKIP_PLAYWRIGHT_MF=true` to skip browser enrichment during scrape.

## Phase 1 — local smoke

1. Copy `.env.example` to `.env` and fill **backend** `FRONTEND_BASE_URL`, `SUPABASE_URL`, and `SUPABASE_SERVICE_ROLE_KEY` (use `PHASE1_SKIP_SUPABASE_STARTUP_CHECK=true` only if you intentionally run without Supabase).
2. From `backend/`: use a **Python 3.11** virtualenv (same minor as `Dockerfile`), install deps, then run uvicorn — same commands as **Local setup → Python version** / **Start backend**.
3. From `frontend/`: set `NEXT_PUBLIC_API_BASE_URL` (e.g. `http://127.0.0.1:8000`), then `npm install` and `npm run dev`.
4. Phase 1 evals: from `backend/`, `.\.venv\Scripts\python.exe -m app.evals.run_all --phase 1` (must score **≥ 85%**; default fixture env is embedded for CI-style runs).

## Local setup (Windows PowerShell) — Phase 1 + Phase 2

### Python version (backend / tests)

Use **CPython 3.11.x** for the backend venv so installs and `pytest` match production (`python:3.11-slim`) and pick up prebuilt wheels for native packages (`lxml`, `greenlet`, Playwright). On Windows, if `python` points at 3.14, use the launcher once to create the venv:

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

For tests: `cd backend` then `.\.venv\Scripts\python.exe -m pytest`. The file `backend/.python-version` is set to `3.11` for pyenv-style tools.

Automated check (requires `py -3.11` / Python 3.11 installed): from `backend/`, run `.\ensure_python_env.ps1` — it creates or recreates `.venv` with 3.11 if needed and runs `pip install -r requirements.txt`.

**Cursor / VS Code:** the repo includes `.vscode/settings.json` pointing at `backend/.venv` (Windows path). On macOS or Linux, choose **Python: Select Interpreter** → `backend/.venv/bin/python`, or run `python -m pytest` only after `source backend/.venv/bin/activate`.

### 0) Apply Supabase schema (one-time per project)

- In Supabase SQL editor, run: `infra/supabase/phase1_phase2_schema.sql`

### 1) Create `.env`

Copy `.env.example` → `.env` and fill at minimum:

- Backend: `APP_ENV`, `FRONTEND_BASE_URL`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `DEFAULT_TIMEZONE`
- Frontend: `NEXT_PUBLIC_API_BASE_URL` (and optionally Supabase public vars for later phases)

### 2) Start backend

```powershell
cd backend
# One-time: py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Smoke:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
Invoke-RestMethod http://127.0.0.1:8000/api/v1/dashboard/badges
```

### 3) Start frontend

```powershell
cd ..\frontend
npm install
# Next.js reads env vars from files under `frontend/` (e.g. `frontend/.env.local`),
# not the repo-root `.env`.
$env:NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:8000"
npm run dev
```

### 4) Run Play Store collector (Phase 2)

```powershell
cd ..
cd backend
.\.venv\Scripts\python.exe -m playwright install chromium
cd ..
backend\.venv\Scripts\python.exe scripts\fetch_groww_playstore_reviews.py --limit 200 --out reviews_raw.json
```

### 5) Ingest raw JSON into Supabase (Phase 2)

```powershell
backend\.venv\Scripts\python.exe scripts\ingest_sources.py --in reviews_raw.json
```

### 6) Generate pulse from real ingested data (Phase 2)

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/pulse/generate -ContentType application/json -Body '{"use_fixture":false,"lookback_weeks":8}'
Invoke-RestMethod http://127.0.0.1:8000/api/v1/pulse/current
Invoke-RestMethod http://127.0.0.1:8000/api/v1/pulse/history?limit=10
```

### 7) Run automated evals

```powershell
cd backend
.\.venv\Scripts\python.exe -m app.evals.run_all --phase 1
.\.venv\Scripts\python.exe -m app.evals.run_all --phase 2
```

