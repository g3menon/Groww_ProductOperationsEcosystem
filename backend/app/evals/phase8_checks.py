"""Phase 8 automated evals — Voice API surface (no live STT/TTS roundtrip required)."""

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


class Phase8EvalReport(BaseModel):
    version: str = Field(default="phase8-v1")
    total_weight: float
    earned_weight: float
    score: float
    checks: list[dict[str, object]]


def _client() -> TestClient:
    from app.main import app as fastapi_app

    return TestClient(fastapi_app, raise_server_exceptions=False)


def _openapi_voice_paths() -> bool:
    c = _client()
    spec = c.get("/openapi.json").json()
    paths = spec.get("paths") or {}
    return "/api/v1/voice/message" in paths and "/api/v1/voice" in paths


def _voice_root_returns_marker() -> bool:
    c = _client()
    r = c.get("/api/v1/voice")
    if r.status_code != 200:
        return False
    body = r.json()
    return body.get("detail") == "voice_api_phase_8"


def _voice_message_missing_upload_safe() -> bool:
    """POST without multipart audio must not 500 (adapter validates input)."""
    c = _client()
    r = c.post("/api/v1/voice/message")
    return r.status_code in (400, 422)


def _voice_adapter_service_import() -> bool:
    import importlib

    mod = importlib.import_module("app.services.voice.voice_adapter_service")
    return hasattr(mod, "VoiceAdapterService")


def run_phase8_evals() -> Phase8EvalReport:
    with patch(
        "app.integrations.supabase.client.check_supabase_connectivity",
        new=AsyncMock(return_value=(True, "ok")),
    ):
        checks: list[Check] = [
            Check("openapi_voice_paths", 40.0, _openapi_voice_paths),
            Check("voice_root_returns_marker", 30.0, _voice_root_returns_marker),
            Check("voice_message_missing_upload_safe", 15.0, _voice_message_missing_upload_safe),
            Check("voice_adapter_service_import", 15.0, _voice_adapter_service_import),
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
        return Phase8EvalReport(
            total_weight=total,
            earned_weight=earned,
            score=score,
            checks=rows,
        )
