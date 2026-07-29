-- TRIADE-VERIFY-v1 · continuidad identitaria verificable.
-- Esta migración no lee ni modifica identity_core.

CREATE TABLE IF NOT EXISTS identity_manifest_anchor (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    identity TEXT NOT NULL,
    identity_version TEXT NOT NULL,
    constitution_hash TEXT NOT NULL,
    identity_core_hash TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    established_at TEXT NOT NULL,
    established_by TEXT NOT NULL,
    backup_ref TEXT
);

CREATE TABLE IF NOT EXISTS identity_continuity_log (
    verification_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    expected_manifest_hash TEXT,
    integrity TEXT NOT NULL CHECK (integrity IN ('verified', 'degraded_safe')),
    continuity_from_previous_run INTEGER NOT NULL CHECK (continuity_from_previous_run IN (0, 1)),
    tamper_detected INTEGER NOT NULL CHECK (tamper_detected IN (0, 1)),
    mismatch_json TEXT NOT NULL DEFAULT '[]',
    verified_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_identity_continuity_run
    ON identity_continuity_log(run_id, verified_at DESC);
