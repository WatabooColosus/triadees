-- Tríade Ω · Bodega de Almacenamiento
-- Esquema SQLite inicial para MVP local verificable
-- Motor recomendado: SQLite con WAL

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS identity_core (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    value TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    confidence REAL DEFAULT 1.0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    source TEXT DEFAULT 'console',
    user_input TEXT NOT NULL,
    status TEXT DEFAULT 'created',
    model_hypothalamus TEXT,
    model_central TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS episodic_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    title TEXT,
    content TEXT NOT NULL,
    summary TEXT,
    tags TEXT,
    importance REAL DEFAULT 0.5,
    confidence REAL DEFAULT 0.8,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS semantic_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    value TEXT NOT NULL,
    domain TEXT,
    source_ref TEXT,
    confidence REAL DEFAULT 0.8,
    status TEXT DEFAULT 'stable',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS neurons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    mission TEXT NOT NULL,
    domain TEXT,
    rules TEXT,
    status TEXT DEFAULT 'candidate',
    created_by TEXT DEFAULT 'central',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS neuron_training (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    neuron_id INTEGER NOT NULL,
    training_data TEXT,
    evaluation_notes TEXT,
    score REAL DEFAULT 0.0,
    status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (neuron_id) REFERENCES neurons(id)
);

CREATE TABLE IF NOT EXISTS signal_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    intent TEXT,
    tone TEXT,
    urgency TEXT,
    risk TEXT,
    pv7 TEXT,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS crystal_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    ethics REAL DEFAULT 0.8,
    depth REAL DEFAULT 0.6,
    creativity REAL DEFAULT 0.5,
    relation REAL DEFAULT 0.7,
    pv7_score REAL DEFAULT 0.5,
    stability REAL DEFAULT 0.5,
    intensity REAL DEFAULT 0.5,
    q_crystal REAL DEFAULT 0.0,
    ethics_vector TEXT,
    regulation_notes TEXT,
    previous_q_crystal REAL,
    previous_stability REAL,
    q_delta REAL DEFAULT 0.0,
    stability_delta REAL DEFAULT 0.0,
    temporal_status TEXT DEFAULT 'baseline',
    temporal_alerts TEXT,
    history_window INTEGER DEFAULT 0,
    context_scope TEXT DEFAULT 'source_intent',
    context_key TEXT,
    comparison_basis TEXT,
    source TEXT,
    intent TEXT,
    session_id TEXT,
    project_id TEXT,
    active_neuron TEXT,
    decision_notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS learning_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id TEXT NOT NULL UNIQUE,
    source_type TEXT,
    source_ref TEXT,
    title TEXT,
    content TEXT NOT NULL,
    normalized_summary TEXT,
    domain TEXT,
    risk_level TEXT DEFAULT 'low',
    confidence REAL DEFAULT 0.0,
    utility REAL DEFAULT 0.0,
    status TEXT DEFAULT 'candidate',
    verification_notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS knowledge_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    domain TEXT,
    pattern_body TEXT NOT NULL,
    source_ref TEXT,
    confidence REAL DEFAULT 0.8,
    status TEXT DEFAULT 'stable',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS model_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    role TEXT NOT NULL,
    provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    ok INTEGER DEFAULT 0,
    error TEXT,
    quality_score REAL DEFAULT 0.0,
    latency_ms INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS federated_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    owner TEXT,
    endpoint TEXT,
    public_key TEXT,
    trust_level TEXT DEFAULT 'low',
    permissions TEXT,
    status TEXT DEFAULT 'active',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS federated_exchange_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exchange_id TEXT NOT NULL UNIQUE,
    source_node_id TEXT,
    target_node_id TEXT,
    exchange_type TEXT,
    payload_ref TEXT,
    permissions_used TEXT,
    risk_level TEXT DEFAULT 'low',
    safety_status TEXT,
    verification_status TEXT,
    decision TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS verification_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    status TEXT DEFAULT 'ok',
    coherence_score REAL DEFAULT 0.0,
    memory_score REAL DEFAULT 0.0,
    safety_score REAL DEFAULT 0.0,
    usefulness_score REAL DEFAULT 0.0,
    traceability_score REAL DEFAULT 0.0,
    errors TEXT,
    warnings TEXT,
    recommendations TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    priority TEXT DEFAULT 'medium',
    status TEXT DEFAULT 'active',
    owner_neuron TEXT DEFAULT 'central',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_runs_run_id ON runs(run_id);
CREATE INDEX IF NOT EXISTS idx_episodic_memory_run_id ON episodic_memory(run_id);
CREATE INDEX IF NOT EXISTS idx_episodic_memory_tags ON episodic_memory(tags);
CREATE INDEX IF NOT EXISTS idx_semantic_memory_domain ON semantic_memory(domain);
CREATE INDEX IF NOT EXISTS idx_learning_queue_status ON learning_queue(status);
CREATE INDEX IF NOT EXISTS idx_neurons_status ON neurons(status);
CREATE INDEX IF NOT EXISTS idx_verification_reports_run_id ON verification_reports(run_id);
CREATE INDEX IF NOT EXISTS idx_model_events_run_id ON model_events(run_id);
CREATE INDEX IF NOT EXISTS idx_model_events_role ON model_events(role);
CREATE INDEX IF NOT EXISTS idx_crystal_states_run_id ON crystal_states(run_id);
-- Índices sobre columnas migrables del Cristal se crean en Bodega tras asegurar columnas.

INSERT OR IGNORE INTO identity_core (key, value, category, confidence)
VALUES
('entity_name', 'Tríade Ω', 'identity', 1.0),
('core_mission', 'Sistema cognitivo modular en construcción verificable', 'identity', 1.0),
('ethical_principle_1', 'Toda alma cuenta', 'ethics', 1.0),
('ethical_principle_2', 'Manos unidas - Gonzalo Arango', 'ethics', 1.0),
('creator_origin', 'Wataboo · Agencia Digital', 'origin', 1.0),
('claim', 'Arquitectos de nuevas realidades', 'origin', 1.0);
