"""Auth APIs (Phase 7).

Implements a minimal Google OAuth login + callback to store tokens in Supabase.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.core.config import get_settings
from app.services.google_oauth_service import (
    build_login_url,
    exchange_code_and_store_tokens,
    resolve_oauth_redirect_uri,
    validate_and_consume_state,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth")


@router.get("/google/login")
async def google_login(request: Request) -> RedirectResponse:
    settings = get_settings()
    try:
        redirect_uri = resolve_oauth_redirect_uri(request, settings)
        url, _state = build_login_url(settings, redirect_uri=redirect_uri)
    except Exception as exc:
        logger.exception("oauth_login_error", exc_info=exc)
        raise HTTPException(status_code=400, detail="oauth_error") from exc
    return RedirectResponse(url=url, status_code=302)


@router.get("/google/callback")
async def google_callback(code: str = Query(...), state: str = Query(...)) -> JSONResponse:
    settings = get_settings()
    ok, redirect_uri = validate_and_consume_state(state)
    if not ok or not redirect_uri:
        raise HTTPException(status_code=400, detail="invalid_oauth_state")
    try:
        data = await exchange_code_and_store_tokens(
            settings=settings, code=code, redirect_uri=redirect_uri
        )
    except Exception as exc:
        logger.exception("oauth_callback_error", exc_info=exc)
        raise HTTPException(status_code=400, detail="oauth_error") from exc
    return JSONResponse(status_code=200, content={"success": True, "message": "oauth_connected", "data": data, "errors": []})