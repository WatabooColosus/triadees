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
    triggers TEXT,
    inputs_allowed TEXT,
    outputs_allowed TEXT,
    forbidden_actions TEXT,
    success_metrics TEXT,
    evidence_required TEXT,
    activation_policy TEXT,
    contract_json TEXT,
    status TEXT DEFAULT 'candidate',
    created_by TEXT DEFAULT 'central',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE IF NOT EXISTS neuron_activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    neuron_id INTEGER,
    name TEXT NOT NULL,
    domain TEXT,
    status TEXT,
    activated INTEGER DEFAULT 1,
    diagnosis_count INTEGER DEFAULT 0,
    test_plan_count INTEGER DEFAULT 0,
    policy TEXT,
    activity_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES runs(run_id),
    FOREIGN KEY (neuron_id) REFERENCES neurons(id)
);

CREATE INDEX IF NOT EXISTS idx_neuron_activity_run_id ON neuron_activity(run_id);
CREATE INDEX IF NOT EXISTS idx_neuron_activity_name ON neuron_activity(name);
CREATE INDEX IF NOT EXISTS idx_neuron_activity_neuron_id ON neuron_activity(neuron_id);
CREATE INDEX IF NOT EXISTS idx_neuron_activity_created_at ON neuron_activity(created_at);

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
    capabilities TEXT,
    capability_status TEXT DEFAULT 'unknown',
    last_seen_at TEXT,
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
    reason TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS verification_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    scope TEXT,
    status TEXT DEFAULT 'ok',
    score REAL,
    coherence_score REAL DEFAULT 0.0,
    memory_score REAL DEFAULT 0.0,
    safety_score REAL DEFAULT 0.0,
    usefulness_score REAL DEFAULT 0.0,
    traceability_score REAL DEFAULT 0.0,
    findings TEXT,
    errors TEXT,
    warnings TEXT,
    recommendations TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trust_levels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL UNIQUE,
    trust_level REAL DEFAULT 0.0,
    criteria_avg_reward REAL DEFAULT 0.0,
    criteria_verification_pass_rate REAL DEFAULT 0.0,
    criteria_error_rate REAL DEFAULT 0.0,
    criteria_run_count INTEGER DEFAULT 0,
    last_updated TEXT DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO trust_levels (domain, trust_level) VALUES ('consolidation', 0.0);
INSERT OR IGNORE INTO trust_levels (domain, trust_level) VALUES ('code_modification', 0.0);
INSERT OR IGNORE INTO trust_levels (domain, trust_level) VALUES ('identity_evolution', 0.0);

CREATE TABLE IF NOT EXISTS reinforcement_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    reward REAL DEFAULT 0.0,
    hypothalamus_quality REAL DEFAULT 0.0,
    central_quality REAL DEFAULT 0.0,
    coherence_score REAL DEFAULT 0.0,
    mood_valence_before REAL,
    mood_valence_after REAL,
    fatigue_before REAL,
    fatigue_after REAL,
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

-- Triade Living Workers storage
CREATE TABLE IF NOT EXISTS worker_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    priority INTEGER DEFAULT 50,
    payload_json TEXT,
    result_json TEXT,
    safety_status TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    finished_at TEXT,
    error TEXT,
    run_ref TEXT
);

CREATE TABLE IF NOT EXISTS worker_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_ref TEXT NOT NULL UNIQUE,
    status TEXT DEFAULT 'created',
    mode TEXT DEFAULT 'once',
    dry_run INTEGER DEFAULT 0,
    max_iterations INTEGER DEFAULT 1,
    sleep_seconds REAL DEFAULT 0.0,
    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    summary_json TEXT,
    artifact_dir TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS worker_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_ref TEXT,
    task_id INTEGER,
    task_type TEXT,
    event_type TEXT NOT NULL,
    status TEXT DEFAULT 'ok',
    message TEXT,
    payload_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES worker_tasks(id)
);

CREATE TABLE IF NOT EXISTS worker_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    value_json TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_worker_tasks_status ON worker_tasks(status);
CREATE INDEX IF NOT EXISTS idx_worker_tasks_type ON worker_tasks(task_type);
CREATE INDEX IF NOT EXISTS idx_worker_tasks_priority ON worker_tasks(priority);
CREATE INDEX IF NOT EXISTS idx_worker_events_run_ref ON worker_events(run_ref);
CREATE INDEX IF NOT EXISTS idx_worker_events_task_type ON worker_events(task_type);
CREATE INDEX IF NOT EXISTS idx_worker_runs_run_ref ON worker_runs(run_ref);

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

CREATE TABLE IF NOT EXISTS hypothalamus_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    mood_valence REAL DEFAULT 0.0,
    mood_arousal REAL DEFAULT 0.0,
    mood_dominance REAL DEFAULT 0.0,
    primary_emotion TEXT DEFAULT 'neutral',
    fatigue REAL DEFAULT 0.0,
    pv7_baseline TEXT,
    run_count INTEGER DEFAULT 0,
    last_active_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS hypothalamus_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text_hash TEXT NOT NULL,
    text_preview TEXT DEFAULT '',
    intent TEXT NOT NULL DEFAULT 'conversation',
    tone TEXT NOT NULL DEFAULT 'constructive',
    risk TEXT NOT NULL DEFAULT 'low',
    urgency TEXT NOT NULL DEFAULT 'medium',
    confidence REAL DEFAULT 0.8,
    hit_count INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_used_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_hypothalamus_patterns_hash ON hypothalamus_patterns(text_hash);

CREATE INDEX IF NOT EXISTS idx_crystal_states_run_id ON crystal_states(run_id);
-- Índices sobre columnas migrables del Cristal se crean en Bodega tras asegurar columnas.

CREATE TABLE IF NOT EXISTS auto_identity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trait_key TEXT NOT NULL UNIQUE,
    trait_value TEXT NOT NULL,
    category TEXT DEFAULT 'discovered',
    source_ref TEXT,
    confidence REAL DEFAULT 0.3,
    status TEXT DEFAULT 'candidate',
    evidence_count INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- ── Neuron Missions ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS neuron_missions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    neuron_id INTEGER,
    title TEXT NOT NULL,
    mission TEXT NOT NULL,
    domain TEXT NOT NULL DEFAULT 'general',
    allowed_sources_json TEXT DEFAULT '[]',
    allowed_actions_json TEXT DEFAULT '[]',
    schedule_hint TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'candidate',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    metrics_json TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_neuron_missions_status ON neuron_missions(status);
CREATE INDEX IF NOT EXISTS idx_neuron_missions_neuron_id ON neuron_missions(neuron_id);

CREATE TABLE IF NOT EXISTS neuron_work_cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id INTEGER NOT NULL,
    neuron_id INTEGER,
    cycle_type TEXT NOT NULL DEFAULT 'observation',
    input_summary TEXT DEFAULT '',
    output_summary TEXT DEFAULT '',
    evidence_refs_json TEXT DEFAULT '[]',
    duration_ms INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'completed',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (mission_id) REFERENCES neuron_missions(id)
);

CREATE INDEX IF NOT EXISTS idx_neuron_work_cycles_mission ON neuron_work_cycles(mission_id);

CREATE TABLE IF NOT EXISTS neuron_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id INTEGER NOT NULL,
    neuron_id INTEGER,
    evidence_type TEXT NOT NULL DEFAULT 'observation',
    source TEXT NOT NULL DEFAULT 'worker',
    content TEXT DEFAULT '',
    refs_json TEXT DEFAULT '[]',
    score REAL DEFAULT 0.0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (mission_id) REFERENCES neuron_missions(id)
);

CREATE INDEX IF NOT EXISTS idx_neuron_evidence_mission ON neuron_evidence(mission_id);

CREATE TABLE IF NOT EXISTS neuron_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id INTEGER NOT NULL,
    neuron_id INTEGER,
    score_type TEXT NOT NULL DEFAULT 'composite',
    value REAL NOT NULL DEFAULT 0.0,
    components_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (mission_id) REFERENCES neuron_missions(id)
);

CREATE INDEX IF NOT EXISTS idx_neuron_scores_mission ON neuron_scores(mission_id);

INSERT OR IGNORE INTO identity_core (key, value, category, confidence)
VALUES
('entity_name', 'Tríade Ω', 'identity', 1.0),
('core_mission', 'Sistema cognitivo modular en construcción verificable', 'identity', 1.0),
('ethical_principle_1', 'Toda alma cuenta', 'ethics', 1.0),
('ethical_principle_2', 'Manos unidas - Gonzalo Arango', 'ethics', 1.0),
('creator_origin', 'Wataboo · Agencia Digital', 'origin', 1.0),
('claim', 'Arquitectos de nuevas realidades', 'origin', 1.0);
