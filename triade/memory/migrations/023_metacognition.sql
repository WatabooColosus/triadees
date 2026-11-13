CREATE TABLE IF NOT EXISTS capability_awareness (
    capability_id TEXT PRIMARY KEY,
    availability TEXT NOT NULL CHECK (availability IN
        ('available', 'degraded', 'unavailable', 'unverified', 'quarantined')),
    dependencies_json TEXT NOT NULL,
    resources_json TEXT NOT NULL,
    utility REAL NOT NULL,
    risk REAL NOT NULL,
    reason TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS capability_predictions (
    prediction_id TEXT PRIMARY KEY,
    capability_id TEXT NOT NULL,
    task_ref TEXT NOT NULL,
    predicted_success REAL NOT NULL CHECK (predicted_success BETWEEN 0 AND 1),
    reasons_json TEXT NOT NULL,
    resources_json TEXT NOT NULL,
    predicted_at TEXT NOT NULL,
    outcome_success INTEGER CHECK (outcome_success IN (0, 1)),
    error_type TEXT,
    evidence_ref TEXT,
    completed_at TEXT,
    FOREIGN KEY (capability_id) REFERENCES capability_awareness(capability_id)
);

CREATE INDEX IF NOT EXISTS idx_capability_predictions_calibration
    ON capability_predictions(capability_id, completed_at);
