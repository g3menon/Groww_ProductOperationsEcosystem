"""CLI entrypoint for eval suites (`python -m app.evals.run_all --phase 1` or `--all`)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch


def _ensure_eval_env() -> None:
    """Eval CLI must be runnable without a local `.env` file (stable fixtures)."""
    os.environ.setdefault("APP_ENV", "eval")
    os.environ.setdefault("LOG_LEVEL", "warning")
    os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
    os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
    os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "eval-placeholder-service-role")
    os.environ.setdefault("PHASE1_SKIP_SUPABASE_STARTUP_CHECK", "true")
    from app.core.config import clear_settings_cache

    clear_settings_cache()


def _persist_deliverable(phase: int, report) -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    out_dir = repo_root / "Deliverables" / "Evals" / f"phase-{phase}"
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    version = getattr(report, "version", f"phase{phase}")

    payload = report.model_dump()
    payload.setdefault("generated_at", datetime.now(timezone.utc).isoformat())

    out_path = out_dir / f"eval_{ts}_{version}.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "latest.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out_path


def _invoke_phase(phase: int) -> tuple[int, Path]:
    """Run one phase; returns (exit_code, deliverable_path)."""
    if phase == 1:
        from app.evals.phase1_checks import run_phase1_evals

        report = run_phase1_evals()
    elif phase == 2:
        from app.evals.pulse_checks import run_phase2_evals

        report = run_phase2_evals()
    elif phase == 3:
        from app.evals.phase3_checks import run_phase3_evals

        report = run_phase3_evals()
    elif phase == 4:
        from app.evals.phase4_checks import run_phase4_evals

        report = run_phase4_evals()
    elif phase == 5:
        from app.evals.phase5_checks import run_phase5_evals

        report = run_phase5_evals()
    elif phase == 6:
        from app.evals.phase6_checks import run_phase6_evals

        report = run_phase6_evals()
    elif phase == 7:
        from app.evals.phase7_checks import run_phase7_evals

        report = run_phase7_evals()
    elif phase == 8:
        from app.evals.phase8_checks import run_phase8_evals

        report = run_phase8_evals()
    elif phase == 9:
        from app.evals.phase9_checks import run_phase9_evals

        report = run_phase9_evals()
    else:
        raise ValueError(f"unsupported phase {phase}")

    out_path = _persist_deliverable(phase, report)
    print(report.model_dump_json(indent=2))
    print(f"\nSaved deliverable: {out_path}")
    if report.score < 85.0:
        print(f"\nFAIL: score {report.score}% is below 85%.", file=sys.stderr)
        return 1, out_path
    print(f"\nPASS: score {report.score}% (threshold 85%).")
    return 0, out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run automated eval suites.")
    parser.add_argument("--phase", type=int, default=None, help="Phase number 1–9.")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run phases 1 through 9 sequentially (fail-fast on first sub-threshold score).",
    )
    args = parser.parse_args(argv)

    if args.all:
        phases = list(range(1, 10))
    elif args.phase is not None:
        phases = [args.phase]
    else:
        phases = [1]

    bad = [p for p in phases if p not in range(1, 10)]
    if bad:
        print(f"Invalid phase(s): {bad}. Use 1–9 or --all.", file=sys.stderr)
        return 2

    _ensure_eval_env()

    worst = 0
    # Stable offline run for phases that touch FastAPI + Supabase startup helpers.
    with patch(
        "app.integrations.supabase.client.check_supabase_connectivity",
        new=AsyncMock(return_value=(True, "ok")),
    ):
        for phase in phases:
            print(f"\n========== Phase {phase} ==========", file=sys.stderr)
            code, _ = _invoke_phase(phase)
            worst = max(worst, code)
            if code != 0:
                break

    return worst


if __name__ == "__main__":
    raise SystemExit(main())
