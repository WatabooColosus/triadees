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
