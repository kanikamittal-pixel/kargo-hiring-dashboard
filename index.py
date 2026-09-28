from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

from flask import Flask, jsonify, request

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db import db  # noqa: E402
from emailing.queue import process_send_queue, send_now  # noqa: E402
from emailing.resend_client import SendError  # noqa: E402
from generation.emails import generate_invite_email, generate_rejection_email  # noqa: E402
from ingestion.parser import ParseError, parse_file  # noqa: E402
from ingestion.redact import compute_location_flag, extract_contact_info, redact_text  # noqa: E402
from scoring.pipeline import score_all_pending  # noqa: E402
from scoring.scorer import load_rubrics  # noqa: E402

# Vercel's native Flask integration builds this whole file into a single Vercel Function and
# invokes it with the real request path (unlike the older /api/*.py-as-individual-Lambda
# convention), so routes are registered with their real /api/... paths, matching what public/app.js
# actually calls. Vercel serves public/index.html, public/app.js, public/style.css straight from
# its CDN and only invokes this function for paths that don't match a static file.
app = Flask(__name__)

_db_initialized = False


def _ensure_db():
    global _db_initialized
    if not _db_initialized:
        db.init_db()
        _db_initialized = True


JSON_FIELDS = ("reason_codes", "red_flags", "interview_brief_probes")


def serialize_candidate(c: dict) -> dict:
    out = dict(c)
    for field in JSON_FIELDS:
        if out.get(field):
            try:
                out[field] = json.loads(out[field])
            except (TypeError, json.JSONDecodeError):
                out[field] = []
        else:
            out[field] = []
    out.pop("raw_text", None)
    return out


RAW_JSON_KEYS = ("criteria_json", "gates_json", "reason_codes_json")


def serialize_scores(scores: dict) -> dict:
    out = {}
    for role, s in scores.items():
        clean = {k: v for k, v in s.items() if k not in RAW_JSON_KEYS}
        out[role] = clean
    return out


@app.before_request
def _init():
    _ensure_db()


@app.errorhandler(Exception)
def handle_error(e):
    return jsonify({"error": str(e)}), 500


@app.route("/api/rubrics", methods=["GET"])
def get_rubrics():
    return jsonify(load_rubrics())


@app.route("/api/upload", methods=["POST"])
def upload():
    default_role = request.form.get("default_role", "PM")
    role_overrides = json.loads(request.form.get("role_overrides") or "{}")
    files = request.files.getlist("files")

    results = []
    for f in files:
        applied_role = role_overrides.get(f.filename) or default_role
        file_bytes = f.read()

        candidate_id = f"C-{uuid.uuid4().hex[:8]}"
        parse_status = "ok"
        raw_text = ""
        redacted = ""
        contact = {"name": None, "email": None, "phone": None, "linkedin": None, "city": None}
        location_flag = "unknown"
        is_duplicate_of = None

        try:
            raw_text = parse_file(f.filename, file_bytes)
            contact = extract_contact_info(raw_text)
            location_flag = compute_location_flag(contact.get("city"), raw_text)
            redacted = redact_text(raw_text, contact)

            existing = db.find_candidate_by_email(contact.get("email"))
            if existing:
                is_duplicate_of = existing["id"]
                parse_status = "duplicate"
        except ParseError as e:
            parse_status = "needs_manual_review"
            redacted = f"[PARSE FAILED: {e}]"

        db.insert_candidate({
            "id": candidate_id,
            "name": contact.get("name"),
            "email": contact.get("email"),
            "phone": contact.get("phone"),
            "linkedin": contact.get("linkedin"),
            "city": contact.get("city"),
            "location_flag": location_flag,
            "applied_role": applied_role,
            "source_file": f.filename,
            "raw_text": raw_text,
            "redacted_text": redacted,
            "parse_status": parse_status,
            "is_duplicate_of": is_duplicate_of,
            "created_at": db.now_iso(),
        })
        db.log_event(candidate_id, "uploaded", detail=f"file={f.filename}, role={applied_role}, status={parse_status}")
        results.append({"filename": f.filename, "candidate_id": candidate_id, "status": parse_status})

    return jsonify({"results": results})


@app.route("/api/candidates", methods=["GET"])
def list_candidates():
    role = request.args.get("role")
    candidates = db.list_candidates(role if role and role != "All" else None)
    return jsonify([serialize_candidate(c) for c in candidates])


@app.route("/api/candidates/<candidate_id>", methods=["GET"])
def get_candidate(candidate_id):
    c = db.get_candidate(candidate_id)
    if not c:
        return jsonify({"error": "not found"}), 404
    scores = db.get_scores(candidate_id)
    return jsonify({"candidate": serialize_candidate(c), "scores": serialize_scores(scores)})


@app.route("/api/score", methods=["POST"])
def score():
    results = score_all_pending()
    return jsonify({"results": results})


@app.route("/api/candidates/<candidate_id>/advance", methods=["POST"])
def advance(candidate_id):
    candidate = db.get_candidate(candidate_id)
    if not candidate:
        return jsonify({"error": "not found"}), 404
    rubrics = load_rubrics()
    scores = db.get_scores(candidate_id)
    score_row = scores[candidate["final_role"]]
    role_label = rubrics["roles"][candidate["final_role"]]["label"]

    email = generate_invite_email(candidate, score_row, role_label)
    db.save_email_draft(candidate_id, "invite", email["subject"], email["body"])
    db.set_decision_status(candidate_id, "advanced")
    db.log_event(candidate_id, "advanced", detail="invite email drafted")
    return jsonify({"status": "advanced"})


@app.route("/api/candidates/<candidate_id>/pass", methods=["POST"])
def pass_candidate(candidate_id):
    candidate = db.get_candidate(candidate_id)
    if not candidate:
        return jsonify({"error": "not found"}), 404
    rubrics = load_rubrics()
    role_label = rubrics["roles"][candidate["final_role"]]["label"]

    email = generate_rejection_email(candidate, role_label)
    db.save_email_draft(candidate_id, "rejection", email["subject"], email["body"])
    db.set_decision_status(candidate_id, "passed")
    db.log_event(candidate_id, "passed", detail="rejection email drafted")
    return jsonify({"status": "passed"})


@app.route("/api/candidates/<candidate_id>/email", methods=["PUT"])
def update_email(candidate_id):
    data = request.get_json(force=True)
    db.update_email_body(candidate_id, data["subject"], data["body"])
    return jsonify({"status": "saved"})


@app.route("/api/candidates/<candidate_id>/send", methods=["POST"])
def send(candidate_id):
    try:
        result = send_now(candidate_id)
        return jsonify(result)
    except SendError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/candidates/<candidate_id>/override", methods=["POST"])
def override(candidate_id):
    db.set_decision_status(candidate_id, "overridden", final_band="REVIEW")
    db.log_event(candidate_id, "overridden", detail="Moved from AUTO_REJECT to REVIEW")
    return jsonify({"status": "overridden"})


@app.route("/api/send-queue/process", methods=["POST"])
def process_queue():
    results = process_send_queue()
    return jsonify({"results": results})


@app.route("/api/decision-log", methods=["GET"])
def decision_log():
    events = db.list_decision_log()
    candidates_by_id = {c["id"]: c for c in db.list_candidates()}
    out = []
    for e in events:
        cand = candidates_by_id.get(e["candidate_id"]) or {}
        out.append({**e, "candidate_name": cand.get("name") or e["candidate_id"]})
    return jsonify(out)


# Local dev only: Vercel serves public/index.html, public/app.js, public/style.css from its own
# CDN and never routes those paths here, so these two routes are dead weight (harmless) in prod.
@app.route("/")
def _dev_index():
    return (PROJECT_ROOT / "public" / "index.html").read_text(), 200, {"Content-Type": "text/html"}


@app.route("/<path:filename>")
def _dev_static(filename):
    file_path = PROJECT_ROOT / "public" / filename
    if not file_path.is_file() or file_path.suffix not in (".js", ".css", ".html"):
        return jsonify({"error": "not found"}), 404
    content_type = {".js": "text/javascript", ".css": "text/css", ".html": "text/html"}[file_path.suffix]
    return file_path.read_text(), 200, {"Content-Type": content_type}


# Local dev entrypoint (`python index.py`). Vercel imports `app` directly and never runs this.
if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
    app.run(port=5001, debug=True)
