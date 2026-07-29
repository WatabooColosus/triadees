CREATE TABLE IF NOT EXISTS governed_evidence (
    evidence_id TEXT PRIMARY KEY,
    origin_class TEXT NOT NULL,
    producer_id TEXT NOT NULL,
    source TEXT NOT NULL,
    root_external_event_id TEXT,
    causal_parent_id TEXT,
    autonomous_depth INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    trust_level TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    FOREIGN KEY(causal_parent_id) REFERENCES governed_evidence(evidence_id)
);
CREATE INDEX IF NOT EXISTS idx_governed_evidence_root
    ON governed_evidence(root_external_event_id, created_at);

CREATE TABLE IF NOT EXISTS evidence_consumptions (
    evidence_id TEXT NOT NULL,
    consumer_type TEXT NOT NULL,
    consumer_id TEXT NOT NULL,
    task_id TEXT,
    consumed_at TEXT NOT NULL,
    outcome TEXT NOT NULL,
    UNIQUE(evidence_id, consumer_type, consumer_id),
    FOREIGN KEY(evidence_id) REFERENCES governed_evidence(evidence_id)
);
