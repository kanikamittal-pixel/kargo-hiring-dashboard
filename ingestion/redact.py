from __future__ import annotations

import re

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(\+?\d[\d\-\s]{8,}\d)")
LINKEDIN_RE = re.compile(r"linkedin\.com/\S+", re.IGNORECASE)

MUMBAI_ALIASES = {"mumbai", "bombay"}

KNOWN_CITIES = [
    "mumbai", "bombay", "bengaluru", "bangalore", "delhi", "new delhi",
    "gurugram", "gurgaon", "noida", "pune", "hyderabad", "chennai",
    "kolkata", "ahmedabad", "jaipur", "chandigarh", "kochi", "cochin",
]

RELOCATION_STATED_RE = re.compile(
    r"(willing to relocate|open to relocat|can relocate|relocating to mumbai|"
    r"happy to relocate|able to relocate)",
    re.IGNORECASE,
)
RELOCATION_UNWILLING_RE = re.compile(
    r"(not willing to relocate|unable to relocate|not open to relocat|"
    r"cannot relocate|unwilling to relocate|will not relocate)",
    re.IGNORECASE,
)

SECTION_STRIP_RE = re.compile(
    r"\n\s*(EDUCATION|CERTIFICATIONS?(?:\s*&\s*(?:SKILLS|TOOLS|OTHER))?)\b.*?"
    r"(?=\n\s*[A-Z][A-Z &/]{3,}\s*(?:\n|$)|\Z)",
    re.IGNORECASE | re.DOTALL,
)


def extract_contact_info(text: str) -> dict:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    email_match = EMAIL_RE.search(text)
    email = email_match.group(0) if email_match else None

    phone_match = PHONE_RE.search(text)
    phone = phone_match.group(0).strip() if phone_match else None

    linkedin_match = LINKEDIN_RE.search(text)
    linkedin = linkedin_match.group(0) if linkedin_match else None

    name = None
    if lines:
        candidate_line = lines[0]
        if "@" not in candidate_line and not any(ch.isdigit() for ch in candidate_line):
            name = candidate_line

    city = None
    head_text = "\n".join(lines[:5]).lower()
    for c in KNOWN_CITIES:
        if c in head_text:
            city = c
            break

    return {
        "name": name,
        "email": email,
        "phone": phone,
        "linkedin": linkedin,
        "city": city,
    }


def compute_location_flag(city: str | None, full_text: str) -> str:
    if city and city.lower() in MUMBAI_ALIASES:
        return "mumbai"
    if RELOCATION_STATED_RE.search(full_text):
        return "relocation_stated"
    if RELOCATION_UNWILLING_RE.search(full_text):
        return "unwilling"
    return "unknown"


def redact_text(text: str, contact: dict) -> str:
    redacted = SECTION_STRIP_RE.sub("\n[REDACTED-SECTION: education/certifications]\n", text)
    redacted = EMAIL_RE.sub("[REDACTED-EMAIL]", redacted)
    redacted = LINKEDIN_RE.sub("[REDACTED-LINKEDIN]", redacted)
    redacted = PHONE_RE.sub("[REDACTED-PHONE]", redacted)

    if contact.get("name"):
        name = contact["name"]
        redacted = re.sub(re.escape(name), "[CANDIDATE]", redacted, flags=re.IGNORECASE)
        for part in name.split():
            if len(part) > 2:
                redacted = re.sub(
                    rf"\b{re.escape(part)}\b", "[CANDIDATE]", redacted, flags=re.IGNORECASE
                )

    if contact.get("city"):
        redacted = re.sub(
            rf"\b{re.escape(contact['city'])}\b", "[REDACTED-LOCATION]", redacted, flags=re.IGNORECASE
        )

    return redacted
