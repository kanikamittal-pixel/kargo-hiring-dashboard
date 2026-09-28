from __future__ import annotations

import json
from datetime import date

from db import db
from generation.briefs import generate_interview_brief
from generation.emails import generate_rejection_email
from scoring.scorer import NeedsManualReview, load_rubrics, score_candidate


def score_all_pending() -> list[dict]:
    """Scores every candidate with score_status='not_scored'. Returns a list of
    {candidate_id, name, status, detail} so the caller can show a results log."""
    rubrics = load_rubrics()
    results = []

    for candidate in db.list_candidates_needing_scoring():
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
            if decision.get("reroute_label"):
                detail += f" ({decision['reroute_label']})"
            db.log_event(candidate["id"], "scored", detail=detail, rubric_version=rubrics["version"])

            if decision["band"] == "AUTO_REJECT":
                db.log_event(candidate["id"], "banded", detail="AUTO_REJECT, 48h hold queued")
                _draft_rejection_for_auto_reject(candidate["id"], rubrics)
            elif decision["band"] in ("SHORTLIST", "REVIEW"):
                _generate_brief(candidate["id"], rubrics)

            results.append({"candidate_id": candidate["id"], "name": label, "status": "scored", "detail": detail})
        except NeedsManualReview as e:
            db.mark_needs_manual_review(candidate["id"])
            db.log_event(candidate["id"], "needs_manual_review", detail=str(e))
            results.append(
                {"candidate_id": candidate["id"], "name": label, "status": "needs_manual_review", "detail": str(e)}
            )
        except Exception as e:
            # An unexpected failure (e.g. the LLM API unavailable) for one CV must not stop the
            # rest of the batch -- isolate it as needs_manual_review and keep going.
            db.mark_needs_manual_review(candidate["id"])
            detail = f"Unexpected error during scoring: {e}"
            db.log_event(candidate["id"], "needs_manual_review", detail=detail)
            results.append({"candidate_id": candidate["id"], "name": label, "status": "needs_manual_review", "detail": detail})

    return results


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
