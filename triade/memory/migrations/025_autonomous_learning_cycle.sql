CREATE TABLE IF NOT EXISTS autonomous_learning_artifacts (
    artifact_id TEXT PRIMARY KEY,
    capability TEXT NOT NULL,
    operation TEXT NOT NULL,
    configuration_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN
        ('candidate', 'canary', 'active', 'rolled_back', 'consolidated', 'rejected')),
    evidence_ref TEXT NOT NULL,
    rollback_ref TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS autonomous_learning_receipts (
    learning_receipt_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL,
    gap_ref TEXT NOT NULL,
    research_ref TEXT NOT NULL,
    baseline_json TEXT NOT NULL,
    post_measurement_json TEXT NOT NULL,
    transfer_json TEXT NOT NULL,
    regression_json TEXT NOT NULL,
    rollback_json TEXT NOT NULL,
    restart_json TEXT NOT NULL,
    decision TEXT NOT NULL,
    evidence_bundle_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (artifact_id) REFERENCES autonomous_learning_artifacts(artifact_id)
);
