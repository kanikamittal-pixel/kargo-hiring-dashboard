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

SECTION_HEADER_WORDS = {
    "summary", "profile", "objective", "experience", "education", "skills",
    "projects", "certifications", "contact", "about", "resume", "curriculum vitae", "cv",
    "work experience", "professional summary", "career objective",
}

# 2-4 capitalized-ish words (allows initials, hyphens, apostrophes: "J. R. Rao", "Anne-Marie O'Brien")
NAME_LINE_RE = re.compile(r"^[A-Za-z][A-Za-z.'\-]*(?:\s+[A-Za-z][A-Za-z.'\-]*){1,3}$")


def _collapse_adjacent_duplicate_letters(s: str) -> str:
    out = []
    for ch in s:
        if out and out[-1].lower() == ch.lower():
            continue
        out.append(ch)
    return "".join(out)


def _word_looks_corrupted(word: str) -> bool:
    letters = [c for c in word if c.isalpha()]
    if len(letters) < 4:
        return False
    # Signal 1: doubled letters (both copies same case) collapse a lot under dedup.
    collapsed = _collapse_adjacent_duplicate_letters("".join(letters))
    if len(collapsed) <= len(letters) * 0.65:
        return True
    # Signal 2: interleaved-but-mismatched-case doubling doesn't collapse as cleanly,
    # but leaves far more capitals scattered through the word than a real name ever
    # would -- a normal word has at most its first letter capitalized (plus rare cases
    # like "McKinsey" or "O'Brien" with one extra), OR is written fully in caps as a
    # deliberate style ("RAHUL BOSE") -- exempt that case, since it's uniform, not
    # scattered. A high interior-capital ratio in a mixed-case word is the same
    # underlying artifact showing up differently.
    if "".join(letters).isupper():
        return False
    interior = letters[1:]
    if not interior:
        return False
    interior_upper_ratio = sum(1 for c in interior if c.isupper()) / len(interior)
    return interior_upper_ratio > 0.3


def _looks_corrupted(line: str) -> bool:
    """Detects a specific PDF text-extraction artifact: some resume templates fake a
    bold/styled header by printing it twice at near-identical coordinates, which naive
    extraction interleaves character-by-character into garbage, e.g. 'RROohHaAnN' for
    'Rohan'. Checked per word since the two overlapping text layers don't always
    produce the same corruption pattern in every word of the line."""
    return any(_word_looks_corrupted(w) for w in line.split())


def _looks_like_name(line: str) -> bool:
    line = line.strip()
    if not (3 <= len(line) <= 50):
        return False
    if "@" in line or any(ch.isdigit() for ch in line):
        return False
    lowered = line.lower()
    if lowered in SECTION_HEADER_WORDS or "http" in lowered or "linkedin.com" in lowered or "github.com" in lowered:
        return False
    if not NAME_LINE_RE.match(line):
        return False
    return not _looks_corrupted(line)


def _extract_name(lines: list[str], full_text: str) -> str | None:
    for line in lines[:6]:
        if _looks_like_name(line):
            return line.strip()

    # Fallback: name glued directly onto the next line's contact details with no separator
    # in between -- a known PDF/DOCX text-extraction artifact (e.g. "Lavanya Iyerlavanya.iyer@x.com").
    email_match = EMAIL_RE.search(full_text)
    if email_match:
        prefix_lines = full_text[: email_match.start()].strip().splitlines()
        if prefix_lines:
            candidate = prefix_lines[-1].strip()
            words = candidate.split()
            if (
                1 <= len(words) <= 4
                and not any(ch.isdigit() for ch in candidate)
                and all(w[0].isupper() for w in words)
                and not _looks_corrupted(candidate)
            ):
                return candidate

    # Last resort: the original bare heuristic -- still better than leaving it blank.
    if (
        lines
        and "@" not in lines[0]
        and not any(ch.isdigit() for ch in lines[0])
        and len(lines[0]) < 60
        and not _looks_corrupted(lines[0])
    ):
        return lines[0]
    return None


NAME_STOPWORDS = {"resume", "cv", "curriculum", "vitae", "final", "updated", "latest", "copy"}


def _name_from_filename(filename: str) -> str | None:
    """Last-resort fallback when the document body has no usable name (e.g. the header
    extracted corrupted -- see _looks_corrupted). Many resumes are literally named
    "firstname_lastname.pdf", which sidesteps whatever went wrong in the PDF/DOCX body."""
    stem = filename.rsplit(".", 1)[0]
    stem = re.sub(r"^\d+[_\-\s]*", "", stem)  # drop leading numbering, e.g. "01_"
    words = [w for w in re.split(r"[_\-\s]+", stem) if w]
    words = [w for w in words if w.lower() not in NAME_STOPWORDS]
    if not (2 <= len(words) <= 4):
        return None
    if any(any(ch.isdigit() for ch in w) for w in words):
        return None
    candidate = " ".join(w.capitalize() for w in words)
    return candidate if not _looks_corrupted(candidate) else None


def extract_contact_info(text: str, filename: str | None = None) -> dict:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    email_match = EMAIL_RE.search(text)
    email = email_match.group(0) if email_match else None

    phone_match = PHONE_RE.search(text)
    phone = phone_match.group(0).strip() if phone_match else None

    linkedin_match = LINKEDIN_RE.search(text)
    linkedin = linkedin_match.group(0) if linkedin_match else None

    name = _extract_name(lines, text)
    if not name and filename:
        name = _name_from_filename(filename)

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
