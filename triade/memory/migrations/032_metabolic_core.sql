CREATE TABLE IF NOT EXISTS metabolic_cycle (
    cycle_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    mode TEXT NOT NULL DEFAULT 'full',
    error TEXT,
    recovery_ref TEXT,
    summary_json TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS metabolic_needs (
    need_id TEXT PRIMARY KEY,
    cycle_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 50,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    estimated_cost_json TEXT NOT NULL DEFAULT '{}',
    risk TEXT NOT NULL DEFAULT 'low',
    status TEXT NOT NULL DEFAULT 'pending',
    authorization_policy TEXT NOT NULL DEFAULT 'always',
    success_condition TEXT,
    expires_at TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    result_json TEXT DEFAULT '{}',
    FOREIGN KEY (cycle_id) REFERENCES metabolic_cycle(cycle_id)
);

CREATE TABLE IF NOT EXISTS metabolic_receipts (
    receipt_id TEXT PRIMARY KEY,
    cycle_id INTEGER NOT NULL,
    need_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    cpu_seconds REAL DEFAULT 0.0,
    ram_mb REAL DEFAULT 0.0,
    duration_ms REAL DEFAULT 0.0,
    artifact_ref TEXT,
    effect_receipt_ref TEXT,
    error TEXT,
    evidence_json TEXT DEFAULT '{}',
    FOREIGN KEY (cycle_id) REFERENCES metabolic_cycle(cycle_id),
    FOREIGN KEY (need_id) REFERENCES metabolic_needs(need_id)
);

CREATE TABLE IF NOT EXISTS metabolic_signals (
    signal_id TEXT PRIMARY KEY,
    cycle_id INTEGER NOT NULL,
    stage TEXT NOT NULL,
    need_id TEXT,
    signal_status TEXT NOT NULL,
    reason TEXT,
    timestamp TEXT NOT NULL,
    budget_json TEXT DEFAULT '{}',
    FOREIGN KEY (cycle_id) REFERENCES metabolic_cycle(cycle_id)
);

-- `metabolic_config` vivio aqui hasta el 2026-08-08. La retira `034`, y su
-- CREATE no puede quedarse: este fichero no es solo historia, `MetabolicCoordinator.
-- _ensure_tables()` lo reejecuta en cada ciclo. Con el CREATE dentro, la retirada
-- se deshacia sola a los minutos y en una base nueva nunca llegaba a aplicarse.
-- La configuracion del metabolismo vive en `triade.yml`, que es su fuente real.
