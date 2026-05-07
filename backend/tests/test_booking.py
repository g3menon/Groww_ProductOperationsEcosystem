"""Booking API tests — Phase 5.

Covers:
  POST /api/v1/booking/create  — happy path, past date, invalid email, missing fields,
                                  duplicate idempotency key
  GET  /api/v1/booking/{id}    — found, not found (structured 404)
  POST /api/v1/booking/cancel  — happy path, idempotent double-cancel, not found,
                                  terminal-state rejection

The in-memory repository is reset before every test so cases are fully isolated.
"""

from __future__ import annotations

import datetime

import pytest


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_booking_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the module-level booking repo singleton before each test."""
    import app.repositories.booking_repository as repo_mod

    repo_mod._MEM_BOOKING = None


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> None:
    """Reset slowapi's in-memory rate limit counters between tests.

    Without this, the 10/minute limit on POST /booking/create fires after
    the first 10 tests that call create, causing later tests to get 429s
    instead of the expected 201s.
    """
    from app.main import app

    try:
        app.state.limiter._storage.reset()
    except Exception:
        pass


def _future_date(days: int = 7) -> str:
    return (datetime.date.today() + datetime.timedelta(days=days)).isoformat()


def _past_date(days: int = 1) -> str:
    return (datetime.date.today() - datetime.timedelta(days=days)).isoformat()


def _valid_payload(**overrides) -> dict:
    base = {
        "customer_name": "Priya Sharma",
        "customer_email": "priya@example.com",
        "issue_summary": "Need advice on mutual fund portfolio rebalancing.",
        "preferred_date": _future_date(),
        "preferred_time": "10:30",
    }
    base.update(overrides)
    return base


# ── POST /booking/create ──────────────────────────────────────────────────────


def test_create_booking_success(client):
    """Happy path: valid payload → 201 with BookingDetail."""
    r = client.post("/api/v1/booking/create", json=_valid_payload())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["success"] is True
    assert body["message"] == "booking_created"
    data = body["data"]
    assert data["booking_id"].startswith("BK-")
    assert data["status"] == "pending_advisor_approval"
    assert data["customer_email"] == "priya@example.com"
    assert data["preferred_time"] == "10:30"
    assert "display_timezone" in data


def test_create_booking_sets_pending_advisor_approval(client):
    """New bookings always start in PENDING_ADVISOR_APPROVAL state."""
    r = client.post("/api/v1/booking/create", json=_valid_payload())
    assert r.json()["data"]["status"] == "pending_advisor_approval"


def test_create_booking_past_date_returns_422_with_message(client):
    """A past preferred_date must return 422 with a human-readable 'message' key,
    not a bare object that JavaScript would render as '[object Object]'."""
    r = client.post("/api/v1/booking/create", json=_valid_payload(preferred_date=_past_date()))
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    # detail must be an object with a 'message' string — not a bare dict/list
    assert isinstance(detail, dict), f"Expected dict detail, got: {type(detail).__name__}"
    assert "message" in detail, f"Expected 'message' key in detail, got keys: {list(detail.keys())}"
    assert isinstance(detail["message"], str)
    assert "past" in detail["message"].lower() or "future" in detail["message"].lower()
    assert detail.get("code") == "booking_invalid_input"


def test_create_booking_invalid_email_returns_422_with_msg_array(client):
    """Invalid email triggers Pydantic validation → 422 with an array of error dicts,
    each containing a 'msg' key — the shape that extractErrorMessage() handles."""
    r = client.post("/api/v1/booking/create", json=_valid_payload(customer_email="not-an-email"))
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert isinstance(detail, list), f"Expected list detail, got: {type(detail).__name__}"
    assert len(detail) > 0
    first = detail[0]
    assert "msg" in first, f"Expected 'msg' key in validation error, got: {list(first.keys())}"
    assert isinstance(first["msg"], str)


def test_create_booking_missing_required_field_returns_422(client):
    """Missing customer_name triggers a Pydantic validation error array."""
    payload = _valid_payload()
    del payload["customer_name"]
    r = client.post("/api/v1/booking/create", json=payload)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert isinstance(detail, list)
    locs = [str(e.get("loc", [])) for e in detail]
    assert any("customer_name" in loc for loc in locs)


def test_create_booking_issue_summary_too_short_returns_422(client):
    """issue_summary with fewer than 10 chars → validation error."""
    r = client.post("/api/v1/booking/create", json=_valid_payload(issue_summary="short"))
    assert r.status_code == 422, r.text


def test_create_booking_invalid_time_format_returns_422(client):
    """preferred_time not matching HH:MM pattern → validation error."""
    r = client.post("/api/v1/booking/create", json=_valid_payload(preferred_time="9:5"))
    assert r.status_code == 422, r.text


def test_create_booking_idempotency_duplicate_returns_409(client):
    """Second submission with same idempotency_key → 409 with existing booking."""
    payload = _valid_payload(idempotency_key="test-idem-001")
    r1 = client.post("/api/v1/booking/create", json=payload)
    assert r1.status_code == 201, r1.text
    original_id = r1.json()["data"]["booking_id"]

    r2 = client.post("/api/v1/booking/create", json=payload)
    assert r2.status_code == 409, r2.text
    body = r2.json()
    assert body["success"] is False
    assert body["message"] == "duplicate_submission"
    assert body["data"]["booking_id"] == original_id
    errors = body["errors"]
    assert len(errors) == 1
    assert errors[0]["code"] == "booking_duplicate_submission"


def test_create_booking_no_idempotency_key_allows_duplicates(client):
    """Without an idempotency_key two identical submissions both succeed."""
    payload = _valid_payload()
    r1 = client.post("/api/v1/booking/create", json=payload)
    r2 = client.post("/api/v1/booking/create", json=payload)
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["data"]["booking_id"] != r2.json()["data"]["booking_id"]


def test_create_booking_email_normalized_to_lowercase(client):
    """Emails should be stripped and lowercased per the schema validator."""
    r = client.post("/api/v1/booking/create", json=_valid_payload(customer_email="  PRIYA@EXAMPLE.COM  "))
    assert r.status_code == 201, r.text
    assert r.json()["data"]["customer_email"] == "priya@example.com"


def test_create_booking_session_id_optional(client):
    """session_id is optional; omitting it should not cause an error."""
    payload = _valid_payload()
    payload.pop("session_id", None)
    r = client.post("/api/v1/booking/create", json=payload)
    assert r.status_code == 201, r.text


# ── GET /booking/{booking_id} ────────────────────────────────────────────────


def test_get_booking_success(client):
    """Fetching a just-created booking returns its full detail."""
    r_create = client.post("/api/v1/booking/create", json=_valid_payload())
    assert r_create.status_code == 201
    booking_id = r_create.json()["data"]["booking_id"]

    r = client.get(f"/api/v1/booking/{booking_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["data"]["booking_id"] == booking_id


def test_get_booking_not_found_returns_404_with_message(client):
    """Unknown booking_id → 404 with a structured detail dict containing 'message'.
    This is the shape that extractErrorMessage() in api-client.ts must handle
    (i.e. NOT '[object Object]')."""
    r = client.get("/api/v1/booking/BK-DOES-NOT-EXIST")
    assert r.status_code == 404, r.text
    detail = r.json()["detail"]
    assert isinstance(detail, dict), f"Expected dict detail, got {type(detail).__name__}"
    assert "message" in detail
    assert detail.get("code") == "booking_not_found"
    assert isinstance(detail["message"], str)
    assert len(detail["message"]) > 0


# ── POST /booking/cancel ─────────────────────────────────────────────────────


def test_cancel_booking_success(client):
    """Cancel a pending booking → 200 with status 'cancelled'."""
    booking_id = client.post("/api/v1/booking/create", json=_valid_payload()).json()["data"]["booking_id"]

    r = client.post("/api/v1/booking/cancel", json={"booking_id": booking_id, "reason": "Changed my mind"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["message"] == "booking_cancelled"
    assert body["data"]["status"] == "cancelled"
    assert body["data"]["cancellation_reason"] == "Changed my mind"


def test_cancel_booking_idempotent_double_cancel(client):
    """Cancelling an already-cancelled booking → 200 (idempotent, G9)."""
    booking_id = client.post("/api/v1/booking/create", json=_valid_payload()).json()["data"]["booking_id"]
    client.post("/api/v1/booking/cancel", json={"booking_id": booking_id})

    r2 = client.post("/api/v1/booking/cancel", json={"booking_id": booking_id})
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["success"] is True
    assert body["message"] == "booking_already_cancelled"
    assert body["data"]["status"] == "cancelled"


def test_cancel_booking_not_found_returns_404_with_message(client):
    """Cancelling an unknown booking → 404 with structured detail (not '[object Object]')."""
    r = client.post("/api/v1/booking/cancel", json={"booking_id": "BK-NO-EXIST"})
    assert r.status_code == 404, r.text
    detail = r.json()["detail"]
    assert isinstance(detail, dict)
    assert "message" in detail
    assert detail.get("code") == "booking_not_found"


def test_cancel_booking_cancel_reason_optional(client):
    """reason field is optional in cancel request."""
    booking_id = client.post("/api/v1/booking/create", json=_valid_payload()).json()["data"]["booking_id"]
    r = client.post("/api/v1/booking/cancel", json={"booking_id": booking_id})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "cancelled"


def test_cancel_booking_terminal_rejected_returns_422(client):
    """Cancelling a booking that was rejected (terminal) → 422 with structured error."""
    import asyncio
    from datetime import datetime, timezone

    from app.core.config import get_settings
    from app.repositories.booking_repository import get_booking_repository
    from app.schemas.booking import BookingStatus

    # Create a booking first
    booking_id = client.post("/api/v1/booking/create", json=_valid_payload()).json()["data"]["booking_id"]

    # Manually advance status to REJECTED (terminal) via the repo
    settings = get_settings()
    repo = get_booking_repository(settings)
    asyncio.run(
        repo.update_status(
            booking_id=booking_id,
            new_status=BookingStatus.REJECTED,
            updated_at=datetime.now(timezone.utc),
        )
    )

    r = client.post("/api/v1/booking/cancel", json={"booking_id": booking_id})
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert isinstance(detail, dict)
    assert detail.get("code") == "booking_invalid_transition"
    assert "message" in detail
    assert "rejected" in detail["message"].lower() or "cancelled" in detail["message"].lower()
