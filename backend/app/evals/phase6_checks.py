"""Phase 6 automated evals — Advisor HITL (structural + API smoke).

Supersedes manual acceptance for reporting when used together with Evals.md override notes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import BaseModel, Field


@dataclass(frozen=True)
class Check:
    id: str
    weight: float
    fn: Callable[[], bool]


class Phase6EvalReport(BaseModel):
    version: str = Field(default="phase6-v1")
    total_weight: float
    earned_weight: float
    score: float
    checks: list[dict[str, object]]


def _client() -> TestClient:
    from app.main import app as fastapi_app

    return TestClient(fastapi_app, raise_server_exceptions=False)


def _future_date() -> str:
    return (date.today() + timedelta(days=7)).isoformat()


def _create_booking(c: TestClient) -> str | None:
    r = c.post(
        "/api/v1/booking/create",
        json={
            "customer_name": "Advisor Eval User",
            "customer_email": "advisor-eval@example.com",
            "issue_summary": "Phase 6 automated eval booking",
            "preferred_date": _future_date(),
            "preferred_time": "11:00",
            "idempotency_key": f"phase6-eval-{uuid4()}",
        },
    )
    if r.status_code != 201:
        return None
    data = (r.json().get("data") or {})
    return data.get("booking_id")


def _openapi_advisor_paths() -> bool:
    c = _client()
    spec = c.get("/openapi.json").json()
    paths = spec.get("paths") or {}
    need = [
        "/api/v1/advisor/pending",
        "/api/v1/advisor/upcoming",
        "/api/v1/advisor/approve/{booking_id}",
        "/api/v1/advisor/reject/{booking_id}",
        "/api/v1/approval/{approval_id}/approve",
        "/api/v1/approval/{approval_id}/reject",
    ]
    return all(p in paths for p in need)


def _pending_contains_created_booking() -> bool:
    c = _client()
    bid = _create_booking(c)
    if not bid:
        return False
    pr = c.get("/api/v1/advisor/pending")
    if pr.status_code != 200:
        return False
    items = ((pr.json().get("data") or {}).get("items")) or []
    return any((it.get("booking_id") == bid for it in items))


def _approve_updates_status() -> bool:
    c = _client()
    bid = _create_booking(c)
    if not bid:
        return False
    ar = c.post(f"/api/v1/advisor/approve/{bid}", json={"reason": "phase6 eval"})
    if ar.status_code != 200:
        return False
    data = ar.json().get("data") or {}
    if data.get("new_status") != "approved":
        return False
    booking = data.get("booking") or {}
    return booking.get("status") == "approved"


def _upcoming_contains_approved() -> bool:
    c = _client()
    bid = _create_booking(c)
    if not bid:
        return False
    c.post(f"/api/v1/advisor/approve/{bid}", json={"reason": "phase6 eval upcoming"})
    ur = c.get("/api/v1/advisor/upcoming")
    if ur.status_code != 200:
        return False
    items = ((ur.json().get("data") or {}).get("items")) or []
    return any(it.get("booking_id") == bid for it in items)


def _duplicate_approve_idempotent() -> bool:
    c = _client()
    bid = _create_booking(c)
    if not bid:
        return False
    first = c.post(f"/api/v1/advisor/approve/{bid}", json={"reason": "first"})
    if first.status_code != 200:
        return False
    second = c.post(f"/api/v1/advisor/approve/{bid}", json={"reason": "second"})
    if second.status_code != 200:
        return False
    data = second.json().get("data") or {}
    return data.get("idempotent") is True


def run_phase6_evals() -> Phase6EvalReport:
    with patch(
        "app.integrations.supabase.client.check_supabase_connectivity",
        new=AsyncMock(return_value=(True, "ok")),
    ):
        checks: list[Check] = [
            Check("openapi_advisor_paths", 30.0, _openapi_advisor_paths),
            Check("pending_contains_created_booking", 22.0, _pending_contains_created_booking),
            Check("approve_updates_status", 23.0, _approve_updates_status),
            Check("upcoming_contains_approved", 15.0, _upcoming_contains_approved),
            Check("duplicate_approve_idempotent", 10.0, _duplicate_approve_idempotent),
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
        return Phase6EvalReport(
            total_weight=total,
            earned_weight=earned,
            score=score,
            checks=rows,
        )
