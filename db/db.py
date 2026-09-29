from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


@contextmanager
def get_conn():
    conn = psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        for stmt in SCHEMA_PATH.read_text().split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def find_candidate_by_email(email: str):
    if not email:
        return None
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM candidates WHERE email = %s AND is_duplicate_of IS NULL",
            (email,),
        ).fetchone()
        return dict(row) if row else None


def insert_candidate(candidate: dict):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO candidates
                (id, name, email, phone, linkedin, city, location_flag,
                 applied_role, source_file, raw_text, redacted_text,
                 parse_status, is_duplicate_of, created_at)
            VALUES
                (%(id)s, %(name)s, %(email)s, %(phone)s, %(linkedin)s, %(city)s, %(location_flag)s,
                 %(applied_role)s, %(source_file)s, %(raw_text)s, %(redacted_text)s,
                 %(parse_status)s, %(is_duplicate_of)s, %(created_at)s)
            """,
            candidate,
        )


def list_candidates(applied_role: str | None = None):
    with get_conn() as conn:
        if applied_role:
            rows = conn.execute(
                "SELECT * FROM candidates WHERE applied_role = %s ORDER BY created_at DESC",
                (applied_role,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM candidates ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def get_candidate(candidate_id: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM candidates WHERE id = %s", (candidate_id,)
        ).fetchone()
        return dict(row) if row else None


def log_event(candidate_id: str, event: str, detail: str = "", rubric_version: str = ""):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO decision_log (candidate_id, event, detail, rubric_version, created_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (candidate_id, event, detail, rubric_version, now_iso()),
        )


def list_candidates_needing_scoring():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM candidates WHERE score_status = 'not_scored' AND parse_status = 'ok' "
            "ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]


def save_score(candidate_id: str, role: str, score_view: dict, rubric_version: str):
    import json as _json

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO scores
                (candidate_id, role, total_points, band, band_flag,
                 criteria_json, gates_json, reason_codes_json, rubric_version, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT(candidate_id, role) DO UPDATE SET
                total_points=excluded.total_points,
                band=excluded.band,
                band_flag=excluded.band_flag,
                criteria_json=excluded.criteria_json,
                gates_json=excluded.gates_json,
                reason_codes_json=excluded.reason_codes_json,
                rubric_version=excluded.rubric_version,
                created_at=excluded.created_at
            """,
            (
                candidate_id,
                role,
                score_view["total_points"],
                score_view["band"],
                score_view.get("band_flag"),
                _json.dumps(score_view["criteria"]),
                _json.dumps(score_view["gates"]),
                _json.dumps(score_view.get("reason_codes", [])),
                rubric_version,
                now_iso(),
            ),
        )


def get_scores(candidate_id: str) -> dict:
    import json as _json

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM scores WHERE candidate_id = %s", (candidate_id,)
        ).fetchall()
    out = {}
    for r in rows:
        d = dict(r)
        d["criteria"] = _json.loads(d["criteria_json"])
        d["gates"] = _json.loads(d["gates_json"])
        d["reason_codes"] = _json.loads(d["reason_codes_json"])
        out[d["role"]] = d
    return out


def apply_scoring_decision(candidate_id: str, decision: dict, rubric_version: str):
    import json as _json

    scored_role = decision["scored_role"]
    save_score(candidate_id, scored_role, decision, rubric_version)
    save_score(candidate_id, decision["other_role_view"]["role"], decision["other_role_view"], rubric_version)

    band = decision["band"]
    decision_status = "auto_reject_queued" if band == "AUTO_REJECT" else "pending"
    auto_reject_send_after = None
    if band == "AUTO_REJECT":
        from datetime import timedelta

        auto_reject_send_after = (
            datetime.now(timezone.utc) + timedelta(hours=decision.get("hold_hours", 48))
        ).isoformat()

    with get_conn() as conn:
        conn.execute(
            """
            UPDATE candidates SET
                years_pm_experience = %s,
                final_role = %s,
                final_band = %s,
                final_band_flag = %s,
                reroute_label = %s,
                reason_codes = %s,
                red_flags = %s,
                location_flag_note = %s,
                better_fit_note = %s,
                score_status = 'scored',
                decision_status = %s,
                auto_reject_send_after = %s,
                scored_at = %s
            WHERE id = %s
            """,
            (
                decision["years_pm_experience"],
                scored_role,
                band,
                decision.get("band_flag"),
                decision.get("reroute_label"),
                _json.dumps(decision.get("reason_codes", [])),
                _json.dumps(decision.get("red_flags", [])),
                decision.get("location_flag_note"),
                decision.get("better_fit_note"),
                decision_status,
                auto_reject_send_after,
                now_iso(),
                candidate_id,
            ),
        )


def mark_needs_manual_review(candidate_id: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE candidates SET score_status = 'needs_manual_review' WHERE id = %s",
            (candidate_id,),
        )


def set_decision_status(candidate_id: str, status: str, final_band: str | None = None):
    with get_conn() as conn:
        if final_band:
            conn.execute(
                "UPDATE candidates SET decision_status = %s, final_band = %s WHERE id = %s",
                (status, final_band, candidate_id),
            )
        else:
            conn.execute(
                "UPDATE candidates SET decision_status = %s WHERE id = %s",
                (status, candidate_id),
            )


def save_interview_brief(candidate_id: str, brief: dict):
    import json as _json

    with get_conn() as conn:
        conn.execute(
            """
            UPDATE candidates SET
                interview_brief_why = %s,
                interview_brief_gap = %s,
                interview_brief_probes = %s,
                interview_brief_generated_at = %s
            WHERE id = %s
            """,
            (
                brief["why_ranked_here"],
                brief["biggest_gap"],
                _json.dumps(brief["probes"]),
                now_iso(),
                candidate_id,
            ),
        )


def save_email_draft(candidate_id: str, email_type: str, subject: str, body: str):
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE candidates SET
                email_type = %s,
                email_subject = %s,
                email_body = %s,
                email_generated_at = %s
            WHERE id = %s
            """,
            (email_type, subject, body, now_iso(), candidate_id),
        )


def update_email_body(candidate_id: str, subject: str, body: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE candidates SET email_subject = %s, email_body = %s WHERE id = %s",
            (subject, body, candidate_id),
        )


def mark_email_sent(candidate_id: str, message_id: str, decision_status: str):
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE candidates SET
                resend_message_id = %s,
                email_sent_at = %s,
                decision_status = %s
            WHERE id = %s
            """,
            (message_id, now_iso(), decision_status, candidate_id),
        )


def list_auto_rejects_due():
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM candidates
            WHERE decision_status = 'auto_reject_queued'
              AND resend_message_id IS NULL
              AND auto_reject_send_after IS NOT NULL
              AND auto_reject_send_after <= %s
            ORDER BY auto_reject_send_after
            """,
            (now_iso(),),
        ).fetchall()
        return [dict(r) for r in rows]


def list_decision_log(candidate_id: str | None = None):
    with get_conn() as conn:
        if candidate_id:
            rows = conn.execute(
                "SELECT * FROM decision_log WHERE candidate_id = %s ORDER BY created_at",
                (candidate_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM decision_log ORDER BY created_at"
            ).fetchall()
        return [dict(r) for r in rows]
