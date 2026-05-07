"""Booking APIs — Phase 5.

Routes:
  POST /api/v1/booking/create         Create a new booking
  GET  /api/v1/booking/{booking_id}   Fetch a booking by ID
  POST /api/v1/booking/cancel         Cancel a booking by ID

All responses use APIEnvelope[T] (Docs/Low Level Architecture.md §6.2).
Errors are user-safe: no stack traces, no raw DB details (G7, Rules UI4).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import ValidationError

from app.core.config import get_settings
from app.main import limiter
from app.repositories.booking_repository import get_booking_repository
from app.schemas.booking import BookingCancelRequest, BookingCreateRequest, BookingDetail
from app.schemas.common import APIEnvelope, ErrorDetail
from app.services.booking_workflow_service import (
    BookingAlreadyCancelledError,
    BookingDuplicateError,
    BookingInvalidTransitionError,
    BookingNotFoundError,
    cancel_booking,
    create_booking,
    get_booking,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/booking")


async def _parse_booking_create_payload(request: Request) -> BookingCreateRequest:
    """Parse JSON body explicitly (slowapi + postponed annotations break plain body models)."""

    try:
        raw = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail=[{"type": "json_invalid", "loc": ["body"], "msg": "Invalid JSON"}])
    if not isinstance(raw, dict):
        raise HTTPException(
            status_code=422,
            detail=[{"type": "model_attributes_type", "loc": ["body"], "msg": "Input should be a valid dictionary"}],
        )
    try:
        return BookingCreateRequest.model_validate(raw)
    except ValidationError as exc:
        # Pydantic v2 errors include a `ctx` key that may hold the original
        # exception object (e.g. ValueError), which is not JSON serializable.
        # Strip to only the fields FastAPI's standard error shape needs.
        safe_errors = [
            {"type": e["type"], "loc": list(e["loc"]), "msg": e["msg"]}
            for e in exc.errors()
        ]
        raise HTTPException(status_code=422, detail=safe_errors) from exc


# ────────────────────────────────────────────────────────────────────
# POST /booking/create
# ────────────────────────────────────────────────────────────────────


@router.post("/create", response_model=APIEnvelope[BookingDetail], status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def create_booking_route(
    request: Request,
    response: Response,
    body: BookingCreateRequest = Depends(_parse_booking_create_payload),
) -> APIEnvelope[BookingDetail]:
    """Create a new booking from the customer flow.

    Returns 201 with the new BookingDetail on success.
    Returns 409 (with the existing booking in data) if idempotency_key was
    already used — this is an idempotent duplicate-submit response (G9, D6).
    Returns 422 if preferred_date is in the past or request is invalid.
    """
    settings = get_settings()
    repo = get_booking_repository(settings)

    try:
        detail = await create_booking(request=body, repo=repo, settings=settings)
    except BookingDuplicateError as exc:
        # Idempotent duplicate — return 409 with the existing booking so the
        # client can reconcile without resubmitting (G9).
        logger.info("booking_duplicate_submission", extra={"booking_id": exc.existing.booking_id})
        response.status_code = status.HTTP_409_CONFLICT
        return APIEnvelope(
            success=False,
            message="duplicate_submission",
            data=exc.existing,
            errors=[
                ErrorDetail(
                    code="booking_duplicate_submission",
                    message="A booking with this idempotency key already exists.",
                    detail=exc.existing.booking_id,
                )
            ],
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "booking_invalid_input", "message": str(exc)},
        )

    return APIEnvelope(
        success=True,
        message="booking_created",
        data=detail,
    )


# ────────────────────────────────────────────────────────────────────
# GET /booking/{booking_id}
# ────────────────────────────────────────────────────────────────────


@router.get("/{booking_id}", response_model=APIEnvelope[BookingDetail])
async def get_booking_route(booking_id: str) -> APIEnvelope[BookingDetail]:
    """Fetch a booking by its booking ID.

    Returns 404 with a safe message if the booking does not exist.
    """
    settings = get_settings()
    repo = get_booking_repository(settings)

    try:
        detail = await get_booking(booking_id=booking_id, repo=repo)
    except BookingNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "booking_not_found", "message": f"Booking {booking_id!r} not found."},
        )

    return APIEnvelope(
        success=True,
        message="booking_detail",
        data=detail,
    )


# ────────────────────────────────────────────────────────────────────
# POST /booking/cancel
# ────────────────────────────────────────────────────────────────────


@router.post("/cancel", response_model=APIEnvelope[BookingDetail])
async def cancel_booking_route(body: BookingCancelRequest) -> APIEnvelope[BookingDetail]:
    """Cancel a booking by booking_id.

    Idempotent: if already cancelled, returns 200 with the current booking state
    and a clear message — no error for a second cancel of the same booking (G9).

    Returns 404 for non-existent booking IDs.
    Returns 422 when the booking is in a terminal state that does not permit
    cancellation (e.g. completed, rejected) — includes the current status in the
    error detail so the client can display an actionable message.
    """
    settings = get_settings()
    repo = get_booking_repository(settings)

    try:
        detail = await cancel_booking(request=body, repo=repo)
    except BookingAlreadyCancelledError as exc:
        # Idempotent — the booking is already cancelled; return current state.
        return APIEnvelope(
            success=True,
            message="booking_already_cancelled",
            data=exc.booking,
            errors=[
                ErrorDetail(
                    code="booking_already_cancelled",
                    message="This booking has already been cancelled.",
                    detail=exc.booking.status.value,
                )
            ],
        )
    except BookingNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "booking_not_found",
                "message": f"Booking {body.booking_id!r} not found. Please check the booking ID.",
            },
        )
    except BookingInvalidTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "booking_invalid_transition",
                "message": (
                    f"This booking cannot be cancelled. "
                    f"Current status: {exc.from_status.value!r}."
                ),
            },
        )

    return APIEnvelope(
        success=True,
        message="booking_cancelled",
        data=detail,
    )
