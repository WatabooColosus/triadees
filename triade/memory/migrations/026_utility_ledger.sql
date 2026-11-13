CREATE TABLE IF NOT EXISTS utility_receipts (
    receipt_id TEXT PRIMARY KEY,
    goal TEXT NOT NULL,
    classification TEXT NOT NULL CHECK (classification IN
        ('activity', 'output', 'effect', 'utility', 'learning')),
    baseline_json TEXT NOT NULL,
    outcome_json TEXT NOT NULL,
    improvement REAL NOT NULL,
    quality_score REAL NOT NULL,
    human_intervention REAL NOT NULL,
    time_cost REAL NOT NULL,
    cpu_cost REAL NOT NULL,
    gpu_cost REAL NOT NULL,
    memory_cost REAL NOT NULL,
    storage_cost REAL NOT NULL,
    network_cost REAL NOT NULL,
    risk TEXT NOT NULL,
    regressions_json TEXT NOT NULL,
    verified INTEGER NOT NULL CHECK (verified IN (0, 1)),
    evidence_ref TEXT,
    effect_receipt_ref TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_utility_receipts_classification
ON utility_receipts(classification, verified, created_at);
