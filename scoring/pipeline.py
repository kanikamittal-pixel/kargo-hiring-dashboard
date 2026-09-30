from __future__ import annotations

import json
from datetime import date

from db import db
from generation.briefs import generate_interview_brief
from generation.emails import generate_rejection_email
from scoring.scorer import NeedsManualReview, load_rubrics, score_candidate


def score_all_pending() -> list[dict]:
    """Scores every candidate with score_status='not_scored'. Returns a list of
    {candidate_id, name, status, detail} so the caller can show a results log.
    Used by the manual "Retry scoring" fallback button, not the primary upload flow --
    each candidate here still does scoring + brief/email-draft generation in one call,
    which is why the primary flow instead calls score_only() and generate_followup()
    as two separate requests (see index.py)."""
    rubrics = load_rubrics()
    results = []
    for candidate in db.list_candidates_needing_scoring():
        result = score_only(candidate, rubrics)
        if result["status"] == "scored":
            generate_followup(candidate["id"], rubrics)
        results.append(result)
    return results


def score_candidates(candidate_ids: list[str]) -> list[dict]:
    """Scores a specific set of candidates (e.g. a just-uploaded batch), skipping any that
    are already scored."""
    rubrics = load_rubrics()
    results = []
    for candidate_id in candidate_ids:
        candidate = db.get_candidate(candidate_id)
        if not candidate or candidate["score_status"] != "not_scored":
            continue
        result = score_only(candidate, rubrics)
        if result["status"] == "scored":
            generate_followup(candidate_id, rubrics)
        results.append(result)
    return results


def score_only(candidate: dict, rubrics: dict) -> dict:
    """Scoring only -- one LLM call. Split out from brief/email-draft generation (a second,
    separate LLM call) so each stays comfortably inside Vercel's per-function time limit;
    combining both in one request risked the second call getting silently killed mid-flight
    with no error logged, after scoring itself had already succeeded and been saved."""
    label = candidate.get("name") or candidate["id"]
    try:
        decision = score_candidate(
            redacted_text=candidate["redacted_text"],
            location_flag=candidate["location_flag"] or "unknown",
            applied_role=candidate["applied_role"],
            reference_date=date.today(),
        )
        db.apply_scoring_decision(candidate["id"], decision, rubrics["version"])

        detail = f"scored_role={decision['scored_role']} band={decision['band']} total={decision['total_points']}"
        if decision.get("role_was_auto_detected"):
            detail += " (role auto-detected from experience)"
        if decision.get("reroute_label"):
            detail += f" ({decision['reroute_label']})"
        db.log_event(candidate["id"], "scored", detail=detail, rubric_version=rubrics["version"])

        if decision["band"] == "AUTO_REJECT":
            db.log_event(candidate["id"], "banded", detail="AUTO_REJECT, 48h hold queued")

        return {"candidate_id": candidate["id"], "name": label, "status": "scored", "detail": detail}
    except NeedsManualReview as e:
        db.mark_needs_manual_review(candidate["id"])
        db.log_event(candidate["id"], "needs_manual_review", detail=str(e))
        return {"candidate_id": candidate["id"], "name": label, "status": "needs_manual_review", "detail": str(e)}
    except Exception as e:
        # An unexpected failure (e.g. the LLM API unavailable, or a request timeout on the way)
        # for one CV must not stop the rest of the batch -- isolate it and keep going.
        db.mark_needs_manual_review(candidate["id"])
        detail = f"Unexpected error during scoring: {e}"
        db.log_event(candidate["id"], "needs_manual_review", detail=detail)
        return {"candidate_id": candidate["id"], "name": label, "status": "needs_manual_review", "detail": detail}


def generate_followup(candidate_id: str, rubrics: dict | None = None) -> dict:
    """Generates whatever the candidate's band calls for: an interview brief (Shortlist/
    Review) or an auto-reject rejection draft (Auto-reject). Safe to call more than once --
    skips if already generated, so a retry after a partial failure never double-generates."""
    rubrics = rubrics or load_rubrics()
    candidate = db.get_candidate(candidate_id)
    if not candidate or candidate.get("score_status") != "scored":
        return {"candidate_id": candidate_id, "status": "not_ready"}

    band = candidate.get("final_band")
    if band == "AUTO_REJECT":
        if candidate.get("email_body"):
            return {"candidate_id": candidate_id, "status": "already_generated"}
        _draft_rejection_for_auto_reject(candidate_id, rubrics)
        return {"candidate_id": candidate_id, "status": "email_drafted"}
    if band in ("SHORTLIST", "REVIEW"):
        if candidate.get("interview_brief_why"):
            return {"candidate_id": candidate_id, "status": "already_generated"}
        _generate_brief(candidate_id, rubrics)
        return {"candidate_id": candidate_id, "status": "brief_generated"}
    return {"candidate_id": candidate_id, "status": "nothing_to_generate"}


def _generate_brief(candidate_id: str, rubrics: dict):
    """Auto-generates the interview brief for a newly-Shortlisted/Reviewed candidate.
    A failure here must not undo the scoring result -- just leave the brief blank for now."""
    try:
        candidate = db.get_candidate(candidate_id)
        score = db.get_scores(candidate_id)[candidate["final_role"]]
        red_flags = json.loads(candidate.get("red_flags") or "[]")
        brief = generate_interview_brief(score, red_flags, rubrics)
        db.save_interview_brief(candidate_id, brief)
        db.log_event(candidate_id, "brief_generated")
    except Exception as e:
        db.log_event(candidate_id, "brief_generation_failed", detail=str(e))


def _draft_rejection_for_auto_reject(candidate_id: str, rubrics: dict):
    """Auto-drafts the rejection email for an auto-rejected candidate so it's ready to send
    unattended after the 48h hold (Milestone 5). Arjun can still edit or override before it sends."""
    try:
        candidate = db.get_candidate(candidate_id)
        role_label = rubrics["roles"][candidate["final_role"]]["label"]
        email = generate_rejection_email(candidate, role_label)
        db.save_email_draft(candidate_id, "rejection", email["subject"], email["body"])
        detail = "auto-drafted for 48h hold"
        if email.get("needs_manual_review"):
            detail += " -- WARNING: draft may reference evaluation mechanics, review before send"
        db.log_event(candidate_id, "email_drafted", detail=detail)
    except Exception as e:
        db.log_event(candidate_id, "email_draft_failed", detail=str(e))
