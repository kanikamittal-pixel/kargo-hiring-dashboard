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


def score_candidate(redacted_text: str, location_flag: str, applied_role: str, reference_date: date) -> dict:
    """Runs the one LLM call for this CV, then does all backend arithmetic:
    years of PM experience, gates, points, band, re-routing, and reason codes."""
    rubrics = load_rubrics()
    applied_role = applied_role.lower()

    result = _get_llm_result(redacted_text, rubrics)

    roles_as_dicts = [r.model_dump() for r in result.roles]
    years = years_pm_experience(roles_as_dicts, reference_date)

    decision = bands.decide(
        rubrics=rubrics,
        years=years,
        ownership=result.ownership,
        location_flag=location_flag,
        pm_scores=result.pm_criteria,
        spm_scores=result.spm_criteria,
        applied_role=applied_role,
    )

    decision["red_flags"] = [f.model_dump() for f in result.red_flags]
    decision["roles"] = roles_as_dicts
    decision["ownership"] = result.ownership.model_dump()
    decision["rubric_version"] = rubrics["version"]
    return decision
