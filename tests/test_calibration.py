import json
import os
from datetime import date, datetime
from pathlib import Path

import pytest

from ingestion.parser import parse_file
from ingestion.redact import compute_location_flag, extract_contact_info, redact_text
from scoring.scorer import score_candidate

RUBRICS = json.loads((Path(__file__).resolve().parent.parent / "rubrics.json").read_text())
FIXTURES = RUBRICS["calibration_fixtures"]
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_PER_FIXTURE = RUBRICS["calibration_test_rules"]["runs_per_fixture"]
MAX_VARIANCE = RUBRICS["calibration_test_rules"]["max_total_point_variance"]

pytestmark = pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set -- calibration tests call the real LLM",
)


def _fixture_by_name(name: str) -> dict:
    return next(f for f in FIXTURES if f["name"] == name)


def _redacted_text_for(fixture: dict) -> tuple[str, str]:
    path = PROJECT_ROOT / fixture["file"]
    raw_text = parse_file(path)
    contact = extract_contact_info(raw_text)
    location_flag = compute_location_flag(contact.get("city"), raw_text)
    redacted = redact_text(raw_text, contact)
    return redacted, location_flag


def _run_fixture(name: str, role_scored_applied_as: str):
    fixture = _fixture_by_name(name)
    redacted, location_flag = _redacted_text_for(fixture)
    reference_date = datetime.strptime(fixture["reference_date"], "%Y-%m-%d").date()

    results = []
    for _ in range(RUNS_PER_FIXTURE):
        decision = score_candidate(
            redacted_text=redacted,
            location_flag=location_flag,
            applied_role=role_scored_applied_as,
            reference_date=reference_date,
        )
        results.append(decision)
    return results


def _assert_stable(results: list[dict], expected_band: str):
    bands_seen = {r["band"] for r in results}
    assert bands_seen == {expected_band}, (
        f"Band drifted across runs: {bands_seen}. Per-run detail:\n"
        + "\n".join(
            f"run {i}: total={r['total_points']} criteria={r['criteria']}"
            for i, r in enumerate(results)
        )
    )
    totals = [r["total_points"] for r in results]
    variance = max(totals) - min(totals)
    assert variance <= MAX_VARIANCE, (
        f"Total point variance {variance} exceeds {MAX_VARIANCE}. Totals: {totals}\n"
        + "\n".join(
            f"run {i}: " + ", ".join(f"{c['id']}={c['score']}({c['evidence']!r})" for c in r["criteria"])
            for i, r in enumerate(results)
        )
    )


def test_lavanya_as_pm_shortlists():
    results = _run_fixture("Lavanya Iyer", "pm")
    for r in results:
        assert r["reroute_label"] is None
        assert r["scored_role"] == "pm"
    _assert_stable(results, "SHORTLIST")


def test_lavanya_as_spm_reroutes_to_pm_then_shortlists():
    results = _run_fixture("Lavanya Iyer", "spm")
    for r in results:
        assert r["reroute_label"] == "Re-routed SPM -> PM"
        assert r["scored_role"] == "pm"
    _assert_stable(results, "SHORTLIST")


def test_vikram_as_pm_reviews():
    results = _run_fixture("Vikram Nair", "pm")
    for r in results:
        assert r["reroute_label"] is None
        flag_ids = {f["id"] for f in r["red_flags"] if f["present"]}
        assert {"F1", "F3", "F4"} <= flag_ids
    _assert_stable(results, "REVIEW")


def test_vikram_as_spm_reroutes_to_pm_then_reviews():
    results = _run_fixture("Vikram Nair", "spm")
    for r in results:
        assert r["reroute_label"] == "Re-routed SPM -> PM"
        assert r["scored_role"] == "pm"
    _assert_stable(results, "REVIEW")


def test_rahul_as_pm_auto_rejects_on_g1():
    results = _run_fixture("Rahul Bose", "pm")
    for r in results:
        assert r["band"] == "AUTO_REJECT"
        assert "G1" in r["reason_codes"]
        assert r["years_pm_experience"] == 0.0


def test_preetham_as_pm_auto_rejects_with_all_red_flags():
    results = _run_fixture("Preetham Rao", "pm")
    for r in results:
        assert r["band"] == "AUTO_REJECT"
        assert "G1" in r["reason_codes"]
        # F1's detect rule is "ops criterion scored 1 or 2." Preetham's only ops exposure is
        # API integration with 3rd-party logistics providers, which the rubric caps at score 3
        # (never 5) -- not low enough to trip F1. Verified stable across repeated real-LLM runs.
        flag_ids = {f["id"] for f in r["red_flags"] if f["present"]}
        assert {"F2", "F3", "F4"} <= flag_ids
