import uuid
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from db import db
from ingestion.parser import ParseError, parse_file
from ingestion.redact import compute_location_flag, extract_contact_info, redact_text
from emailing.queue import process_send_queue
from scoring.pipeline import score_all_pending
from scoring.scorer import load_rubrics
from ui.cards import render_auto_reject_log, render_band_tab, render_decision_log, render_summary_bar

load_dotenv(Path(__file__).resolve().parent / ".env")

UPLOAD_DIR = Path(__file__).resolve().parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

db.init_db()

if "send_queue_checked" not in st.session_state:
    st.session_state["send_queue_checked"] = True
    process_send_queue()

st.set_page_config(page_title="Kargo Hiring Dashboard", layout="wide")
st.title("Kargo Hiring Dashboard")

(
    tab_upload,
    tab_score,
    tab_shortlist,
    tab_review,
    tab_auto_reject,
    tab_decision_log,
    tab_candidates,
) = st.tabs(
    ["Upload", "Score", "Shortlist", "Review", "Auto-Reject Log", "Decision Log", "All Candidates"]
)

with tab_upload:
    st.subheader("Bulk upload CVs")
    default_role = st.selectbox("Default applied role for this batch", ["PM", "SPM"])
    uploaded_files = st.file_uploader(
        "Upload CVs (PDF or DOCX)", type=["pdf", "docx"], accept_multiple_files=True
    )

    role_overrides = {}
    if uploaded_files:
        st.write("Per-file role override (optional):")
        for f in uploaded_files:
            role_overrides[f.name] = st.selectbox(
                f"{f.name}", ["(use default)", "PM", "SPM"], key=f"role_{f.name}"
            )

    if uploaded_files and st.button("Process batch"):
        results = []
        for f in uploaded_files:
            applied_role = role_overrides.get(f.name, "(use default)")
            if applied_role == "(use default)":
                applied_role = default_role

            dest_path = UPLOAD_DIR / f.name
            dest_path.write_bytes(f.getvalue())

            candidate_id = f"C-{uuid.uuid4().hex[:8]}"
            parse_status = "ok"
            raw_text = ""
            redacted = ""
            contact = {"name": None, "email": None, "phone": None, "linkedin": None, "city": None}
            location_flag = "unknown"
            is_duplicate_of = None

            try:
                raw_text = parse_file(dest_path)
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

            db.insert_candidate(
                {
                    "id": candidate_id,
                    "name": contact.get("name"),
                    "email": contact.get("email"),
                    "phone": contact.get("phone"),
                    "linkedin": contact.get("linkedin"),
                    "city": contact.get("city"),
                    "location_flag": location_flag,
                    "applied_role": applied_role,
                    "source_file": f.name,
                    "raw_text": raw_text,
                    "redacted_text": redacted,
                    "parse_status": parse_status,
                    "is_duplicate_of": is_duplicate_of,
                    "created_at": db.now_iso(),
                }
            )
            db.log_event(candidate_id, "uploaded", detail=f"file={f.name}, role={applied_role}, status={parse_status}")
            results.append((f.name, parse_status))

        st.success(f"Processed {len(results)} files.")
        for name, status in results:
            st.write(f"- {name}: **{status}**")

with tab_candidates:
    st.subheader("Candidates")
    role_filter = st.selectbox("Filter by role", ["All", "PM", "SPM"], key="filter_role")
    candidates = db.list_candidates(None if role_filter == "All" else role_filter)

    if not candidates:
        st.info("No candidates uploaded yet.")
    else:
        for c in candidates:
            with st.expander(f"{c['id']} — {c.get('name') or '(name not detected)'} — {c['applied_role']} — {c['parse_status']}"):
                col1, col2 = st.columns(2)
                with col1:
                    st.write("**Extracted fields**")
                    st.json({
                        "email": c.get("email"),
                        "phone": c.get("phone"),
                        "linkedin": c.get("linkedin"),
                        "city": c.get("city"),
                        "location_flag": c.get("location_flag"),
                        "source_file": c.get("source_file"),
                        "is_duplicate_of": c.get("is_duplicate_of"),
                    })
                with col2:
                    st.write("**Redacted text sent to the LLM (preview)**")
                    st.text_area(
                        "redacted_text", c.get("redacted_text") or "", height=300,
                        key=f"redacted_{c['id']}", label_visibility="collapsed"
                    )

with tab_score:
    st.subheader("Score pending candidates")
    pending = db.list_candidates_needing_scoring()
    st.write(f"{len(pending)} candidate(s) awaiting scoring.")
    if st.button("Score all pending candidates", disabled=not pending):
        with st.spinner(f"Scoring {len(pending)} candidate(s)... this calls the LLM once per candidate."):
            results = score_all_pending()
        st.success(f"Scored {len(results)} candidate(s).")
        for r in results:
            icon = "✅" if r["status"] == "scored" else "⚠️"
            st.write(f"{icon} {r['name']}: {r['status']} -- {r['detail']}")
        st.rerun()

    needs_review = [c for c in db.list_candidates() if c.get("score_status") == "needs_manual_review"]
    if needs_review:
        st.warning(f"{len(needs_review)} candidate(s) need manual review (LLM output failed validation twice).")
        for c in needs_review:
            st.write(f"- {c.get('name') or c['id']} ({c['applied_role']})")

rubrics = load_rubrics()
all_candidates = db.list_candidates()

with tab_shortlist:
    render_summary_bar(all_candidates, "pm", "PM")
    render_summary_bar(all_candidates, "spm", "SPM")
    st.divider()
    render_band_tab(all_candidates, rubrics, "SHORTLIST")

with tab_review:
    render_summary_bar(all_candidates, "pm", "PM")
    render_summary_bar(all_candidates, "spm", "SPM")
    st.divider()
    render_band_tab(all_candidates, rubrics, "REVIEW")

with tab_auto_reject:
    st.subheader("Auto-reject log")
    render_auto_reject_log(all_candidates)

with tab_decision_log:
    st.subheader("Decision log")
    render_decision_log()
