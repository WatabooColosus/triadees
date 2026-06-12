-- Triade QualiaBus storage
CREATE TABLE IF NOT EXISTS qualia_experiences (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    neuron_id TEXT,
    neuron_type TEXT,
    mission TEXT,
    source TEXT,
    source_type TEXT,
    observation TEXT,
    extracted_pattern TEXT,
    proposed_learning TEXT,
    confidence REAL DEFAULT 0.0,
    risk TEXT DEFAULT 'low',
    usefulness REAL DEFAULT 0.0,
    emotional_signal_json TEXT,
    evidence_refs_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS qualia_signals (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    experience_id TEXT,
    signal_type TEXT,
    intensity REAL DEFAULT 0.0,
    valence REAL DEFAULT 0.0,
    urgency REAL DEFAULT 0.0,
    curiosity REAL DEFAULT 0.0,
    risk REAL DEFAULT 0.0,
    confidence REAL DEFAULT 0.0,
    tone_hint TEXT,
    reason TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS qualia_central_packets (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    experience_id TEXT,
    claim TEXT,
    hypothesis TEXT,
    decision_hint TEXT,
    validation_need TEXT,
    related_goals_json TEXT,
    confidence REAL DEFAULT 0.0,
    evidence_refs_json TEXT,
    status TEXT DEFAULT 'hypothesis',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS qualia_storage_packets (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    experience_id TEXT,
    memory_type TEXT,
    category TEXT,
    subcategory TEXT,
    content TEXT,
    source TEXT,
    content_hash TEXT,
    confidence REAL DEFAULT 0.0,
    verification_status TEXT DEFAULT 'unverified',
    promotion_status TEXT DEFAULT 'candidate',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS qualia_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    curiosity REAL DEFAULT 0.0,
    confidence REAL DEFAULT 0.0,
    risk REAL DEFAULT 0.0,
    urgency REAL DEFAULT 0.0,
    coherence REAL DEFAULT 0.0,
    novelty REAL DEFAULT 0.0,
    usefulness REAL DEFAULT 0.0,
    saturation REAL DEFAULT 0.0,
    dominant_signal TEXT DEFAULT 'none',
    recommended_action TEXT DEFAULT 'observe',
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_qualia_experiences_run_id ON qualia_experiences(run_id);
CREATE INDEX IF NOT EXISTS idx_qualia_experiences_source_type ON qualia_experiences(source_type);
CREATE INDEX IF NOT EXISTS idx_qualia_signals_run_id ON qualia_signals(run_id);
CREATE INDEX IF NOT EXISTS idx_qualia_signals_experience_id ON qualia_signals(experience_id);
CREATE INDEX IF NOT EXISTS idx_qualia_central_packets_run_id ON qualia_central_packets(run_id);
CREATE INDEX IF NOT EXISTS idx_qualia_storage_packets_run_id ON qualia_storage_packets(run_id);
CREATE INDEX IF NOT EXISTS idx_qualia_states_run_id ON qualia_states(run_id);
