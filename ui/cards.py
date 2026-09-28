from __future__ import annotations

import json
from collections import Counter

import streamlit as st

from db import db
from emailing.queue import process_send_queue, send_now
from emailing.resend_client import SendError
from generation.briefs import generate_interview_brief
from generation.emails import generate_invite_email, generate_rejection_email

BAND_ORDER = {"SHORTLIST": 0, "REVIEW": 1, "AUTO_REJECT": 2}


def compute_summary(candidates: list[dict], role_key: str) -> dict:
    in_role = [c for c in candidates if c.get("final_role") == role_key]
    needs_review = [
        c for c in candidates
        if c.get("score_status") == "needs_manual_review" and c.get("applied_role", "").lower() == role_key
    ]

    reason_counter = Counter()
    flag_counter = Counter()
    for c in in_role:
        for code in json.loads(c.get("reason_codes") or "[]"):
            reason_counter[code] += 1
        for flag in json.loads(c.get("red_flags") or "[]"):
            if flag.get("present"):
                flag_counter[flag["id"]] += 1

    return {
        "shortlist": sum(1 for c in in_role if c["final_band"] == "SHORTLIST"),
        "review": sum(1 for c in in_role if c["final_band"] == "REVIEW"),
        "auto_reject": sum(1 for c in in_role if c["final_band"] == "AUTO_REJECT"),
        "rerouted": sum(1 for c in in_role if c.get("reroute_label")),
        "near_miss": sum(1 for c in in_role if c.get("final_band_flag") == "near miss"),
        "needs_manual_review": len(needs_review),
        "most_common_reason_code": reason_counter.most_common(1)[0][0] if reason_counter else "-",
        "most_common_red_flag": flag_counter.most_common(1)[0][0] if flag_counter else "-",
    }


def render_summary_bar(candidates: list[dict], role_key: str, role_label: str):
    s = compute_summary(candidates, role_key)
    st.subheader(f"{role_label} summary")
    cols = st.columns(6)
    cols[0].metric("Shortlist", s["shortlist"])
    cols[1].metric("Review", s["review"])
    cols[2].metric("Auto-reject", s["auto_reject"])
    cols[3].metric("Re-routed", s["rerouted"])
    cols[4].metric("Near miss", s["near_miss"])
    cols[5].metric("Needs manual review", s["needs_manual_review"])
    st.caption(f"Most common reason code: **{s['most_common_reason_code']}** · Most common red flag: **{s['most_common_red_flag']}**")


def _band_reasoning(role_key: str, score: dict, rubrics: dict) -> str:
    band_defs = rubrics["roles"][role_key]["bands"]
    shortlist_min = next(b["min"] for b in band_defs if b["label"] == "SHORTLIST")
    review_min = next(b["min"] for b in band_defs if b["label"] == "REVIEW" and not b.get("flag"))
    total = score["total_points"]
    band = score["band"]
    band_flag = score.get("band_flag")

    criteria = sorted(score["criteria"], key=lambda c: c["points"] / c["weight"])
    weakest = criteria[0]
    strongest = criteria[-1]

    if band_flag == "above experience range":
        return "Sent to Review regardless of score: SPM experience is above the 8-year range, so the rubric caps this at Review rather than Shortlist."

    lines = []
    if band == "SHORTLIST":
        lines.append(f"Total {total} meets the Shortlist threshold ({shortlist_min}+).")
    elif band_flag == "near miss":
        lines.append(f"Total {total} is within 5 points below the Review threshold ({review_min}) -- held as a near miss rather than auto-rejected.")
    elif band == "REVIEW":
        lines.append(f"Total {total} falls in the Review range (below the {shortlist_min}-point Shortlist bar).")
    else:
        lines.append(f"Total {total} falls below the auto-reject threshold.")

    lines.append(
        f"Why not higher: **{weakest['name']}** ({weakest['id']}) scored {weakest['score']}/5 "
        f"({weakest['points']} of {weakest['weight']} possible points) -- the biggest single drag on the total."
    )
    lines.append(
        f"Why not lower: **{strongest['name']}** ({strongest['id']}) scored {strongest['score']}/5, "
        f"carrying {strongest['points']} of {strongest['weight']} possible points."
    )
    return "\n\n".join(lines)


def render_criteria_table(criteria: list[dict]):
    st.dataframe(
        [
            {
                "ID": c["id"],
                "Criterion": c["name"],
                "Anchor": c["matched_anchor"],
                "Score": c["score"],
                "Points": f"{c['points']} / {c['weight']}",
                "Evidence": c["evidence"],
                "Rationale": c["rationale"],
            }
            for c in criteria
        ],
        hide_index=True,
        use_container_width=True,
    )


def render_gates(gates: dict, years_pm_experience: float):
    parts = [f"Years of PM experience (computed): **{years_pm_experience}**"]
    for gid, g in gates.items():
        status = "PASS" if g["passed"] else "FAIL"
        flag = f" -- flagged: {g['flag']}" if g.get("flag") else ""
        parts.append(f"{gid}: {status}{flag}")
    st.write(" · ".join(parts))


def render_red_flags(red_flags: list[dict], rubrics: dict):
    flag_defs = {f["id"]: f for f in rubrics["red_flags"]["flags"]}
    present = [f for f in red_flags if f.get("present")]
    if not present:
        st.caption("No red flags.")
        return
    for f in present:
        fdef = flag_defs.get(f["id"], {})
        st.warning(f"**{f['id']} -- {fdef.get('name', '')}**\n\nEvidence: {f['evidence']}\n\nProbe: _{fdef.get('probe', '')}_")


def render_interview_brief(candidate: dict):
    if not candidate.get("interview_brief_why"):
        st.caption("Not yet generated. Brief generation ran with scoring -- check the Score tab for errors.")
        return
    st.markdown(f"**Why ranked here:** {candidate['interview_brief_why']}")
    st.markdown(f"**Biggest gap:** {candidate['interview_brief_gap']}")
    probes = json.loads(candidate.get("interview_brief_probes") or "[]")
    if probes:
        st.markdown("**Interview probes:**")
        for p in probes:
            tag = "red flag" if p["source"] == "red_flag" else "weak criterion"
            st.markdown(f"- _{p['text']}_ ({tag} {p['id']})")


def render_email_draft(candidate: dict, allow_send: bool = False):
    if not candidate.get("email_body"):
        st.caption("Not yet generated -- drafted automatically when you click Advance or Pass.")
        return
    key_prefix = f"email_{candidate['id']}"

    if candidate.get("resend_message_id"):
        st.success(f"Sent {candidate['email_sent_at']} -- Resend id `{candidate['resend_message_id']}`")
        return

    subject = st.text_input("Subject", value=candidate["email_subject"], key=f"{key_prefix}_subject")
    body = st.text_area("Body", value=candidate["email_body"], height=220, key=f"{key_prefix}_body")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Save edits", key=f"{key_prefix}_save"):
            db.update_email_body(candidate["id"], subject, body)
            st.success("Draft saved.")
    if allow_send:
        with col2:
            if st.button("Send", key=f"{key_prefix}_send"):
                db.update_email_body(candidate["id"], subject, body)
                try:
                    with st.spinner("Sending via Resend..."):
                        result = send_now(candidate["id"])
                    st.success(f"Sent (Resend id: {result['message_id']}).")
                    st.rerun()
                except SendError as e:
                    st.error(f"Send failed: {e}")


def render_candidate_card(candidate: dict, rubrics: dict, on_action=None):
    scores = db.get_scores(candidate["id"])
    scored_role = candidate["final_role"]
    score = scores.get(scored_role)
    if not score:
        st.error("No score record found for this candidate's final role.")
        return

    other_role = "spm" if scored_role == "pm" else "pm"
    other_score = scores.get(other_role)

    title = f"{candidate.get('name') or candidate['id']} -- {scored_role.upper()} -- {candidate['final_band']}"
    if candidate.get("final_band_flag"):
        title += f" ({candidate['final_band_flag']})"
    if candidate.get("reroute_label"):
        title += f" -- {candidate['reroute_label']}"

    with st.expander(title):
        if candidate.get("location_flag_note"):
            st.info(f"Location: {candidate['location_flag_note']}")

        st.markdown("**Gates**")
        render_gates(score["gates"], candidate["years_pm_experience"])

        st.markdown("**Criteria**")
        render_criteria_table(score["criteria"])

        st.markdown("**Red flags**")
        render_red_flags(json.loads(candidate.get("red_flags") or "[]"), rubrics)

        st.markdown("**Band reasoning**")
        st.markdown(_band_reasoning(scored_role, score, rubrics))

        st.markdown("**Interview brief**")
        render_interview_brief(candidate)

        st.markdown("**Email draft**")
        render_email_draft(candidate, allow_send=candidate.get("decision_status") != "pending")

        if other_score:
            with st.expander(f"Score on the other rubric ({other_role.upper()})"):
                render_gates(other_score["gates"], candidate["years_pm_experience"])
                render_criteria_table(other_score["criteria"])
                st.write(f"Total: {other_score['total_points']} -- {other_score['band']}")

        col1, col2 = st.columns(2)
        decision_status = candidate.get("decision_status", "pending")
        role_label = rubrics["roles"][scored_role]["label"]
        with col1:
            if st.button("Advance", key=f"advance_{candidate['id']}", disabled=decision_status != "pending"):
                with st.spinner("Drafting invite email..."):
                    email = generate_invite_email(candidate, score, role_label)
                db.save_email_draft(candidate["id"], "invite", email["subject"], email["body"])
                db.set_decision_status(candidate["id"], "advanced")
                db.log_event(candidate["id"], "advanced", detail="invite email drafted")
                st.rerun()
        with col2:
            if st.button("Pass", key=f"pass_{candidate['id']}", disabled=decision_status != "pending"):
                with st.spinner("Drafting rejection email..."):
                    email = generate_rejection_email(candidate, role_label)
                db.save_email_draft(candidate["id"], "rejection", email["subject"], email["body"])
                db.set_decision_status(candidate["id"], "passed")
                db.log_event(candidate["id"], "passed", detail="rejection email drafted")
                st.rerun()
        if decision_status != "pending":
            st.caption(f"Decision: **{decision_status}**")


def render_band_tab(candidates: list[dict], rubrics: dict, band: str):
    matching = [c for c in candidates if c.get("final_band") == band]
    matching.sort(key=lambda c: -(db.get_scores(c["id"]).get(c["final_role"], {}).get("total_points", 0)))
    if not matching:
        st.info(f"No candidates in {band} yet.")
        return
    for c in matching:
        render_candidate_card(c, rubrics)


def render_auto_reject_log(candidates: list[dict]):
    rejected = [c for c in candidates if c.get("final_band") == "AUTO_REJECT"]
    if not rejected:
        st.info("No auto-rejected candidates yet.")
        return

    if st.button("Process send queue"):
        with st.spinner("Sending due rejections via Resend..."):
            results = process_send_queue()
        if results:
            st.success(f"Processed {len(results)} candidate(s).")
            for r in results:
                st.write(f"- {r['name']}: {r['status']} -- {r['detail']}")
        else:
            st.info("Nothing due yet.")
        st.rerun()

    for c in rejected:
        scores = db.get_scores(c["id"])
        score = scores.get(c["final_role"], {})
        reason_codes = ", ".join(json.loads(c.get("reason_codes") or "[]"))
        already_sent = bool(c.get("resend_message_id"))
        cols = st.columns([3, 1, 1, 2, 2, 2])
        cols[0].write(c.get("name") or c["id"])
        cols[1].write(c["applied_role"])
        cols[2].write(score.get("total_points", "-"))
        cols[3].write(reason_codes or "-")
        cols[4].write("Sent" if already_sent else c.get("auto_reject_send_after", "-"))
        if cols[5].button("Override -> Review", key=f"override_{c['id']}", disabled=already_sent):
            db.set_decision_status(c["id"], "overridden", final_band="REVIEW")
            db.log_event(c["id"], "overridden", detail="Moved from AUTO_REJECT to REVIEW")
            st.rerun()
        with st.expander(f"Rejection email draft -- {c.get('name') or c['id']}"):
            st.caption("Sends automatically after the 48h hold via the send queue -- use Override to stop it.")
            render_email_draft(c, allow_send=False)


def render_decision_log():
    events = db.list_decision_log()
    if not events:
        st.info("No events yet.")
        return
    candidates_by_id = {c["id"]: c for c in db.list_candidates()}
    st.dataframe(
        [
            {
                "Timestamp": e["created_at"],
                "Candidate": (candidates_by_id.get(e["candidate_id"]) or {}).get("name") or e["candidate_id"],
                "Event": e["event"],
                "Detail": e["detail"],
                "Rubric version": e["rubric_version"],
            }
            for e in events
        ],
        hide_index=True,
        use_container_width=True,
    )
