-- Runtime resilience v1. Aditiva, idempotente y compatible con SQLite.
CREATE TABLE IF NOT EXISTS autonomous_tasks (
    task_id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    worker_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    priority INTEGER NOT NULL DEFAULT 50,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    lease_acquired_at TEXT,
    lease_expires_at TEXT,
    heartbeat_at TEXT,
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    retry_after TEXT,
    last_error TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    payload_hash TEXT NOT NULL,
    result_ref TEXT,
    rollback_ref TEXT
);
CREATE INDEX IF NOT EXISTS idx_autonomous_tasks_claim
    ON autonomous_tasks(status, retry_after, priority, created_at);
CREATE INDEX IF NOT EXISTS idx_autonomous_tasks_lease
    ON autonomous_tasks(lease_expires_at, worker_id);

CREATE TABLE IF NOT EXISTS resource_ledger (
    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT,
    worker_id TEXT,
    neuron_id TEXT,
    recorded_day TEXT NOT NULL,
    cpu_seconds REAL NOT NULL DEFAULT 0,
    gpu_seconds REAL NOT NULL DEFAULT 0,
    ram_peak_mb REAL NOT NULL DEFAULT 0,
    vram_peak_mb REAL NOT NULL DEFAULT 0,
    tokens_input INTEGER NOT NULL DEFAULT 0,
    tokens_output INTEGER NOT NULL DEFAULT 0,
    network_bytes INTEGER NOT NULL DEFAULT 0,
    disk_bytes_read INTEGER NOT NULL DEFAULT 0,
    disk_bytes_written INTEGER NOT NULL DEFAULT 0,
    duration_seconds REAL NOT NULL DEFAULT 0,
    model TEXT,
    estimated_energy_wh REAL NOT NULL DEFAULT 0,
    temperature_peak_c REAL,
    success INTEGER NOT NULL,
    task_class TEXT NOT NULL DEFAULT 'general',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_resource_ledger_day ON resource_ledger(recorded_day, task_class);
CREATE INDEX IF NOT EXISTS idx_resource_ledger_task ON resource_ledger(task_id, worker_id, neuron_id);

CREATE TABLE IF NOT EXISTS runtime_health_snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    state TEXT NOT NULL,
    reason_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runtime_recovery_events (
    recovery_id TEXT PRIMARY KEY,
    cause TEXT NOT NULL,
    state TEXT NOT NULL,
    snapshot_ref TEXT,
    actions_json TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);
