import json
from pathlib import Path

import pytest

from scoring import bands

RUBRICS = json.loads((Path(__file__).resolve().parent.parent / "rubrics.json").read_text())


def crit(score, matched_anchor=None, evidence="some evidence here", rationale="r"):
    return {
        "score": score,
        "matched_anchor": matched_anchor or (1 if score == 1 else 3 if score in (2, 3) else 5),
        "evidence": evidence,
        "rationale": rationale,
    }


def full_criteria(scores: dict):
    return {cid: crit(scores.get(cid, 1)) for cid in ("A", "B", "C", "D", "E", "F")}


def ownership(end_to_end=True, no_senior_layer=True):
    return {
        "end_to_end_ownership": {"value": end_to_end, "evidence": "e"},
        "no_senior_pm_layer": {"value": no_senior_layer, "evidence": "e"},
    }


def test_vikram_pm_breakdown_matches_rubric_calibration():
    pm_scores = {"A": crit(1), "B": crit(3), "C": crit(3), "D": crit(3), "E": crit(4), "F": crit(3)}
    spm_scores = full_criteria({})  # irrelevant, SPM gate will fail on experience anyway

    result = bands.decide(
        rubrics=RUBRICS,
        years=2.9,
        ownership=ownership(end_to_end=True, no_senior_layer=False),
        location_flag="unknown",
        pm_scores=pm_scores,
        spm_scores=spm_scores,
        applied_role="pm",
    )

    assert result["scored_role"] == "pm"
    assert result["reroute_label"] is None
    assert result["total_points"] == 50
    assert result["band"] == "REVIEW"
    by_id = {c["id"]: c for c in result["criteria"]}
    assert by_id["A"]["points"] == 6
    assert by_id["B"]["points"] == 9
    assert by_id["C"]["points"] == 12
    assert by_id["D"]["points"] == 9
    assert by_id["E"]["points"] == 8
    assert by_id["F"]["points"] == 6


def test_spm_below_five_years_reroutes_to_pm():
    pm_scores = full_criteria({"A": 5, "B": 5, "C": 5, "D": 5, "E": 5, "F": 5})
    spm_scores = full_criteria({})

    result = bands.decide(
        rubrics=RUBRICS,
        years=2.0,
        ownership=ownership(end_to_end=True, no_senior_layer=True),
        location_flag="mumbai",
        pm_scores=pm_scores,
        spm_scores=spm_scores,
        applied_role="spm",
    )

    assert result["scored_role"] == "pm"
    assert result["reroute_label"] == "Re-routed SPM -> PM"
    assert result["band"] == "SHORTLIST"


def test_zero_pm_experience_auto_rejects_with_no_reroute():
    pm_scores = full_criteria({})
    spm_scores = full_criteria({})

    result = bands.decide(
        rubrics=RUBRICS,
        years=0.0,
        ownership=ownership(end_to_end=False, no_senior_layer=False),
        location_flag="mumbai",
        pm_scores=pm_scores,
        spm_scores=spm_scores,
        applied_role="pm",
    )

    assert result["band"] == "AUTO_REJECT"
    assert result["hold_hours"] == 48
    assert "G1" in result["reason_codes"]
    assert result["scored_role"] == "pm"


def test_spm_above_eight_years_forced_to_review_not_rejected():
    spm_scores = full_criteria({"A": 5, "B": 5, "C": 5, "D": 5, "E": 5, "F": 5})
    pm_scores = full_criteria({})

    result = bands.decide(
        rubrics=RUBRICS,
        years=10.0,
        ownership=ownership(end_to_end=True, no_senior_layer=True),
        location_flag="mumbai",
        pm_scores=pm_scores,
        spm_scores=spm_scores,
        applied_role="spm",
    )

    assert result["band"] == "REVIEW"
    assert result["band_flag"] == "above experience range"
    assert result["scored_role"] == "spm"


def test_unknown_location_never_rejects():
    pm_scores = full_criteria({"A": 5, "B": 5, "C": 5, "D": 5, "E": 5, "F": 5})
    spm_scores = full_criteria({})

    result = bands.decide(
        rubrics=RUBRICS,
        years=3.0,
        ownership=ownership(end_to_end=True, no_senior_layer=True),
        location_flag="unknown",
        pm_scores=pm_scores,
        spm_scores=spm_scores,
        applied_role="pm",
    )

    assert result["band"] == "SHORTLIST"
    assert result["location_flag_note"] == "confirm relocation"


def test_unwilling_to_relocate_fails_gate():
    pm_scores = full_criteria({"A": 5, "B": 5, "C": 5, "D": 5, "E": 5, "F": 5})
    spm_scores = full_criteria({})

    result = bands.decide(
        rubrics=RUBRICS,
        years=3.0,
        ownership=ownership(end_to_end=True, no_senior_layer=True),
        location_flag="unwilling",
        pm_scores=pm_scores,
        spm_scores=spm_scores,
        applied_role="pm",
    )

    assert result["band"] == "AUTO_REJECT"
    assert "G3" in result["reason_codes"]


def test_near_miss_buffer():
    # PM review_min is 40; 35-39 should be REVIEW flagged "near miss".
    pm_scores = {"A": crit(2), "B": crit(2), "C": crit(2), "D": crit(2), "E": crit(2), "F": crit(1)}
    spm_scores = full_criteria({})

    result = bands.decide(
        rubrics=RUBRICS,
        years=3.0,
        ownership=ownership(end_to_end=True, no_senior_layer=False),
        location_flag="mumbai",
        pm_scores=pm_scores,
        spm_scores=spm_scores,
        applied_role="pm",
    )

    assert 35 <= result["total_points"] <= 39
    assert result["band"] == "REVIEW"
    assert result["band_flag"] == "near miss"


def test_better_fit_note_when_other_role_scores_higher_band():
    # years=5.0 sits on the boundary shared by both gates (PM: 1.5-5, SPM: 5-8), so both
    # roles' gates pass -- no re-route is triggered, but SPM scores a clearly better band.
    pm_scores = {"A": crit(1), "B": crit(3), "C": crit(3), "D": crit(3), "E": crit(4), "F": crit(3)}  # 50 -> REVIEW
    spm_scores = full_criteria({"A": 5, "B": 5, "C": 5, "D": 5, "E": 5, "F": 5})  # 100 -> SHORTLIST

    result = bands.decide(
        rubrics=RUBRICS,
        years=5.0,
        ownership=ownership(end_to_end=True, no_senior_layer=True),
        location_flag="mumbai",
        pm_scores=pm_scores,
        spm_scores=spm_scores,
        applied_role="pm",
    )

    assert result["scored_role"] == "pm"
    assert result["reroute_label"] is None
    assert result["band"] == "REVIEW"
    assert result["better_fit_note"] is not None
    assert "SPM" in result["better_fit_note"]


def test_no_better_fit_note_when_other_role_gates_fail():
    pm_scores = {"A": crit(1), "B": crit(3), "C": crit(3), "D": crit(3), "E": crit(4), "F": crit(3)}
    spm_scores = full_criteria({"A": 5, "B": 5, "C": 5, "D": 5, "E": 5, "F": 5})

    result = bands.decide(
        rubrics=RUBRICS,
        years=2.9,  # fails SPM's 5-8y gate, so SPM isn't actually a viable alternative
        ownership=ownership(end_to_end=True, no_senior_layer=True),
        location_flag="mumbai",
        pm_scores=pm_scores,
        spm_scores=spm_scores,
        applied_role="pm",
    )

    assert result["scored_role"] == "pm"
    assert result["better_fit_note"] is None


def test_no_better_fit_note_when_margin_too_small():
    pm_scores = {"A": crit(1), "B": crit(3), "C": crit(3), "D": crit(3), "E": crit(4), "F": crit(3)}  # 50
    spm_scores = full_criteria({"A": 3, "B": 3, "C": 3, "D": 3, "E": 3, "F": 2})  # 58, same REVIEW band, <10pt gap

    result = bands.decide(
        rubrics=RUBRICS,
        years=5.0,
        ownership=ownership(end_to_end=True, no_senior_layer=True),
        location_flag="mumbai",
        pm_scores=pm_scores,
        spm_scores=spm_scores,
        applied_role="pm",
    )

    assert result["band"] == "REVIEW"
    assert result["other_role_view"]["band"] == "REVIEW"
    assert result["better_fit_note"] is None
