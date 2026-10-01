CREATE TABLE IF NOT EXISTS candidates (
    id TEXT PRIMARY KEY,
    name TEXT,
    email TEXT,
    phone TEXT,
    linkedin TEXT,
    city TEXT,
    location_flag TEXT,
    applied_role TEXT NOT NULL,
    source_file TEXT NOT NULL,
    raw_text TEXT,
    redacted_text TEXT,
    parse_status TEXT NOT NULL DEFAULT 'ok',
    is_duplicate_of TEXT,
    created_at TEXT NOT NULL,

    years_pm_experience REAL,
    final_role TEXT,
    final_band TEXT,
    final_band_flag TEXT,
    reroute_label TEXT,
    reason_codes TEXT,
    red_flags TEXT,
    location_flag_note TEXT,
    score_status TEXT NOT NULL DEFAULT 'not_scored',
    decision_status TEXT NOT NULL DEFAULT 'pending',
    auto_reject_send_after TEXT,
    resend_message_id TEXT,
    scored_at TEXT
);

CREATE TABLE IF NOT EXISTS scores (
    id SERIAL PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    role TEXT NOT NULL,
    total_points REAL NOT NULL,
    band TEXT NOT NULL,
    band_flag TEXT,
    criteria_json TEXT NOT NULL,
    gates_json TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL,
    rubric_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(candidate_id, role)
);

CREATE TABLE IF NOT EXISTS decision_log (
    id SERIAL PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    event TEXT NOT NULL,
    detail TEXT,
    rubric_version TEXT,
    created_at TEXT NOT NULL
);

ALTER TABLE candidates ADD COLUMN IF NOT EXISTS interview_brief_why TEXT;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS interview_brief_gap TEXT;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS interview_brief_probes TEXT;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS interview_brief_generated_at TEXT;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS email_type TEXT;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS email_subject TEXT;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS email_body TEXT;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS email_generated_at TEXT;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS email_sent_at TEXT;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS better_fit_note TEXT;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS contact_flag TEXT;

-- Dedup by email alone broke on datasets where multiple different candidates share a
-- placeholder/template email (e.g. a course's sample resume batch) -- switched to
-- (email, name) together. NULLs are excluded from the constraint (Postgres treats each
-- NULL as distinct anyway), matching db.find_duplicate_candidate's app-level logic of
-- never calling something a duplicate when either name is missing.
DROP INDEX IF EXISTS idx_candidates_email;
CREATE UNIQUE INDEX IF NOT EXISTS idx_candidates_email_name
    ON candidates(email, lower(name))
    WHERE email IS NOT NULL AND name IS NOT NULL AND is_duplicate_of IS NULL;
