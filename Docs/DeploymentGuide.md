# Deployment Guide — Groww Product Operations Ecosystem

This guide walks through deploying the full stack: **Supabase** (database) → **Railway** (FastAPI backend) → **Vercel** (Next.js frontend) → **GitHub Secrets** (CI/CD) → **Google OAuth** (governed integrations).

---

## Prerequisites

| Account | Purpose | URL |
|---------|---------|-----|
| Supabase | Postgres database, source of truth | https://supabase.com |
| Railway | FastAPI backend container | https://railway.app |
| Vercel | Next.js frontend hosting | https://vercel.com |
| Google Cloud Console | OAuth credentials, Gmail/Calendar/Sheets APIs | https://console.cloud.google.com |
| GitHub | Source control, CI, weekly cron scheduler | https://github.com |

> **Order matters.** Set up Supabase first (you will need its URLs), then Railway (you need its URL for Vercel and GitHub Secrets), then Vercel, then Google OAuth.

---

## Production URLs (reference)

| Surface | URL |
|---------|-----|
| Frontend (Vercel) | [https://groww-product-ops-ecosystem.vercel.app](https://groww-product-ops-ecosystem.vercel.app) |
| Backend (Railway API origin) | [https://loving-art-production-d433.up.railway.app](https://loving-art-production-d433.up.railway.app) |
| Health | [https://loving-art-production-d433.up.railway.app/api/v1/health](https://loving-art-production-d433.up.railway.app/api/v1/health) |
| Google OAuth redirect (`GOOGLE_REDIRECT_URI` + GCP “Authorized redirect URI”) | `https://loving-art-production-d433.up.railway.app/api/v1/auth/google/callback` |

> **OAuth path:** Use **`/api/v1/auth/google/callback`**, not `.../api/v1/auth/callback`. The mounted route is `GET /api/v1/auth/google/callback` in `backend/app/api/v1/auth.py`.

---

## Step 1 — Supabase (Database)

### 1.1 Create a Supabase Project

1. Log in to [supabase.com](https://supabase.com) and create a new project.
2. Choose a region closest to your Railway deployment region (reduces latency).
3. Note down:
   - **Project URL** → `SUPABASE_URL` (e.g., `https://xxxx.supabase.co`)
   - **Service Role Key** (under Project Settings → API → `service_role`) → `SUPABASE_SERVICE_ROLE_KEY`
   - **Anon Key** → `SUPABASE_ANON_KEY` (only needed if frontend ever queries Supabase directly; currently the frontend talks to FastAPI only)

### 1.2 Apply the Schema

Open the Supabase SQL Editor and run the following migration files **in order**:

```
infra/supabase/phase1_phase2_schema.sql   ← core tables, pulse, reviews
infra/supabase/phase3_chat_schema.sql     ← chat sessions and messages
infra/supabase/phase3_vector_schema.sql   ← RAG vector support
infra/supabase/phase4_schema.sql          ← RAG document chunks
infra/supabase/phase5_schema.sql          ← bookings and slots
infra/supabase/phase6_schema.sql          ← advisor approvals
infra/supabase/phase7_schema.sql          ← Google OAuth tokens
```

> Paste the contents of each file into the SQL Editor and click **Run**. Run them sequentially — each migration depends on the previous one's tables.

### 1.3 Enable Row Level Security (RLS)

All tables ship with RLS policies already defined in the schema files. Verify in **Table Editor → \<table\> → Policies** that policies are active for each table.

---

## Step 2 — Railway Backend

### 2.1 Connect the Repository

1. Go to [railway.app](https://railway.app) and create a new project.
2. Select **Deploy from GitHub repo** and select this repository.
3. Railway will detect `railway.toml` at the repo root, which points to the `Dockerfile`.
4. Set the **root directory** to `/` (repository root). The Dockerfile is at the root.

### 2.2 Set Environment Variables

In the Railway service **Variables** panel, add all the following:

| Variable | Required | Description |
|----------|----------|-------------|
| `APP_ENV` | Yes | Set to `production` |
| `LOG_LEVEL` | No | `info` (default); use `warning` in prod for quieter logs |
| `API_BASE_URL` | Yes | Your Railway public URL, e.g. `https://loving-art-production-d433.up.railway.app` |
| `FRONTEND_BASE_URL` | Yes | Your Vercel frontend URL, e.g. `https://groww-product-ops-ecosystem.vercel.app`. Must be exact origin (no trailing slash). Used for CORS allowlist. |
| `SUPABASE_URL` | Yes | From Step 1.3 |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes | From Step 1.3 — **backend-only; never expose to frontend** |
| `SUPABASE_ANON_KEY` | No | Only needed if backend uses anon client |
| `GEMINI_API_KEY` | Yes | Primary Gemini API key (used for pulse synthesis, answer composition) |
| `GEMINI_API_KEY_FALLBACK` | Recommended | Fallback key; used automatically on 429 / quota errors from primary |
| `GEMINI_MODEL` | No | Default: `gemini-2.5-flash`. Change only with compatibility testing. |
| `GROQ_API_KEY` | Yes | Primary Groq API key (used for theme extraction, preprocessing) |
| `GROQ_API_KEY_FALLBACK` | Recommended | Fallback key; used automatically on rate-limit errors from primary |
| `GOOGLE_PROJECT_ID` | Yes (Phase 7+) | GCP project ID that owns the OAuth credentials |
| `GOOGLE_CLIENT_ID` | Yes (Phase 7+) | OAuth 2.0 client ID from Google Cloud Console |
| `GOOGLE_CLIENT_SECRET` | Yes (Phase 7+) | OAuth 2.0 client secret — **backend-only; never expose** |
| `GOOGLE_REDIRECT_URI` | Yes (Phase 7+) | Must match the authorized redirect URI registered in GCP, e.g. `https://loving-art-production-d433.up.railway.app/api/v1/auth/google/callback` |
| `GOOGLE_OAUTH_SCOPES` | Yes (Phase 7+) | Space-separated scopes: `openid email profile https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/spreadsheets` |
| `GOOGLE_AUTHORIZED_EMAIL` | Yes (Phase 7+) | The Google account email that will be used for Gmail/Calendar/Sheets actions |
| `GMAIL_SENDER_EMAIL` | Yes (Phase 7+) | Email address to send pulse and confirmation emails from (usually same as `GOOGLE_AUTHORIZED_EMAIL`) |
| `GOOGLE_CALENDAR_ID` | Yes (Phase 7+) | Google Calendar ID for creating appointment holds (usually `primary` or a specific calendar ID) |
| `GOOGLE_SHEETS_SPREADSHEET_ID` | No | Google Sheets spreadsheet ID for advisor export |
| `GOOGLE_SHEETS_WORKSHEET_NAME` | No | Sheet/tab name for advisor export rows |
| `TOKEN_ENCRYPTION_KEY` | Yes (Phase 7+) | Fernet key for encrypting stored OAuth refresh tokens. Generate with: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `SCHEDULER_SHARED_SECRET` | Yes (Phase 7+) | Shared secret to authenticate GitHub Actions webhook calls to `/api/v1/internal/scheduler/pulse`. Must match `INTERNAL_SCHEDULER_SECRET` GitHub secret. |
| `DEFAULT_TIMEZONE` | No | Default: `Asia/Kolkata` |
| `PULSE_MAX_THEME_SEGMENTS` | No | Default: `60`. Groq TPM guardrail for pulse theme generation. |

### 2.3 Verify the Deployment

After Railway builds and deploys:

1. Visit `https://loving-art-production-d433.up.railway.app/api/v1/health` — should return `{"success": true, "data": {"status": "ok", ...}}`.
2. Note the Railway public URL — you will need it for Vercel and GitHub Secrets.

---

## Step 3 — Vercel Frontend

### 3.1 Connect the Repository

1. Go to [vercel.com](https://vercel.com), create a new project, import the GitHub repository.
2. Vercel will detect `vercel.json` at the repo root, which sets `rootDirectory: "frontend"` and `framework: "nextjs"`.
3. Do **not** change the build or output settings — they are already correct in `vercel.json`.

### 3.2 Set Environment Variables

> **Critical:** `NEXT_PUBLIC_API_BASE_URL` is a `NEXT_PUBLIC_*` variable. Next.js **bakes it into the JavaScript bundle at build time**, not runtime. It must be set in Vercel project settings **before** clicking Deploy. Deployments that run without this variable set will build but the frontend will throw "NEXT_PUBLIC_API_BASE_URL is not configured" errors in the browser.

In the Vercel project **Settings → Environment Variables**, add:

| Variable | Value | Environments |
|----------|-------|--------------|
| `NEXT_PUBLIC_API_BASE_URL` | `https://loving-art-production-d433.up.railway.app` (your Railway URL, no trailing slash, no `/api/v1` suffix) | Production, Preview, Development |

No other environment variables are required for the frontend — all business logic runs in the FastAPI backend.

### 3.3 Trigger a New Deployment

After setting the environment variable, go to **Deployments → Redeploy** (or push a commit) to trigger a fresh build with the env var set.

---

## Step 4 — GitHub Secrets (for CI and Weekly Scheduler)

In the GitHub repository: **Settings → Secrets and variables → Actions**, add:

| Secret Name | Value | Used By |
|-------------|-------|---------|
| `RAILWAY_API_URL` | Your Railway backend URL, e.g. `https://loving-art-production-d433.up.railway.app` | `weekly-pulse.yml` — the POST target |
| `INTERNAL_SCHEDULER_SECRET` | Same value as `SCHEDULER_SHARED_SECRET` on Railway | `weekly-pulse.yml` — authenticates the cron request |

> **Secret alignment:** `INTERNAL_SCHEDULER_SECRET` (GitHub) and `SCHEDULER_SHARED_SECRET` (Railway env var) must have **identical values**. The backend's `/api/v1/internal/scheduler/pulse` endpoint validates the `X-Scheduler-Secret` header against `SCHEDULER_SHARED_SECRET`.

---

## Step 5 — Google OAuth Setup

### 5.1 Enable APIs in Google Cloud Console

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and select or create a GCP project.
2. Enable these APIs under **APIs & Services → Library**:
   - Gmail API
   - Google Calendar API
   - Google Sheets API
   - Cloud Speech-to-Text API (optional, Phase 8 voice)
   - Cloud Text-to-Speech API (optional, Phase 8 voice)

### 5.2 Create OAuth 2.0 Credentials

1. Go to **APIs & Services → Credentials → Create Credentials → OAuth client ID**.
2. Application type: **Web application**.
3. Add the following **Authorized redirect URIs**:
   - `https://loving-art-production-d433.up.railway.app/api/v1/auth/google/callback` (production)
   - `http://localhost:8000/api/v1/auth/google/callback` (local dev)
4. Click **Create** and note down:
   - **Client ID** → `GOOGLE_CLIENT_ID`
   - **Client Secret** → `GOOGLE_CLIENT_SECRET`

### 5.3 Configure OAuth Consent Screen

1. Go to **APIs & Services → OAuth consent screen**.
2. User type: **External** (for testing; switch to Internal for a Workspace org account).
3. Fill in app name, support email, and developer contact.
4. Add the following **Scopes**:
   - `openid`, `email`, `profile`
   - `https://www.googleapis.com/auth/gmail.send`
   - `https://www.googleapis.com/auth/calendar.events`
   - `https://www.googleapis.com/auth/spreadsheets`
5. Add your authorized test user emails (the account that will authorize the app).

### 5.4 Authorize the Google Account

1. Visit `https://loving-art-production-d433.up.railway.app/api/v1/auth/google/login` in a browser.
2. Complete the Google sign-in flow with the operational Google account (the one in `GOOGLE_AUTHORIZED_EMAIL`).
3. After the callback, the backend stores the refresh token in Supabase (`google_oauth_tokens` table).
4. Verify with `GET /api/v1/auth/google/refresh` — should return a valid access token.

---

## Post-Deploy Smoke Tests

Run these checks after full deployment to verify the stack is healthy:

### Health Endpoint
```bash
curl https://loving-art-production-d433.up.railway.app/api/v1/health
# Expected: {"success": true, "data": {"status": "ok", "supabase": {"reachable": true, ...}}}
```

### Dashboard Load
Open `https://groww-product-ops-ecosystem.vercel.app` in a browser (production). Verify:
- Dashboard shell renders with 3 tabs (Customer, Product, Advisor)
- Status badges load (may show "Data connection pending" if Supabase is not yet fully configured)
- No browser console errors about `NEXT_PUBLIC_API_BASE_URL`

### Weekly Pulse Manual Trigger
```bash
curl -X POST https://loving-art-production-d433.up.railway.app/api/v1/internal/scheduler/pulse \
  -H "X-Scheduler-Secret: YOUR_SCHEDULER_SHARED_SECRET" \
  -H "Content-Type: application/json"
# Expected: 200 or 202 with pulse run details
```

Alternatively, trigger from GitHub: **Actions → Weekly Pulse Scheduler → Run workflow**.

### OAuth Callback Test
1. Visit `https://loving-art-production-d433.up.railway.app/api/v1/auth/google/login`
2. Complete Google sign-in
3. Verify redirect to callback succeeds and tokens are stored

### Badge Endpoint
```bash
curl https://loving-art-production-d433.up.railway.app/api/v1/dashboard/badges
# Expected: {"success": true, "data": {"customer": {...}, "product": {...}, "advisor": {...}}}
```

---

## Rollback Steps

### Railway Backend Rollback
1. Go to Railway project → **Deployments**.
2. Find the last known-good deployment and click **Rollback**.
3. Railway redeploys the previous image without code changes.

### Vercel Frontend Rollback
1. Go to Vercel project → **Deployments**.
2. Find the last known-good deployment (green checkmark).
3. Click the three-dot menu → **Promote to Production**.

### Database Rollback
Supabase does not have one-click schema rollback. To revert a schema migration:
1. Write a reverse migration SQL and run it in the SQL Editor.
2. Keep reverse migration scripts alongside each `infra/supabase/phaseN_schema.sql`.

---

## Known Issues and Workarounds

### Issue: Vercel build fails with "NEXT_PUBLIC_API_BASE_URL is not configured"
**Cause:** The env var was not set in Vercel project settings before building. Next.js bakes `NEXT_PUBLIC_*` variables into the bundle at compile time, not runtime.  
**Fix:** Add `NEXT_PUBLIC_API_BASE_URL` to Vercel **Settings → Environment Variables**, then trigger a new deployment (push a commit or use Redeploy).

### Issue: Railway healthcheck fails on first deploy
**Cause:** Playwright Chromium install and pip dependency installation can take 3–5 minutes. Railway's healthcheck timeout is set to 30s in `railway.toml`.  
**Fix:** Increase `healthcheckTimeout` temporarily in `railway.toml`, or wait for the image to fully build and cache before the next deploy.

### Issue: Weekly pulse cron fires but returns 401/403
**Cause:** `INTERNAL_SCHEDULER_SECRET` (GitHub secret) and `SCHEDULER_SHARED_SECRET` (Railway env var) are out of sync.  
**Fix:** Ensure both values are identical. Regenerate a new secret, update both, and re-run the workflow.

### Issue: Google OAuth callback returns "redirect_uri_mismatch"
**Cause:** The `GOOGLE_REDIRECT_URI` env var on Railway does not exactly match the Authorized redirect URI registered in Google Cloud Console.  
**Fix:** Check both values — they must be character-for-character identical (including `https://` and no trailing slash). The path must be **`/api/v1/auth/google/callback`**, not `/api/v1/auth/callback`.

### Issue: Health response shows `settings.api_base_url` as `http://127.0.0.1:8000` in production
**Cause:** Railway `API_BASE_URL` is missing or still reflects the local default.  
**Fix:** Set `API_BASE_URL` to the public Railway origin, e.g. `https://loving-art-production-d433.up.railway.app` (no trailing slash), then redeploy.

### Issue: Gmail send fails with "invalid_grant"
**Cause:** The stored refresh token has expired or been revoked (Google revokes tokens after ~6 months of inactivity, or if the OAuth consent screen is in "Testing" mode for >7 days).  
**Fix:** Re-authorize by visiting `GET /api/v1/auth/google/login` and completing the flow again.

### Issue: Supabase connection fails in production ("connection refused")
**Cause:** `SUPABASE_URL` or `SUPABASE_SERVICE_ROLE_KEY` is missing or incorrect on Railway.  
**Fix:** Double-check the values in Railway Variables match the Supabase project's API settings exactly.

### What the Evals Don't Cover
The Phase 9 evals verify **file presence** only (Dockerfile, railway.toml, weekly-pulse.yml, schema, package.json). They do not verify:
- Actual deployment health (Railway, Vercel, Supabase connectivity)
- OAuth token validity
- LLM API key quota
- Actual email delivery via Gmail
- End-to-end booking → approval → confirmation flow in production

Use the **Post-Deploy Smoke Tests** above for production validation.

---

## Environment Variable Reference Table

| Variable | Platform | Required | Default | Description |
|----------|----------|----------|---------|-------------|
| `NEXT_PUBLIC_API_BASE_URL` | Vercel | **Yes** | — | Railway backend URL (no trailing slash, no `/api/v1`). Set before build. |
| `APP_ENV` | Railway | **Yes** | — | `production` in prod; `eval` for tests |
| `LOG_LEVEL` | Railway | No | `info` | Python log level: `debug`, `info`, `warning`, `error` |
| `API_BASE_URL` | Railway | **Yes** | `http://127.0.0.1:8000` | This service's own public URL (for internal links, OAuth callbacks) |
| `FRONTEND_BASE_URL` | Railway | **Yes** | — | Vercel frontend origin, used for CORS allowlist |
| `SUPABASE_URL` | Railway | **Yes** | — | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Railway | **Yes** | — | Supabase service role key (elevated, backend-only) |
| `SUPABASE_ANON_KEY` | Railway | No | — | Supabase anon key (only if backend uses anon client) |
| `GEMINI_API_KEY` | Railway | **Yes** | — | Primary Gemini API key |
| `GEMINI_API_KEY_FALLBACK` | Railway | Recommended | — | Fallback Gemini key; auto-used on 429/quota errors |
| `GEMINI_MODEL` | Railway | No | `gemini-2.5-flash` | Gemini model name |
| `GROQ_API_KEY` | Railway | **Yes** | — | Primary Groq API key |
| `GROQ_API_KEY_FALLBACK` | Railway | Recommended | — | Fallback Groq key; auto-used on rate-limit errors |
| `GOOGLE_PROJECT_ID` | Railway | Yes (Phase 7+) | — | GCP project ID |
| `GOOGLE_CLIENT_ID` | Railway | Yes (Phase 7+) | — | OAuth 2.0 client ID |
| `GOOGLE_CLIENT_SECRET` | Railway | Yes (Phase 7+) | — | OAuth 2.0 client secret (never expose to frontend) |
| `GOOGLE_REDIRECT_URI` | Railway | Yes (Phase 7+) | — | Exact redirect URI registered in GCP |
| `GOOGLE_OAUTH_SCOPES` | Railway | Yes (Phase 7+) | — | Space-separated OAuth scopes |
| `GOOGLE_AUTHORIZED_EMAIL` | Railway | Yes (Phase 7+) | — | Google account email for Gmail/Calendar/Sheets operations |
| `GMAIL_SENDER_EMAIL` | Railway | Yes (Phase 7+) | — | From-address for outgoing emails |
| `GOOGLE_CALENDAR_ID` | Railway | Yes (Phase 7+) | — | Calendar ID for appointment holds (`primary` or explicit ID) |
| `GOOGLE_SHEETS_SPREADSHEET_ID` | Railway | No | — | Spreadsheet ID for advisor export |
| `GOOGLE_SHEETS_WORKSHEET_NAME` | Railway | No | — | Sheet/tab name for advisor export |
| `TOKEN_ENCRYPTION_KEY` | Railway | Yes (Phase 7+) | — | Fernet key for encrypting refresh tokens at rest |
| `SCHEDULER_SHARED_SECRET` | Railway | Yes (Phase 7+) | — | Must match `INTERNAL_SCHEDULER_SECRET` GitHub secret |
| `GOOGLE_OAUTH_REFRESH_TOKEN` | Railway | No | — | Bootstrap refresh token for local dev (replaced by DB row in prod) |
| `DEFAULT_TIMEZONE` | Railway | No | `Asia/Kolkata` | Timezone for scheduling and display |
| `PULSE_MAX_THEME_SEGMENTS` | Railway | No | `60` | Max text segments sent to Groq per pulse run (TPM guardrail) |
| `LLM_CACHE_ENABLED` | Railway | No | `true` | Enable in-memory LLM response cache |
| `MAX_RAG_CHUNKS_FOR_LLM` | Railway | No | `3` | Max RAG chunks forwarded to LLM per query |
| `RAG_STORAGE_MODE` | Railway | No | `file` | RAG index storage: `file` or `memory` |
| `RAILWAY_API_URL` | GitHub Secrets | **Yes** | — | Railway backend URL used by the weekly pulse cron job |
| `INTERNAL_SCHEDULER_SECRET` | GitHub Secrets | **Yes** | — | Must match `SCHEDULER_SHARED_SECRET` on Railway |
