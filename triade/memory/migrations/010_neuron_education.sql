-- Educación neuronal gobernada y repetición espaciada.
CREATE TABLE IF NOT EXISTS neuron_competencies (
    competency_id TEXT PRIMARY KEY,
    neuron_id INTEGER NOT NULL,
    domain TEXT NOT NULL,
    name TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0,
    retention_score REAL NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    last_reviewed TEXT,
    next_review TEXT,
    decay_rate REAL NOT NULL DEFAULT 0.05,
    status TEXT NOT NULL DEFAULT 'diagnosed',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(neuron_id, domain, name)
);
CREATE INDEX IF NOT EXISTS idx_neuron_competencies_due ON neuron_competencies(next_review, status);

CREATE TABLE IF NOT EXISTS neuron_curricula (
    curriculum_id TEXT PRIMARY KEY,
    neuron_id INTEGER NOT NULL,
    mission_id INTEGER,
    domain TEXT NOT NULL,
    objective TEXT NOT NULL,
    prerequisites_json TEXT NOT NULL DEFAULT '[]',
    allowed_source_types_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'candidate',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(neuron_id, domain)
);

CREATE TABLE IF NOT EXISTS neuron_education_sessions (
    session_id TEXT PRIMARY KEY,
    curriculum_id TEXT NOT NULL,
    neuron_id INTEGER NOT NULL,
    competency_id TEXT NOT NULL,
    state TEXT NOT NULL,
    material_refs_json TEXT NOT NULL DEFAULT '[]',
    independent_source_count INTEGER NOT NULL DEFAULT 0,
    lesson_json TEXT NOT NULL DEFAULT '{}',
    exercise_json TEXT NOT NULL DEFAULT '{}',
    evaluation_json TEXT NOT NULL DEFAULT '{}',
    baseline_score REAL,
    post_score REAL,
    applied_run_count INTEGER NOT NULL DEFAULT 0,
    regression_count INTEGER NOT NULL DEFAULT 0,
    result TEXT NOT NULL,
    rollback_ref TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_neuron_education_neuron ON neuron_education_sessions(neuron_id, created_at);

CREATE TABLE IF NOT EXISTS neuron_education_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    neuron_id INTEGER,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
