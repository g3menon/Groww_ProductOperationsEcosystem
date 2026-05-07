"""Phase 7 automated evals — integrations surface + module wiring (offline-safe).

Does not call Google APIs; validates router + imports + scheduler route behaviour when secret unset.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from pydantic import BaseModel, Field


@dataclass(frozen=True)
class Check:
    id: str
    weight: float
    fn: Callable[[], bool]


class Phase7EvalReport(BaseModel):
    version: str = Field(default="phase7-v1")
    total_weight: float
    earned_weight: float
    score: float
    checks: list[dict[str, object]]


def _client() -> TestClient:
    from app.main import app as fastapi_app

    return TestClient(fastapi_app, raise_server_exceptions=False)


def _openapi_scheduler_pulse() -> bool:
    c = _client()
    spec = c.get("/openapi.json").json()
    paths = spec.get("paths") or {}
    return "/api/v1/internal/scheduler/pulse" in paths


def _scheduler_pulse_refuses_without_valid_secret() -> bool:
    """No valid Bearer → 401 if secret configured, else 501 not configured."""
    c = _client()
    r = c.post("/api/v1/internal/scheduler/pulse")
    return r.status_code in (401, 501)


def _import_gmail_service() -> bool:
    import importlib

    mod = importlib.import_module("app.services.gmail_service")
    return hasattr(mod, "send_booking_confirmation")


def _import_calendar_service() -> bool:
    import importlib

    mod = importlib.import_module("app.services.calendar_service")
    return hasattr(mod, "create_calendar_hold")


def _import_sheets_service() -> bool:
    import importlib

    mod = importlib.import_module("app.services.sheets_service")
    return hasattr(mod, "append_advisor_sheet_row")


def _mcp_integrations_export() -> bool:
    import importlib

    mod = importlib.import_module("app.services.mcp_integrations")
    return hasattr(mod, "run_approval_integrations")


def run_phase7_evals() -> Phase7EvalReport:
    with patch(
        "app.integrations.supabase.client.check_supabase_connectivity",
        new=AsyncMock(return_value=(True, "ok")),
    ):
        checks: list[Check] = [
            Check("openapi_internal_scheduler_pulse", 22.0, _openapi_scheduler_pulse),
            Check("scheduler_pulse_refuses_without_valid_secret", 22.0, _scheduler_pulse_refuses_without_valid_secret),
            Check("import_gmail_service", 18.0, _import_gmail_service),
            Check("import_calendar_service", 18.0, _import_calendar_service),
            Check("import_sheets_service", 10.0, _import_sheets_service),
            Check("mcp_run_approval_integrations_export", 10.0, _mcp_integrations_export),
        ]
        earned = 0.0
        total = 0.0
        rows: list[dict[str, object]] = []
        for chk in checks:
            total += chk.weight
            ok = False
            try:
                ok = bool(chk.fn())
            except Exception as exc:
                rows.append({"id": chk.id, "weight": chk.weight, "passed": False, "error": str(exc)})
                continue
            if ok:
                earned += chk.weight
            rows.append({"id": chk.id, "weight": chk.weight, "passed": ok})
        score = round((earned / total) * 100.0, 2) if total else 0.0
        return Phase7EvalReport(
            total_weight=total,
            earned_weight=earned,
            score=score,
            checks=rows,
        )
