from __future__ import annotations

from db import db
from emailing.resend_client import SendError, send_email


def send_now(candidate_id: str) -> dict:
    """Manually triggered send for the Advance/Pass draft. Idempotent: no-ops if already sent."""
    candidate = db.get_candidate(candidate_id)
    if candidate.get("resend_message_id"):
        return {"status": "already_sent", "message_id": candidate["resend_message_id"]}
    if not candidate.get("email_body"):
        raise SendError("No email draft to send.")

    message_id = send_email(candidate, candidate["email_subject"], candidate["email_body"])
    decision_status = "invite_sent" if candidate["email_type"] == "invite" else "rejection_sent"
    db.mark_email_sent(candidate_id, message_id, decision_status)
    db.log_event(candidate_id, "email_sent", detail=f"type={candidate['email_type']} message_id={message_id}")
    return {"status": "sent", "message_id": message_id}


def process_send_queue() -> list[dict]:
    """Sends every auto-reject whose 48h hold has elapsed and that hasn't been sent or overridden.
    Safe to call repeatedly (e.g. on every app load): list_auto_rejects_due already excludes
    anything with a resend_message_id set."""
    results = []
    for candidate in db.list_auto_rejects_due():
        label = candidate.get("name") or candidate["id"]
        try:
            if not candidate.get("email_body"):
                results.append(
                    {"candidate_id": candidate["id"], "name": label, "status": "skipped", "detail": "no draft on file"}
                )
                continue
            message_id = send_email(candidate, candidate["email_subject"], candidate["email_body"])
            db.mark_email_sent(candidate["id"], message_id, "rejection_sent")
            db.log_event(
                candidate["id"], "email_sent",
                detail=f"type=rejection (auto, 48h hold) message_id={message_id}",
            )
            results.append({"candidate_id": candidate["id"], "name": label, "status": "sent", "detail": message_id})
        except SendError as e:
            db.log_event(candidate["id"], "email_send_failed", detail=str(e))
            results.append({"candidate_id": candidate["id"], "name": label, "status": "failed", "detail": str(e)})
    return results
