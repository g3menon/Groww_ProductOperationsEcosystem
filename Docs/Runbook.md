# Groww Product Operations Ecosystem — Lean Runbook

This runbook is the minimum operational guide for running, validating, troubleshooting, and recovering the Groww Product Operations Ecosystem.

Use it during:
- local setup,
- deployment,
- smoke testing,
- incident recovery,
- and demo prep.

## System map

- **Frontend:** Next.js on Vercel ([production dashboard](https://groww-product-ops-ecosystem.vercel.app))
- **Backend:** FastAPI on Railway ([production API origin](https://loving-art-production-d433.up.railway.app))
- **Database:** Supabase
- **LLM providers:** Gemini (**`gemini-2.5-flash`** by default) and Groq, each with **primary + fallback** API keys (`Docs/Architecture.md`)
- **Canonical Groww URLs & Playwright rules:** `Deliverables/Resources.md`
- **Google integrations:** Gmail, Calendar, Sheets
- **Scheduler:** GitHub Actions and/or backend internal trigger

## Key docs

Keep these aligned:
- `Docs/Architecture.md`
- `Docs/Rules.md`
- `Docs/Failures&EdgeCases.md`
- `Docs/UserFlow.md`
- `Docs/UI.md`
- `Deliverables/Resources.md`
- `Docs/Runbook.md`
- `.env.example`

## Low-level interface index

Use this section to jump from “what the runbook says” to the concrete API/DB/logging interfaces you need to verify.

### Backend API endpoints (current v1 routers)
All API routes are mounted under the `/api/v1` prefix (see `backend/app/api/v1/__init__.py`).

FastAPI schema:
- OpenAPI: `GET /openapi.json`
- Swagger UI: `GET /docs`

Implemented routers in this repo:
- Health: [`backend/app/api/v1/health.py`](backend/app/api/v1/health.py) → `GET /api/v1/health`
- Dashboard badges: [`backend/app/api/v1/dashboard.py`](backend/app/api/v1/dashboard.py) → `GET /api/v1/dashboard/badges`
- Weekly pulse: [`backend/app/api/v1/pulse.py`](backend/app/api/v1/pulse.py)
  - `POST /api/v1/pulse/generate`
  - `GET /api/v1/pulse/current`
  - `GET /api/v1/pulse/history`
  - `POST /api/v1/pulse/subscribe`
  - `POST /api/v1/pulse/unsubscribe`
  - `POST /api/v1/pulse/send-now`
- Customer chat: [`backend/app/api/v1/chat.py`](backend/app/api/v1/chat.py)
  - `POST /api/v1/chat/message`
  - `GET /api/v1/chat/prompts`
  - `GET /api/v1/chat/history/{session_id}`
- Automated eval runner: [`backend/app/api/v1/evals.py`](backend/app/api/v1/evals.py) → `POST /api/v1/evals/run` (supports suites: phase1/phase2/phase3)
- Booking: [`backend/app/api/v1/booking.py`](backend/app/api/v1/booking.py)
  - `POST /api/v1/booking/create`
  - `GET /api/v1/booking/{booking_id}`
  - `POST /api/v1/booking/cancel`
- Advisor: [`backend/app/api/v1/advisor.py`](backend/app/api/v1/advisor.py)
  - `GET /api/v1/advisor/pending`
  - `GET /api/v1/advisor/upcoming`
  - `POST /api/v1/advisor/approve/{booking_id}`
  - `POST /api/v1/advisor/reject/{booking_id}`
- Approval (alternate IDs): [`backend/app/api/v1/approval.py`](backend/app/api/v1/approval.py)
  - `POST /api/v1/approval/{approval_id}/approve`
  - `POST /api/v1/approval/{approval_id}/reject`
- Google OAuth (Phase 7): [`backend/app/api/v1/auth.py`](backend/app/api/v1/auth.py)
  - `GET /api/v1/auth/google/login`
  - `GET /api/v1/auth/google/callback`
- Scheduler webhook (Phase 7): [`backend/app/api/v1/internal.py`](backend/app/api/v1/internal.py)
  - `POST /api/v1/internal/scheduler/pulse` (Bearer `SCHEDULER_SHARED_SECRET`)

Voice remains out of scope for Phases 1–7 verification: [`backend/app/api/v1/voice.py`](backend/app/api/v1/voice.py) → `501` stub until Phase 8.

### Supabase schema scripts
Apply in dependency order (all additive migrations under `infra/supabase/`):

- Phase 1–2: `infra/supabase/phase1_phase2_schema.sql`
- Phase 3 chat: `infra/supabase/phase3_chat_schema.sql`
- Phase 4 RAG: `infra/supabase/phase4_schema.sql`
- Phase 5 bookings: `infra/supabase/phase5_schema.sql`
- Phase 6 advisor indexes / notes: `infra/supabase/phase6_schema.sql`
- Phase 7 integrations logs + OAuth tokens: `infra/supabase/phase7_schema.sql`

### Status/enums and response envelope
- Standard API envelope + error shape: [`backend/app/schemas/common.py`](backend/app/schemas/common.py) (`APIEnvelope`, `ErrorDetail`)
- Weekly pulse models (including degraded state and subscription status literals): [`backend/app/schemas/pulse.py`](backend/app/schemas/pulse.py)

### Correlation IDs and logging conventions
- Correlation middleware: [`backend/app/main.py`](backend/app/main.py)
  - Reads header: `X-Correlation-ID` (and `x-correlation-id`)
  - Writes response header: `X-Correlation-ID`
  - Stores in request context var for downstream log formatting
- Log formatting with correlation id: [`backend/app/core/logging.py`](backend/app/core/logging.py)
  - Formatter includes `cid=<correlation_id>`
- Correlation context var: [`backend/app/core/context.py`](backend/app/core/context.py)

## Required env groups

### Frontend
```env
NEXT_PUBLIC_API_BASE_URL=
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
```

### Backend
```env
APP_ENV=
LOG_LEVEL=
API_BASE_URL=
FRONTEND_BASE_URL=
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
GEMINI_API_KEY=
GEMINI_API_KEY_FALLBACK=
GEMINI_MODEL=gemini-2.5-flash
GROQ_API_KEY=
GROQ_API_KEY_FALLBACK=
GOOGLE_PROJECT_ID=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=
GOOGLE_OAUTH_SCOPES=
GOOGLE_AUTHORIZED_EMAIL=
GMAIL_SENDER_EMAIL=
GOOGLE_CALENDAR_ID=
GOOGLE_SHEETS_SPREADSHEET_ID=
GOOGLE_SHEETS_WORKSHEET_NAME=
TOKEN_ENCRYPTION_KEY=
SCHEDULER_SHARED_SECRET=
DEFAULT_TIMEZONE=Asia/Kolkata
```

### GitHub Actions
```env
SCHEDULER_SHARED_SECRET=
```

## Startup sequence

### Local
1. Verify env files are present and complete.
2. If you run **Groww Play Store** collection or other **Playwright** jobs locally, install browser binaries once (`playwright install` for the active Python environment) and confirm the script entrypoint in `Docs/Architecture.md` / `scripts/`.
3. Start backend.
4. Confirm backend health endpoint works.
5. Start frontend.
6. Confirm frontend can reach backend.
7. Open Customer, Product, and Advisor tabs.

### Groww Play Store reviews (Playwright) and RAG corpus

Use this when refreshing **Weekly Pulse** inputs or **RAG** MF/fee indexes.

1. **Play Store (Groww)**  
   - Run the documented job (for example `scripts/fetch_groww_playstore_reviews.py`).  
   - Confirm log lines show **parse count** and any **selector warnings**.  
   - Verify raw or normalized rows landed in the DB (or staging path) before pulse generation.

2. **Normalization**  
   - Ensure the normalization step completed for the batch (dedupe counts, dropped-row reasons in logs).  
   - On failure, fix upstream data or filters; do not run pulse or index rebuild on half-normalized batches without an explicit recovery plan.

3. **Chunking and RAG index (MF/fee scraped sources)**  
   - Run `ingest_sources.py` / pipeline as documented.  
   - Run `rebuild_index.py` (or equivalent) after source updates.  
   - Spot-check one retrieved chunk in dev: no raw HTML, citation metadata present.

4. **Pulse**  
   - Run pulse generation only after the full chain succeeded for the intended window, following the canonical pipeline order in `Deliverables/Resources.md` (**Weekly Pulse from Play Store (order)**). Or explicitly accept an **empty-ingestion** degraded mode documented in logs.

### Production

Canonical URLs (same as `Docs/DeploymentGuide.md` *Production URLs*):

- Frontend: `https://groww-product-ops-ecosystem.vercel.app`
- Backend: `https://loving-art-production-d433.up.railway.app`
- OAuth redirect (GCP + `GOOGLE_REDIRECT_URI`): `https://loving-art-production-d433.up.railway.app/api/v1/auth/google/callback` (path includes **`/google/`**)

Steps:

1. Confirm Railway env vars are correct (`API_BASE_URL`, `FRONTEND_BASE_URL`, `GOOGLE_REDIRECT_URI`, secrets — see Deployment Guide).
2. Confirm Vercel env vars are correct (`NEXT_PUBLIC_API_BASE_URL` = Railway origin above, no trailing slash).
3. Deploy backend.
4. Verify `GET https://loving-art-production-d433.up.railway.app/api/v1/health`.
5. Deploy frontend (redeploy if env changed so the bundle picks up `NEXT_PUBLIC_*`).
6. Verify dashboard load and API connectivity from the browser.

## Smoke test checklist

Run this after major changes or deploys.

- [ ] Frontend loads.
- [ ] Backend health endpoint works.
- [ ] Customer tab loads.
- [ ] Product tab loads.
- [ ] Advisor tab loads.
- [ ] One customer chat request works.
- [ ] One booking path works.
- [ ] One advisor approval/rejection action works.
- [ ] One Product Pulse path works.
- [ ] Groww Play Store ingestion path works (or documented skip) when pulse inputs changed.
- [ ] One integration path works if affected.
- [ ] Scheduler/manual trigger works if affected.

## End-to-end test (text-only, before voice / Phase 8)

Use this checklist to validate **the whole implementation through Phase 7** without STT/TTS. Voice (Phase 8) is optional and must not block sign-off on core product behavior.

**Prerequisites**

- Local or staging env matches `Docs/Architecture.md` and `.env.example` (including **primary + fallback** LLM keys if generation paths are enabled).
- `playwright install` (or equivalent) done if you run Groww Play Store collection locally.

**Ordered checks (text and UI only)**

1. **Phase 1–style connectivity:** frontend loads; backend health; badges (or stub) respond; Supabase connectivity as designed; CORS/preflight OK for `localhost:3000` → `localhost:8000`.
2. **Pulse data path:** run Playwright collection (or inject fixture raw batch) → confirm **cleaning** and **normalization** job logs → confirm **theme** step then **pulse** step produce one valid `weekly_pulses` row → Product tab shows current pulse and history where implemented.
3. **Customer text chat:** typed message and prompt chips; session/history; MF + fee + hybrid answers with citations (no microphone).
4. **Booking:** create booking from text flow; copy booking ID; cancel by ID; states visible on Customer UI.
5. **Advisor:** pending/upcoming lists; approve/reject; confirmation path matches `Docs/UserFlow.md` (text-only).
6. **Integrations (when Phase 7 is in scope):** one Gmail/Calendar path in dev or staging; scheduler manual trigger idempotent; fallback keys exercised once under forced primary quota if possible.

**Recording**

- Capture results under `Deliverables/Evals/` for the highest phase covered (per architecture quality gate).

## Main incident checks

### Groww Play Store ingestion or Playwright job fails
Check:
- job logs (selector errors, timeout, zero parse count)
- Playwright and browser versions match CI or Railway image
- network egress from runner (local, Railway, or GitHub Actions)

Fix:
- update selectors or wait conditions per `Docs/Failures&EdgeCases.md`
- reinstall browsers if image changed
- rerun normalization only after raw batch is verified

### Frontend cannot reach backend
Check:
- `NEXT_PUBLIC_API_BASE_URL`
- backend health endpoint
- browser network errors
- CORS settings

Fix:
- correct frontend env var
- restore backend
- update CORS config if needed

### Backend fails to boot
Check:
- Railway logs
- missing env vars
- config validation
- import/runtime errors

Fix:
- correct env vars
- fix startup code
- redeploy

### LLM quota or key exhaustion (Gemini / Groq)
Check:
- logs for **429**, **quota**, or **resource exhausted**
- whether the request retried on **`GEMINI_API_KEY_FALLBACK`** or **`GROQ_API_KEY_FALLBACK`**
- `GEMINI_MODEL` is set to **`gemini-2.5-flash`** unless you intentionally changed it

Fix:
- rotate or refill quotas on the primary project
- verify **both** keys per provider are valid and distinct
- temporarily reduce traffic or enable stricter caching; never log key strings

### Supabase failures
Check:
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- DB schema existence
- backend logs

Fix:
- correct keys/config
- repair schema
- redeploy if needed

### Google OAuth fails
Check:
- redirect URI
- client ID/secret
- scopes
- connected account

Fix:
- correct Google Cloud config
- reconnect Google account
- redeploy backend if callback env changed

### Gmail / Calendar / Sheets fail
Check:
- token validity
- required scopes
- sender/calendar/sheet IDs
- backend integration logs

Fix:
- reconnect OAuth
- correct provider IDs
- retry safely only after checking duplicate risk

### Scheduler fails or runs twice
Check:
- `SCHEDULER_SHARED_SECRET`
- GitHub Actions logs
- backend duplicate protection

Fix:
- correct secrets
- rerun safely
- verify idempotency

## Rollback rules

### Frontend rollback
Use when a Vercel deploy breaks production UI.

Steps:
1. Identify last healthy deployment.
2. Roll back to it.
3. Verify dashboard and tab load.
4. Investigate bad deploy after service is restored.

### Backend rollback
Use when a Railway deploy breaks API or integrations.

Steps:
1. Revert to a known good commit/config.
2. Redeploy backend.
3. Verify health endpoint.
4. Verify one DB-backed route.
5. Verify one affected integration route.

## Manual trigger paths

### Manual pulse generation
Use when scheduler fails or Product tab needs validation.

Check:
- backend healthy
- **Groww Play Store** ingestion + normalization completed for the intended date range (or explicitly accept empty-ingestion mode)
- source data exists
- generation creates exactly one expected result

### Manual scheduler trigger
Use when scheduled run did not execute.

Check:
- secret matches
- URL correct
- logs show one run only

### Manual OAuth reconnect
Use when tokens expire or wrong account is connected.

Check:
- correct Google account
- required scopes granted
- one Gmail/Calendar/Sheets action works after reconnect

## Safe mode

Use safe mode when integrations are unstable but the core product should remain usable.

Possible safe-mode actions:
- disable scheduler
- disable outbound email sends
- disable Calendar creation
- disable Sheets append
- keep dashboard read-only if needed

Rule:
- preserve workflow truth first,
- restore side effects second.

## Recovery verification

After any fix, verify:
- [ ] frontend loads
- [ ] backend health endpoint works
- [ ] all three tabs render
- [ ] one customer action works
- [ ] one product action works
- [ ] one advisor action works
- [ ] affected integration path works if relevant
- [ ] no duplicate records or side effects were created

## Escalate when

Escalate if:
- rollback does not restore service,
- production data integrity may be affected,
- duplicate emails/events/sheet rows may have been created,
- OAuth/secrets may have been exposed,
- or the failure cannot be explained quickly.

When escalating, capture:
- symptom,
- environment,
- timestamps,
- logs,
- recent changes,
- current mitigation,
- exact reproduction steps.

## Update this runbook when

Update the file whenever:
- a new external integration is added,
- a deploy/setup step changes,
- a new manual recovery path is introduced,
- a scheduler flow changes,
- **Playwright** or **ingestion/normalization/index** commands change,
- or an incident reveals a missing operational step.