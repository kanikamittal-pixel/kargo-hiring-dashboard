from __future__ import annotations


def _field(obj, key):
    """Duck-types Pydantic models and plain dicts the same way, so tests can
    pass plain dicts instead of building full Pydantic objects."""
    return getattr(obj, key) if hasattr(obj, key) else obj[key]


def compute_criteria_points(rubrics: dict, role_key: str, criteria_scores: dict) -> tuple[float, list[dict]]:
    role_def = rubrics["roles"][role_key]
    per_criterion = []
    total = 0.0
    for crit in role_def["criteria"]:
        cid = crit["id"]
        result = criteria_scores[cid]
        score = _field(result, "score")
        matched_anchor = _field(result, "matched_anchor")
        evidence = _field(result, "evidence")
        rationale = _field(result, "rationale")
        points = round((score / 5) * crit["weight"], 2)
        total += points
        per_criterion.append(
            {
                "id": cid,
                "code": crit["code"],
                "name": crit["name"],
                "weight": crit["weight"],
                "matched_anchor": matched_anchor,
                "score": score,
                "points": points,
                "evidence": evidence,
                "rationale": rationale,
            }
        )
    return round(total, 2), per_criterion


def evaluate_gates(rubrics: dict, role_key: str, years: float, ownership, location_flag: str) -> dict:
    gates = {}

    if role_key == "pm":
        g1_passed = 1.5 <= years <= 5
        gates["G1"] = {"passed": g1_passed, "flag": None}

        g2_passed = _field(_field(ownership, "end_to_end_ownership"), "value")
        gates["G2"] = {"passed": g2_passed, "flag": None}

    else:  # spm
        if years > 8:
            gates["G1"] = {"passed": True, "flag": "above experience range"}
        else:
            g1_passed = 5 <= years <= 8
            gates["G1"] = {"passed": g1_passed, "flag": None}

        g2_passed = _field(_field(ownership, "no_senior_pm_layer"), "value")
        gates["G2"] = {"passed": g2_passed, "flag": None}

    if location_flag == "mumbai" or location_flag == "relocation_stated":
        gates["G3"] = {"passed": True, "flag": None}
    elif location_flag == "unknown":
        gates["G3"] = {"passed": True, "flag": "confirm relocation"}
    else:  # unwilling
        gates["G3"] = {"passed": False, "flag": None}

    return gates


def band_for_points(rubrics: dict, role_key: str, total_points: float) -> tuple[str, str | None]:
    for band in rubrics["roles"][role_key]["bands"]:
        if band["min"] <= total_points <= band["max"]:
            return band["label"], band.get("flag")
    return "AUTO_REJECT", None


def reason_codes_for(rubrics: dict, per_criterion: list[dict], failed_gate_ids: list[str]) -> list[str]:
    codes = list(failed_gate_ids)
    for crit in per_criterion:
        if crit["code"] and crit["score"] in (1, 2):
            if crit["code"] not in codes:
                codes.append(crit["code"])
    return codes


BAND_RANK = {"SHORTLIST": 0, "REVIEW": 1, "AUTO_REJECT": 2}
BETTER_FIT_MARGIN = 10  # points; only flag a same-band tie-break if the gap is this large


def _better_fit_note(scored_role: str, scored_view: dict, other_role: str, other_gates: dict, other_view: dict) -> str | None:
    """Only meaningful when the CURRENT applied role's gates already passed -- if they'd
    failed, re-routing already moved the candidate to whichever role is actually eligible."""
    if not all(g["passed"] for g in other_gates.values()):
        return None
    scored_rank = BAND_RANK.get(scored_view["band"], 2)
    other_rank = BAND_RANK.get(other_view["band"], 2)
    is_better_band = other_rank < scored_rank
    is_same_band_but_higher = other_rank == scored_rank and (other_view["total_points"] - scored_view["total_points"]) >= BETTER_FIT_MARGIN
    if is_better_band or is_same_band_but_higher:
        return (
            f"Scored higher as {other_role.upper()} ({other_view['total_points']} pts, {other_view['band']}) "
            f"than as {scored_role.upper()} ({scored_view['total_points']} pts, {scored_view['band']}) -- "
            f"consider evaluating for {other_role.upper()} instead."
        )
    return None


def _view_for(rubrics: dict, role_key: str, gates: dict, total: float, per_crit: list[dict]) -> dict:
    band_label, band_flag = band_for_points(rubrics, role_key, total)
    g1_flag = gates.get("G1", {}).get("flag")
    if g1_flag == "above experience range":
        band_label = "REVIEW"
        band_flag = "above experience range"
    return {
        "role": role_key,
        "total_points": total,
        "criteria": per_crit,
        "gates": gates,
        "band": band_label,
        "band_flag": band_flag,
        "reason_codes": reason_codes_for(rubrics, per_crit, []),
    }


def decide(rubrics: dict, years: float, ownership, location_flag: str, pm_scores: dict, spm_scores: dict, applied_role: str) -> dict:
    pm_gates = evaluate_gates(rubrics, "pm", years, ownership, location_flag)
    spm_gates = evaluate_gates(rubrics, "spm", years, ownership, location_flag)
    pm_total, pm_per_crit = compute_criteria_points(rubrics, "pm", pm_scores)
    spm_total, spm_per_crit = compute_criteria_points(rubrics, "spm", spm_scores)

    gates_by_role = {"pm": pm_gates, "spm": spm_gates}
    total_by_role = {"pm": pm_total, "spm": spm_total}
    per_crit_by_role = {"pm": pm_per_crit, "spm": spm_per_crit}

    def gates_pass(gates: dict) -> bool:
        return all(g["passed"] for g in gates.values())

    other_role = "spm" if applied_role == "pm" else "pm"
    applied_gates = gates_by_role[applied_role]
    other_gates = gates_by_role[other_role]
    failed_ids = [gid for gid, g in applied_gates.items() if not g["passed"]]

    if failed_ids:
        if gates_pass(other_gates):
            scored_role = other_role
            reroute_label = f"Re-routed {applied_role.upper()} -> {other_role.upper()}"
        else:
            reason_codes = reason_codes_for(rubrics, per_crit_by_role[applied_role], failed_ids)
            return {
                "applied_role": applied_role,
                "scored_role": applied_role,
                "reroute_label": None,
                "band": "AUTO_REJECT",
                "band_flag": None,
                "better_fit_note": None,
                "hold_hours": 48,
                "total_points": total_by_role[applied_role],
                "criteria": per_crit_by_role[applied_role],
                "gates": applied_gates,
                "reason_codes": reason_codes,
                "years_pm_experience": years,
                "other_role_view": _view_for(rubrics, other_role, other_gates, total_by_role[other_role], per_crit_by_role[other_role]),
            }
    else:
        scored_role = applied_role
        reroute_label = None

    scored_gates = gates_by_role[scored_role]
    total = total_by_role[scored_role]
    per_crit = per_crit_by_role[scored_role]

    scored_view = _view_for(rubrics, scored_role, scored_gates, total, per_crit)
    other_view = _view_for(rubrics, other_role, other_gates, total_by_role[other_role], per_crit_by_role[other_role])
    g3_flag = scored_gates.get("G3", {}).get("flag")

    better_fit_note = None
    if reroute_label is None:  # only meaningful when we didn't already re-route to the eligible role
        better_fit_note = _better_fit_note(scored_role, scored_view, other_role, other_gates, other_view)

    return {
        "applied_role": applied_role,
        "scored_role": scored_role,
        "reroute_label": reroute_label,
        "band": scored_view["band"],
        "band_flag": scored_view["band_flag"],
        "location_flag_note": g3_flag,
        "better_fit_note": better_fit_note,
        "hold_hours": 48 if scored_view["band"] == "AUTO_REJECT" else None,
        "total_points": total,
        "criteria": per_crit,
        "gates": scored_gates,
        "reason_codes": scored_view["reason_codes"],
        "years_pm_experience": years,
        "other_role_view": other_view,
    }
