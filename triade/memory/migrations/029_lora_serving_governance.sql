CREATE TABLE IF NOT EXISTS governed_peft_versions (
    version_id TEXT PRIMARY KEY,
    adapter_path TEXT NOT NULL,
    integrity_sha256 TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN
        ('candidate', 'canary', 'canary_failed', 'approved', 'active', 'rolled_back', 'retired')),
    traffic_percent REAL NOT NULL,
    baseline_quality REAL NOT NULL,
    rollback_ref TEXT NOT NULL,
    approved_by TEXT,
    previous_version_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS governed_peft_observations (
    observation_id TEXT PRIMARY KEY,
    version_id TEXT NOT NULL,
    quality REAL NOT NULL,
    latency_ms REAL NOT NULL,
    success INTEGER NOT NULL CHECK (success IN (0, 1)),
    evidence_ref TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (version_id) REFERENCES governed_peft_versions(version_id)
);

CREATE TABLE IF NOT EXISTS governed_peft_active_slot (
    slot TEXT PRIMARY KEY,
    version_id TEXT,
    previous_version_id TEXT,
    updated_at TEXT NOT NULL
);
