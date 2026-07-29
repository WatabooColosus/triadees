-- Evidencia independiente y aplicaciones reales de sesiones educativas.
CREATE TABLE IF NOT EXISTS neuron_education_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    outcome_score REAL NOT NULL,
    evidence_ref TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(session_id, run_id),
    FOREIGN KEY(session_id) REFERENCES neuron_education_sessions(session_id)
);
CREATE INDEX IF NOT EXISTS idx_neuron_education_applications_session
ON neuron_education_applications(session_id, created_at);
