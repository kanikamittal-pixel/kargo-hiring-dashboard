from __future__ import annotations

from scoring.llm_client import generate_text

SIGNATURE = "\n\nBest,\nArjun Mehta\nFounder, Kargo"

BANNED_TERMS = (
    "score", "scored", "criteria", "criterion", "rubric", "red flag",
    "reason code", "gate", "weight", "points", "band", "shortlist", "auto-reject",
)


def _first_name(candidate: dict) -> str:
    name = (candidate.get("name") or "").strip()
    return name.split()[0] if name else "there"


def _contains_banned_term(text: str) -> str | None:
    lowered = text.lower()
    for term in BANNED_TERMS:
        if term in lowered:
            return term
    return None


def generate_invite_email(candidate: dict, score: dict, role_label: str) -> dict:
    first_name = _first_name(candidate)
    top_evidence = "\n".join(
        f"- {c['name']}: \"{c['evidence']}\""
        for c in sorted(score["criteria"], key=lambda c: -c["score"])[:3]
        if c["evidence"] and c["evidence"].lower() != "none found"
    ) or "No specific evidence available -- keep the email general but still warm."

    prompt = f"""Write a warm, concise email body (no greeting, no sign-off, no subject line) from a
hiring manager at Kargo inviting a candidate to interview for the {role_label} role.

Requirements:
- Mention ONE specific, real detail from their background below -- do not invent anything not listed.
- Ask them to reply with 3 time slots for a 45-minute call.
- Warm but professional tone. Under 150 words.

Real background details to draw from (pick the single most compelling one):
{top_evidence}

Respond with ONLY the email body paragraphs as plain text."""

    body_text = generate_text(prompt, temperature=0.5)
    full_body = f"Hi {first_name},\n\n{body_text}{SIGNATURE}"
    subject = f"Interview invitation -- {role_label} at Kargo"
    return {"subject": subject, "body": full_body}


def generate_rejection_email(candidate: dict, role_label: str) -> dict:
    first_name = _first_name(candidate)

    prompt = f"""Write a respectful, brief rejection email body (no greeting, no sign-off, no subject line)
from a hiring manager at Kargo to a candidate who applied for the {role_label} role.

Requirements:
- 4-5 sentences total.
- Thank them for their time and interest in Kargo.
- Do NOT mention scores, evaluation criteria, rubrics, reasons, red flags, or any specific weakness or gap.
  Keep it generic, kind, and free of any evaluation language.

Respond with ONLY the email body paragraphs as plain text."""

    body_text = generate_text(prompt, temperature=0.5)
    banned = _contains_banned_term(body_text)
    if banned:
        retry_prompt = prompt + (
            f"\n\nYour previous draft included the word '{banned}', which reveals evaluation "
            "mechanics to the candidate. Rewrite it without any reference to scoring, evaluation, "
            "or specific weaknesses -- keep it purely a warm, generic thank-you and rejection."
        )
        body_text = generate_text(retry_prompt, temperature=0.5)
        banned = _contains_banned_term(body_text)

    full_body = f"Hi {first_name},\n\n{body_text}{SIGNATURE}"
    subject = "Your application to Kargo"
    return {"subject": subject, "body": full_body, "needs_manual_review": bool(banned)}
