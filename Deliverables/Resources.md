# Canonical sources — Groww Product Operations Ecosystem

Use this file as the **single list of URLs and collection rules** referenced from `Docs/Architecture.md`, `Docs/Runbook.md`, and `Docs/UI.md`. Do not auto-construct Groww fund URLs from display names; slugs drift after rebranding.

This document merges **product-facing sources** (Groww, Play Store), **reference data** (AMFI), **integration endpoints** (Google OAuth, Workspace scopes, LLM/Speech APIs), and **design inspiration** (Dribbble). Paths are exercised by ingestion scripts (`scripts/sources_manifest.json`, `scripts/rebuild_index.py`, `scripts/fetch_groww_playstore_reviews.py`), RAG fixtures (`backend/app/rag/fixtures/mf_corpus.json`), and backend integrations (`backend/app/services`, `backend/app/integrations`).

**Weekly Pulse from Play Store (order):** raw Playwright capture → persist raw → **cleaning** → **normalization** → (optional segment) → **theme generation (Groq)** → **pulse generation (Gemini)** → validate → store. See `Docs/Architecture.md` (Weekly pulse architecture).

---

## Groww — Google Play Store (Playwright)

- **Listing (reviews):** [https://play.google.com/store/apps/details?id=com.nextbillion.groww&hl=en_IN](https://play.google.com/store/apps/details?id=com.nextbillion.groww&hl=en_IN)  
- **Collection:** **Playwright**, server-side or batch jobs only (`scripts/fetch_groww_playstore_reviews.py`).  
- **Privacy:** Do **not** collect reviewer display names. **Do** collect **device type** (`Phone`, `Chromebook`, or `Tablet`) when shown on the listing.

### Example normalized review record (shape)

```json
{
  "review_id": "",
  "rating": 1,
  "text": "Example review text for schema validation only.",
  "date": "2026-02-14",
  "found_review_helpful": 21,
  "device": "Phone"
}
```

---

## Groww — mutual fund pages (RAG / scrape corpus)

Canonical manifest: [`scripts/sources_manifest.json`](../scripts/sources_manifest.json). Fixture corpus duplicates these URLs in [`backend/app/rag/fixtures/mf_corpus.json`](../backend/app/rag/fixtures/mf_corpus.json) (plus one **fee explainer** row that reuses the HDFC Flexi page URL).

**HTTP:** Scrapers send **`Referer: https://groww.in/`** when fetching fund HTML (`scripts/rebuild_index.py`).

### Motilal Oswal AMC

| Scheme                                                  | URL                                                                                                                                                                                |
| ------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Motilal Oswal Midcap Fund Direct Growth                 | [https://groww.in/mutual-funds/motilal-oswal-most-focused-midcap-30-fund-direct-growth](https://groww.in/mutual-funds/motilal-oswal-most-focused-midcap-30-fund-direct-growth)     |
| Motilal Oswal Flexi Cap Fund Direct Growth              | [https://groww.in/mutual-funds/motilal-oswal-most-focused-multicap-35-fund-direct-growth](https://groww.in/mutual-funds/motilal-oswal-most-focused-multicap-35-fund-direct-growth) |
| Motilal Oswal Nifty Midcap 150 Index Fund Direct Growth | [https://groww.in/mutual-funds/motilal-oswal-nifty-midcap-150-index-fund-direct-growth](https://groww.in/mutual-funds/motilal-oswal-nifty-midcap-150-index-fund-direct-growth)     |

### HDFC AMC

| Scheme                                    | URL                                                                                                                                                |
| ----------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| HDFC Large and Mid Cap Fund Direct Growth | [https://groww.in/mutual-funds/hdfc-large-and-mid-cap-fund-direct-growth](https://groww.in/mutual-funds/hdfc-large-and-mid-cap-fund-direct-growth) |
| HDFC Flexi Cap Direct Plan Growth         | [https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth](https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth)                       |
| HDFC Large Cap Fund Direct Growth         | [https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth](https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth)                 |

**Scraping note:** Groww may keep **legacy URL slugs** after scheme renames (e.g. Flexi Cap path still uses `hdfc-equity-fund-direct-growth`). Always use the URLs in this table—do not derive slugs from current scheme titles alone.

### Optional manifest extension (documented in eval notes)

Used only as an example of adding a fund via `scripts/sources_manifest.json` without code changes (`Deliverables/Evals/phase-4/ACCEPTANCE_NOTES.md`):

| Scheme                         | URL                                                                                                                                                              |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Parag Parikh Flexi Cap Direct Growth | [https://groww.in/mutual-funds/parag-parikh-long-term-value-fund-direct-growth](https://groww.in/mutual-funds/parag-parikh-long-term-value-fund-direct-growth) |

---

## Fee explainer corpus

Expense ratio and exit load (and related fee copy) appear **on each fund page** linked above. The Product-tab corpus treats those pages as **fee explainer** source material for Customer/Advisor chat—not a separate PM “fee tutorial” block (`Docs/UserFlow.md`, Rules UI18).

**Design intent for analytics:** active funds in this set carry higher expense ratios (~0.5–1%) vs the Motilal Nifty Midcap 150 index fund (~0.15–0.30%), surfacing an active vs passive fee contrast in the dataset.

---

## AMFI — NAV reference data

Bulk NAV file used for enrichment / validation (`backend/app/integrations/mf_nav_provider.py`, `scripts/rebuild_index.py`):

- [https://www.amfiindia.com/spages/NAVAll.txt](https://www.amfiindia.com/spages/NAVAll.txt)

---

## Google OAuth & Workspace (Phase 7 integrations)

**OAuth authorization (user consent):** [https://accounts.google.com/o/oauth2/v2/auth](https://accounts.google.com/o/oauth2/v2/auth) (`backend/app/services/google_oauth_service.py`)

**Token exchange / refresh:** [https://oauth2.googleapis.com/token](https://oauth2.googleapis.com/token) (`google_oauth_service.py`, `backend/app/repositories/token_repository.py`)

**OAuth scopes configured in env** (see `.env.example`, `Docs/Architecture.md`, `backend/tests/test_oauth_scopes_normalize.py`):

- [https://www.googleapis.com/auth/gmail.send](https://www.googleapis.com/auth/gmail.send)
- [https://www.googleapis.com/auth/calendar.events](https://www.googleapis.com/auth/calendar.events)
- [https://www.googleapis.com/auth/spreadsheets](https://www.googleapis.com/auth/spreadsheets)

**Developer tooling:** refresh-token workflows often use [Google OAuth 2.0 Playground](https://developers.google.com/oauthplayground) (documented in `.env.example`).

**Workspace API references** (HTTP APIs behind the Google client libraries):

- Gmail API: [https://developers.google.com/gmail/api](https://developers.google.com/gmail/api)
- Google Calendar API: [https://developers.google.com/calendar](https://developers.google.com/calendar)
- Google Sheets API: [https://developers.google.com/sheets/api](https://developers.google.com/sheets/api)

**Example Sheets workbook** cited in `Docs/Architecture.md` (replace with your deployed spreadsheet ID in production):

- [https://docs.google.com/spreadsheets/d/1EQe6JVH6RfPnLgf3vvdLycYx0xtmippKMya1UA7rVow/edit?usp=sharing](https://docs.google.com/spreadsheets/d/1EQe6JVH6RfPnLgf3vvdLycYx0xtmippKMya1UA7rVow/edit?usp=sharing)

---

## LLM providers (pulse, themes, RAG)

**Google Gemini** — used via `google.generativeai` for embeddings / generation paths (`backend/app/llm/gemini_client.py`, `backend/app/rag/embeddings.py`, `rerank.py`). Product documentation: [https://ai.google.dev/gemini-api/docs](https://ai.google.dev/gemini-api/docs)

**Groq** — OpenAI-compatible Chat Completions API (`groq` Python SDK, `backend/app/llm/groq_client.py`). Base URL used by the SDK: [https://api.groq.com/openai/v1](https://api.groq.com/openai/v1) — see [https://console.groq.com/docs](https://console.groq.com/docs)

---

## Google Cloud Speech & TTS (Phase 8 voice adapter)

Clients: `google.cloud.speech`, `google.cloud.texttospeech` (`backend/app/integrations/google/stt_client.py`, `tts_client.py`). Official product pages:

- Speech-to-Text: [https://cloud.google.com/speech-to-text](https://cloud.google.com/speech-to-text)
- Text-to-Speech: [https://cloud.google.com/text-to-speech](https://cloud.google.com/text-to-speech)

---

## Reference UI (visual inspiration only)

Linked from `Docs/UI.md` and early UX alignment—not sources for factual MF answers.

- Product / pulse + email layout inspiration: [https://dribbble.com/shots/26857590-CallAI-AI-Voice-Assistants-Dashboard-Design](https://dribbble.com/shots/26857590-CallAI-AI-Voice-Assistants-Dashboard-Design)  
- Customer chat: [https://dribbble.com/shots/26057790-Ultima-AI-Dashboard-Your-Smart-Chat-Partner](https://dribbble.com/shots/26057790-Ultima-AI-Dashboard-Your-Smart-Chat-Partner) and [https://dribbble.com/shots/26756293-Voice-AI-Automation-Dashboard](https://dribbble.com/shots/26756293-Voice-AI-Automation-Dashboard)  
- Advisor: [https://dribbble.com/shots/25680703-Voice-AI-Agent-Configurations](https://dribbble.com/shots/25680703-Voice-AI-Agent-Configurations)

---

## Deployment & hosting references (Phase 9)

Documented topology: Vercel (frontend), Railway (backend), Supabase (database). Official docs:

- Vercel: [https://vercel.com/docs](https://vercel.com/docs)
- Railway: [https://docs.railway.app](https://docs.railway.app)
- Supabase: [https://supabase.com/docs](https://supabase.com/docs)

**This project’s production deployments (canonical):**

- Frontend (Vercel): `https://groww-product-ops-ecosystem.vercel.app`
- Backend API (Railway): `https://loving-art-production-d433.up.railway.app`
- Google OAuth redirect (GCP authorized URI + `GOOGLE_REDIRECT_URI`): `https://loving-art-production-d433.up.railway.app/api/v1/auth/google/callback`

---

## Plain-text URL inventory (35 distinct HTTPS destinations)

Use this checklist for capstone “source manifest” completeness. *Groww fund URLs count once each even if referenced in manifest + fixture + tests.* Production deploy URLs (**33–35**) are canonical for Phase 9; keep them synced with Railway/Vercel if the project moves.

1. `https://play.google.com/store/apps/details?id=com.nextbillion.groww&hl=en_IN`
2. `https://groww.in/` (Referer only)
3. `https://groww.in/mutual-funds/motilal-oswal-most-focused-midcap-30-fund-direct-growth`
4. `https://groww.in/mutual-funds/motilal-oswal-most-focused-multicap-35-fund-direct-growth`
5. `https://groww.in/mutual-funds/motilal-oswal-nifty-midcap-150-index-fund-direct-growth`
6. `https://groww.in/mutual-funds/hdfc-large-and-mid-cap-fund-direct-growth`
7. `https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth`
8. `https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth`
9. `https://groww.in/mutual-funds/parag-parikh-long-term-value-fund-direct-growth` (optional manifest example)
10. `https://www.amfiindia.com/spages/NAVAll.txt`
11. `https://accounts.google.com/o/oauth2/v2/auth`
12. `https://oauth2.googleapis.com/token`
13. `https://www.googleapis.com/auth/gmail.send`
14. `https://www.googleapis.com/auth/calendar.events`
15. `https://www.googleapis.com/auth/spreadsheets`
16. `https://developers.google.com/oauthplayground`
17. `https://developers.google.com/gmail/api`
18. `https://developers.google.com/calendar`
19. `https://developers.google.com/sheets/api`
20. `https://docs.google.com/spreadsheets/d/1EQe6JVH6RfPnLgf3vvdLycYx0xtmippKMya1UA7rVow/edit?usp=sharing`
21. `https://ai.google.dev/gemini-api/docs`
22. `https://api.groq.com/openai/v1`
23. `https://console.groq.com/docs`
24. `https://cloud.google.com/speech-to-text`
25. `https://cloud.google.com/text-to-speech`
26. `https://dribbble.com/shots/26857590-CallAI-AI-Voice-Assistants-Dashboard-Design`
27. `https://dribbble.com/shots/26057790-Ultima-AI-Dashboard-Your-Smart-Chat-Partner`
28. `https://dribbble.com/shots/26756293-Voice-AI-Automation-Dashboard`
29. `https://dribbble.com/shots/25680703-Voice-AI-Agent-Configurations`
30. `https://vercel.com/docs` (frontend hosting — `Docs/Low Level Architecture.md` §14.9)
31. `https://docs.railway.app` (backend hosting — root `railway.toml`)
32. `https://supabase.com/docs` (managed Postgres / client — infra migrations under `infra/supabase/`)
33. `https://groww-product-ops-ecosystem.vercel.app` (production Next.js dashboard — Phase 9)
34. `https://loving-art-production-d433.up.railway.app` (production FastAPI origin — Phase 9)
35. `https://loving-art-production-d433.up.railway.app/api/v1/auth/google/callback` (production OAuth redirect — Phase 7/9)

**Excluded by design from this inventory:** `http://localhost:*`, `http://127.0.0.1:*`, docker internal hosts, and placeholder eval URLs such as `https://example.supabase.co` (see `backend/app/evals/run_all.py`).
