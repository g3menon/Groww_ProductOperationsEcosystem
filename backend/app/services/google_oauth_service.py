"""Google OAuth service — Phase 7.

Provides the OAuth login URL and handles the callback exchange to persist
encrypted tokens into Supabase (`google_oauth_tokens`).
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any

import httpx
from starlette.requests import Request
from supabase import Client, create_client

from app.core.config import Settings, normalize_google_oauth_scopes_value
from app.core.security import encrypt_token

logger = logging.getLogger(__name__)

# state → {created: unix_ts, redirect_uri: str} so token exchange matches authorization
_PENDING_STATES: dict[str, dict[str, Any]] = {}

_AUTH_BASE = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def resolve_oauth_redirect_uri(request: Request, settings: Settings) -> str:
    """OAuth redirect_uri must exactly match one value registered in Google Cloud Console.

    In development, derive from how the browser reached the API (`localhost` vs `127.0.0.1`)
    so it matches Authorized redirect URIs and avoids Google's \"redirect_uri_mismatch\" /
    generic \"Authorization Error\" screens.

    Outside local dev (or when HOST is neither localhost nor 127.0.0.1), use
    GOOGLE_REDIRECT_URI (e.g. Railway / custom domain callback).
    """
    configured = (settings.google_redirect_uri or "").strip()
    host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or ""
    ).strip()
    scheme = (
        request.headers.get("x-forwarded-proto", "").strip().split(",")[0].strip().lower()
        or (request.url.scheme or "http")
    )
    hostname = host.split(":")[0].lower() if host else ""
    env = (settings.app_env or "").lower()

    if env == "development" and hostname in ("localhost", "127.0.0.1") and host:
        return f"{scheme}://{host}/api/v1/auth/google/callback"

    if not settings.google_client_id:
        raise ValueError("GOOGLE_CLIENT_ID must be configured")
    if not configured:
        raise ValueError("GOOGLE_REDIRECT_URI must be configured outside local-host dev")
    return configured


def build_login_url(settings: Settings, *, redirect_uri: str) -> tuple[str, str]:
    """Return (authorize_url, state)."""
    if not settings.google_client_id:
        raise ValueError("GOOGLE_CLIENT_ID must be configured")

    # Always normalize again: Google's authorize endpoint requires space-separated
    # scopes; commas / %2C in .env produce Error 400 invalid_scope.
    scope_str = normalize_google_oauth_scopes_value(settings.google_oauth_scopes)
    if not scope_str:
        raise ValueError("GOOGLE_OAUTH_SCOPES must be configured")

    state = secrets.token_urlsafe(24)
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope_str,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    _PENDING_STATES[state] = {"created": time.time(), "redirect_uri": redirect_uri}
    return f"{_AUTH_BASE}?{urllib.parse.urlencode(params)}", state


def validate_and_consume_state(state: str) -> tuple[bool, str | None]:
    payload = _PENDING_STATES.get(state)
    if payload is None:
        return False, None
    if time.time() - float(payload["created"]) >= 600:
        del _PENDING_STATES[state]
        return False, None
    redirect_uri = str(payload["redirect_uri"])
    del _PENDING_STATES[state]
    return True, redirect_uri


def _get_supabase(settings: Settings) -> Client:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise ValueError("Supabase not configured")
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


async def exchange_code_and_store_tokens(
    *,
    settings: Settings,
    code: str,
    redirect_uri: str,
) -> dict[str, Any]:
    """Exchange OAuth code for tokens and store them encrypted in Supabase."""
    if not settings.google_client_id or not settings.google_client_secret or not redirect_uri:
        raise ValueError("Google OAuth client config missing")
    if not settings.token_encryption_key:
        raise ValueError("TOKEN_ENCRYPTION_KEY missing")

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            _TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        payload = resp.json()

    refresh_token = payload.get("refresh_token")
    access_token = payload.get("access_token")
    expires_in = int(payload.get("expires_in") or 0)

    if not refresh_token:
        # If the user previously consented, Google may omit refresh_token unless prompt=consent
        raise ValueError("refresh_token not returned; ensure prompt=consent and access_type=offline")

    authorized_email = settings.google_authorized_email or "default"
    expires_at = (_now_utc().timestamp() + expires_in) if expires_in else None
    expires_at_iso = datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat() if expires_at else None

    scope_record = normalize_google_oauth_scopes_value(settings.google_oauth_scopes) or ""
    row = {
        "authorized_email": authorized_email,
        "scopes": scope_record,
        "encrypted_refresh_token": encrypt_token(str(refresh_token), settings.token_encryption_key),
        "encrypted_access_token": encrypt_token(str(access_token), settings.token_encryption_key) if access_token else None,
        "access_token_expires_at": expires_at_iso,
        "updated_at": _now_utc().isoformat(),
    }

    sb = _get_supabase(settings)
    await asyncio.to_thread(lambda: sb.table("google_oauth_tokens").upsert(row, on_conflict="authorized_email").execute())

    logger.info("google_oauth_tokens_stored", extra={"authorized_email": authorized_email})
    return {
        "authorized_email": authorized_email,
        "access_token_present": bool(access_token),
        "expires_in": expires_in,
    }
