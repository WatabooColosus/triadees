CREATE TABLE IF NOT EXISTS backup_restore_drills (
    drill_id TEXT PRIMARY KEY,
    backup_ref TEXT NOT NULL,
    status TEXT NOT NULL,
    sandbox_ref TEXT NOT NULL,
    integrity_check TEXT,
    identity_manifest_hash TEXT,
    semantic_memory_count INTEGER NOT NULL DEFAULT 0,
    task_states_json TEXT NOT NULL DEFAULT '{}',
    backup_bytes INTEGER NOT NULL DEFAULT 0,
    snapshot_bytes INTEGER NOT NULL DEFAULT 0,
    artifact_bytes INTEGER NOT NULL DEFAULT 0,
    growth_bytes INTEGER,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_restore_drills_created
ON backup_restore_drills(created_at);
