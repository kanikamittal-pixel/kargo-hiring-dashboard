from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from scoring import bands
from scoring.experience import years_pm_experience
from scoring.llm_client import call_llm
from scoring.llm_schemas import CVScoreResult

RUBRICS_PATH = Path(__file__).resolve().parent.parent / "rubrics.json"

_rubrics_cache: dict | None = None


def load_rubrics() -> dict:
    global _rubrics_cache
    if _rubrics_cache is None:
        _rubrics_cache = json.loads(RUBRICS_PATH.read_text())
    return _rubrics_cache


class NeedsManualReview(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _get_llm_result(redacted_text: str, rubrics: dict) -> CVScoreResult:
    raw = call_llm(redacted_text, rubrics)
    try:
        return CVScoreResult.model_validate(raw)
    except ValidationError as e:
        try:
            raw_retry = call_llm(redacted_text, rubrics, repair_note=str(e))
            return CVScoreResult.model_validate(raw_retry)
        except ValidationError as e2:
            raise NeedsManualReview(f"LLM output failed validation twice: {e2}") from e2


def determine_role_from_experience(years: float) -> str:
    """Used when the uploader didn't specify PM vs SPM. PM's experience gate (1.5-5y) and
    SPM's (5-8y) barely overlap, so years alone is a strong first guess -- the gate/re-route/
    best-fit-note logic in bands.decide() still catches anything this gets wrong."""
    if years > 5:
        return "spm"
    return "pm"


def score_candidate(redacted_text: str, location_flag: str, applied_role: str | None, reference_date: date) -> dict:
    """Runs the one LLM call for this CV, then does all backend arithmetic:
    years of PM experience, gates, points, band, re-routing, and reason codes."""
    rubrics = load_rubrics()

    result = _get_llm_result(redacted_text, rubrics)

    roles_as_dicts = [r.model_dump() for r in result.roles]
    years = years_pm_experience(roles_as_dicts, reference_date)

    role_was_auto_detected = not applied_role or applied_role.strip().lower() in ("", "auto")
    resolved_role = determine_role_from_experience(years) if role_was_auto_detected else applied_role.lower()

    decision = bands.decide(
        rubrics=rubrics,
        years=years,
        ownership=result.ownership,
        location_flag=location_flag,
        pm_scores=result.pm_criteria,
        spm_scores=result.spm_criteria,
        applied_role=resolved_role,
    )

    decision["role_was_auto_detected"] = role_was_auto_detected
    decision["red_flags"] = [f.model_dump() for f in result.red_flags]
    decision["roles"] = roles_as_dicts
    decision["ownership"] = result.ownership.model_dump()
    decision["rubric_version"] = rubrics["version"]
    return decision
