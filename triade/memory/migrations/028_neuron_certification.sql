CREATE TABLE IF NOT EXISTS neuron_certifications (
    certification_id TEXT PRIMARY KEY,
    neuron_id INTEGER NOT NULL,
    version TEXT NOT NULL,
    owner TEXT NOT NULL,
    mission TEXT NOT NULL,
    domain TEXT NOT NULL,
    allowed_sources_json TEXT NOT NULL,
    allowed_actions_json TEXT NOT NULL,
    benchmarks_json TEXT NOT NULL,
    baseline_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    limitations_json TEXT NOT NULL,
    rollback_ref TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    last_review TEXT NOT NULL,
    independent_evaluation INTEGER NOT NULL CHECK (independent_evaluation IN (0, 1)),
    regressions_green INTEGER NOT NULL CHECK (regressions_green IN (0, 1)),
    rollback_verified INTEGER NOT NULL CHECK (rollback_verified IN (0, 1)),
    restart_verified INTEGER NOT NULL CHECK (restart_verified IN (0, 1)),
    benchmark_passed INTEGER NOT NULL CHECK (benchmark_passed IN (0, 1)),
    evidence_complete INTEGER NOT NULL CHECK (evidence_complete IN (0, 1)),
    created_at TEXT NOT NULL,
    FOREIGN KEY (neuron_id) REFERENCES neurons(id)
);

CREATE TABLE IF NOT EXISTS neuron_certification_transitions (
    transition_id TEXT PRIMARY KEY,
    neuron_id INTEGER NOT NULL,
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    reason TEXT NOT NULL,
    rollback_ref TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (neuron_id) REFERENCES neurons(id)
);
