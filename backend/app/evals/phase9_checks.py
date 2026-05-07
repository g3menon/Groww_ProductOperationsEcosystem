"""Phase 9 automated evals — deployment artifact presence (repo-level structural gate).

Does not deploy or hit production; validates files expected by Docs/Low Level Architecture §14.9.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class Check:
    id: str
    weight: float
    fn: Callable[[], bool]


class Phase9EvalReport(BaseModel):
    version: str = Field(default="phase9-v1")
    total_weight: float
    earned_weight: float
    score: float
    checks: list[dict[str, object]]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _dockerfile_exists() -> bool:
    return (_repo_root() / "Dockerfile").is_file()


def _railway_toml_exists() -> bool:
    return (_repo_root() / "railway.toml").is_file()


def _weekly_pulse_workflow_exists() -> bool:
    return (_repo_root() / ".github" / "workflows" / "weekly-pulse.yml").is_file()


def _supabase_baseline_schema_exists() -> bool:
    p = _repo_root() / "infra" / "supabase" / "phase1_phase2_schema.sql"
    return p.is_file()


def _frontend_package_exists() -> bool:
    return (_repo_root() / "frontend" / "package.json").is_file()


def run_phase9_evals() -> Phase9EvalReport:
    checks: list[Check] = [
        Check("dockerfile_present", 25.0, _dockerfile_exists),
        Check("railway_toml_present", 25.0, _railway_toml_exists),
        Check("weekly_pulse_github_workflow_present", 25.0, _weekly_pulse_workflow_exists),
        Check("supabase_phase1_phase2_schema_present", 15.0, _supabase_baseline_schema_exists),
        Check("frontend_package_present", 10.0, _frontend_package_exists),
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
    return Phase9EvalReport(
        total_weight=total,
        earned_weight=earned,
        score=score,
        checks=rows,
    )
