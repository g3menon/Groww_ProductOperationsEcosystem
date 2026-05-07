This folder holds **manual and automated** eval artifacts by phase (see `Docs/Rules.md` EVAL* and `Docs/Runbook.md` Recording).

- `phase-1/` … `phase-9/`: automated JSON artifacts + `latest.json` via `backend/app/evals/run_all.py`
- Phases **6–9** automated suites are **structural / smoke** checks (OpenAPI, advisor flow, integration imports, voice routes, deployment files); they **replace manual acceptance in Evals.md** when run — production smoke and live OAuth remain separate.
- **Production URLs:** see the repo root **`Evals.md`** header (Vercel + Railway + OAuth path) and **`Docs/DeploymentGuide.md`** (*Production URLs*).

For local runs:

```bash
cd backend
py -3.11 -m app.evals.run_all --all
# or one phase:
py -3.11 -m app.evals.run_all --phase 6
```

Notes:
- Threshold on every phase score: **≥ 85%**.
- Still run `Docs/Runbook.md` end-to-end when validating UX or live Google integrations; automation does not hit production APIs.
