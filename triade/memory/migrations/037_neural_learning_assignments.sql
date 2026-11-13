CREATE TABLE IF NOT EXISTS neuron_learning_assignments (
    assignment_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    neuron_id INTEGER NOT NULL,
    session_id TEXT NOT NULL,
    source_run_id TEXT NOT NULL,
    knowledge_version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'experimental',
    decision TEXT NOT NULL,
    evidence_ref TEXT NOT NULL,
    pre_behavior_json TEXT NOT NULL DEFAULT '{}',
    post_behavior_json TEXT NOT NULL DEFAULT '{}',
    outcome_score REAL,
    use_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(candidate_id, neuron_id),
    FOREIGN KEY(candidate_id) REFERENCES learning_queue(candidate_id),
    FOREIGN KEY(neuron_id) REFERENCES neurons(id),
    FOREIGN KEY(session_id) REFERENCES neuron_education_sessions(session_id)
);

CREATE INDEX IF NOT EXISTS idx_neuron_learning_assignment_candidate
ON neuron_learning_assignments(candidate_id, status);

CREATE INDEX IF NOT EXISTS idx_neuron_learning_assignment_neuron
ON neuron_learning_assignments(neuron_id, status, knowledge_version);
