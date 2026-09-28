from __future__ import annotations

import os

import resend


class SendError(Exception):
    pass


def _is_test_mode() -> bool:
    return os.environ.get("TEST_MODE", "true").strip().lower() == "true"


def send_email(candidate: dict, subject: str, body: str) -> str:
    """Sends via Resend and returns the message id. In TEST_MODE, every email is routed
    to TEST_RECIPIENT with the intended recipient prefixed into the subject, since Resend's
    shared test domain only delivers to the account's own verified email."""
    to_email = candidate.get("email")
    if not to_email:
        raise SendError(f"Candidate {candidate.get('id')} has no email on file.")

    resend.api_key = os.environ["RESEND_API_KEY"]

    if _is_test_mode():
        test_recipient = os.environ["TEST_RECIPIENT"]
        subject = f"[TEST -- would send to {to_email}] {subject}"
        to_email = test_recipient

    params = {
        "from": os.environ["RESEND_FROM"],
        "to": [to_email],
        "subject": subject,
        "text": body,
    }
    try:
        result = resend.Emails.send(params)
    except Exception as e:
        raise SendError(f"Resend send failed: {e}") from e

    message_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", None)
    if not message_id:
        raise SendError(f"Resend response had no message id: {result}")
    return message_id
