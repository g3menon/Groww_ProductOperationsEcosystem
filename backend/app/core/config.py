"""Central application settings (Phase 1). Validates required env at import/lifespan."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_origins(value: str) -> list[str]:
    return [p.strip() for p in value.split(",") if p.strip()]


def normalize_google_oauth_scopes_value(v: object) -> str | None:
    """Return a single space-delimited scope string for Google's OAuth ``scope`` param.

    Google rejects ``invalid_scope`` if scopes are joined with commas, semicolons,
    or literal ``%2C`` / ``%3B`` (common from copy-paste). RFC 6749 expects one ``scope``
    parameter with space-separated values.
    """
    if v is None:
        return None
    s = str(v).strip()
    if (len(s) >= 2 and s[0] == s[-1]) and s[0] in "\"'":
        s = s[1:-1].strip()
    if not s:
        return None
    s = s.replace("%2C", " ").replace("%2c", " ")
    s = s.replace("%3B", " ").replace("%3b", " ")
    s = s.replace(",", " ").replace(";", " ")
    normalized = " ".join(part for part in s.split() if part.strip())
    return normalized or None


class Settings(BaseSettings):
    """App configuration. Secrets must never appear in logs or API responses (P1.4)."""

    model_config = SettingsConfigDict(
        # Support running from repo root or from `backend/` on Windows.
        # - If cwd is repo root: `.env` works.
        # - If cwd is `backend/`: `../.env` works.
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str | None = Field(default=None, validation_alias=AliasChoices("APP_ENV"))
    log_level: str = Field(default="info", validation_alias=AliasChoices("LOG_LEVEL"))

    api_base_url: str = Field(
        default="http://127.0.0.1:8000",
        validation_alias=AliasChoices("API_BASE_URL"),
    )
    frontend_base_url: str | None = Field(default=None, validation_alias=AliasChoices("FRONTEND_BASE_URL"))

    supabase_url: str | None = Field(default=None, validation_alias=AliasChoices("SUPABASE_URL"))
    supabase_service_role_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SUPABASE_SERVICE_ROLE_KEY"),
    )
    supabase_anon_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SUPABASE_ANON_KEY"),
    )

    # Declared for .env parity; not required for Phase 1 cold boot validation.
    gemini_api_key: str | None = Field(default=None, validation_alias=AliasChoices("GEMINI_API_KEY"))
    gemini_api_key_fallback: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GEMINI_API_KEY_FALLBACK"),
    )
    gemini_model: str = Field(
        default="gemini-2.5-flash",
        validation_alias=AliasChoices("GEMINI_MODEL"),
    )
    groq_api_key: str | None = Field(default=None, validation_alias=AliasChoices("GROQ_API_KEY"))
    groq_api_key_fallback: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GROQ_API_KEY_FALLBACK"),
    )

    # Max text segments forwarded to Groq for theme generation per pulse run.
    # This is a Groq TPM guardrail ONLY — it does not reduce reviews collected,
    # stored, counted in metrics, or used for quotes/normalization.
    pulse_max_theme_segments: int = Field(
        default=60,
        validation_alias=AliasChoices("PULSE_MAX_THEME_SEGMENTS"),
    )

    # ---------------------------------------------------------------------
    # LLM guardrails (Phase 4): cache, tier routing, and budgets
    # ---------------------------------------------------------------------

    llm_cache_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("LLM_CACHE_ENABLED"),
    )

    max_rag_chunks_for_llm: int = Field(
        default=3,
        validation_alias=AliasChoices("MAX_RAG_CHUNKS_FOR_LLM"),
    )
    rag_storage_mode: str = Field(
        default="file",
        validation_alias=AliasChoices("RAG_STORAGE_MODE"),
    )

    gemini_rpm_limit: int = Field(
        default=8,
        validation_alias=AliasChoices("GEMINI_RPM_LIMIT"),
    )
    groq_rpm_limit: int = Field(
        default=25,
        validation_alias=AliasChoices("GROQ_RPM_LIMIT"),
    )

    llm_light_model: str = Field(
        default="llama-3.3-70b-versatile",
        validation_alias=AliasChoices("LLM_LIGHT_MODEL"),
    )
    llm_standard_model: str = Field(
        default="llama-3.3-70b-versatile",
        validation_alias=AliasChoices("LLM_STANDARD_MODEL"),
    )
    llm_heavy_model: str = Field(
        default="gemini-2.5-flash",
        validation_alias=AliasChoices("LLM_HEAVY_MODEL"),
    )
    llm_primary_provider: str = Field(
        default="groq",
        validation_alias=AliasChoices("LLM_PRIMARY_PROVIDER"),
    )

    default_timezone: str = Field(
        default="Asia/Kolkata",
        validation_alias=AliasChoices("DEFAULT_TIMEZONE"),
    )

    # ── Phase 7: Google OAuth app credentials ─────────────────────────────────
    # All optional: missing values cause the relevant integration to skip
    # gracefully with a warning log rather than crashing the approval flow.

    google_project_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GOOGLE_PROJECT_ID"),
    )
    google_client_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GOOGLE_CLIENT_ID"),
    )
    google_client_secret: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GOOGLE_CLIENT_SECRET"),
    )
    google_redirect_uri: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GOOGLE_REDIRECT_URI"),
    )
    google_oauth_scopes: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GOOGLE_OAUTH_SCOPES"),
    )

    @field_validator("google_oauth_scopes", mode="before")
    @classmethod
    def normalize_google_oauth_scopes(cls, v: object) -> str | None:
        """Load ``GOOGLE_OAUTH_SCOPES`` as space-delimited scopes (see ``normalize_google_oauth_scopes_value``)."""
        return normalize_google_oauth_scopes_value(v)

    # Phase 7: operational Google account identifiers
    google_authorized_email: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GOOGLE_AUTHORIZED_EMAIL"),
    )
    gmail_sender_email: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GMAIL_SENDER_EMAIL"),
    )
    google_calendar_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GOOGLE_CALENDAR_ID"),
    )
    google_sheets_spreadsheet_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GOOGLE_SHEETS_SPREADSHEET_ID"),
    )
    google_sheets_worksheet_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GOOGLE_SHEETS_WORKSHEET_NAME"),
    )

    # Phase 7: token storage encryption key (Fernet, base64-encoded 32 bytes).
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    token_encryption_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("TOKEN_ENCRYPTION_KEY"),
    )

    # Phase 7: scheduler webhook secret (SCHEDULER_SHARED_SECRET already in .env).
    scheduler_shared_secret: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SCHEDULER_SHARED_SECRET"),
    )

    # Phase 7: bootstrap refresh token (env-var fallback; Phase 8 replaces with DB row).
    # Set this to a pre-authorized refresh token for local dev when the full
    # OAuth login flow (Phase 8) has not yet been run.
    google_oauth_refresh_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GOOGLE_OAUTH_REFRESH_TOKEN"),
    )

    @field_validator("frontend_base_url", "supabase_url", "api_base_url")
    @classmethod
    def strip_urls(cls, v: str) -> str:
        return v.strip().rstrip("/")

    @model_validator(mode="after")
    def validate_phase1_required(self) -> Settings:
        missing: list[str] = []
        if not self.app_env:
            missing.append("APP_ENV")
        if not self.frontend_base_url:
            missing.append("FRONTEND_BASE_URL")
        if not self.supabase_url:
            missing.append("SUPABASE_URL")
        if not self.supabase_service_role_key:
            missing.append("SUPABASE_SERVICE_ROLE_KEY")
        if missing:
            raise ValueError(
                "Missing required environment variables for Phase 1/2: "
                + ", ".join(missing)
                + ". Ensure your `.env` is either in repo root or in `backend/`, "
                + "or export the variables in your shell before starting the backend.",
            )
        return self

    def cors_origins(self) -> list[str]:
        """Allow one or more frontend origins (comma-separated)."""
        return _split_origins(self.frontend_base_url or "")

    @model_validator(mode="after")
    def _validate_cors(self) -> Settings:
        """Warn at settings load if origins are incompatible with CORS allow_credentials (see main.py)."""
        origins = self.cors_origins()
        # app.main configures CORSMiddleware with allow_credentials=True; wildcard Origin is invalid then.
        if "*" in origins:
            raise ValueError(
                "Wildcard CORS origin '*' cannot be used with allow_credentials=True; "
                "set FRONTEND_BASE_URL to explicit origins (comma-separated).",
            )
        return self

    def safe_public_dict(self) -> dict[str, Any]:
        """Serializable snapshot for health/debug: no secrets (P1.4)."""
        return {
            "app_env": self.app_env,
            "log_level": self.log_level,
            "api_base_url": self.api_base_url,
            "frontend_base_url": self.frontend_base_url,
            "supabase_url": self.supabase_url,
            "supabase_configured": bool(self.supabase_url and self.supabase_service_role_key),
            "gemini_model": self.gemini_model,
            "default_timezone": self.default_timezone,
            "rag_storage_mode": self.rag_storage_mode,
            "llm_keys_present": {
                "gemini_primary": bool(self.gemini_api_key),
                "gemini_fallback": bool(self.gemini_api_key_fallback),
                "groq_primary": bool(self.groq_api_key),
                "groq_fallback": bool(self.groq_api_key_fallback),
            },
            "pulse_max_theme_segments": self.pulse_max_theme_segments,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()


def load_settings_from_env(overrides: dict[str, str] | None = None) -> Settings:
    """Test helper: reload env-backed settings."""
    clear_settings_cache()
    if overrides:
        for k, v in overrides.items():
            os.environ[k] = v
    return get_settings()
