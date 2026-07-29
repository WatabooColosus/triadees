-- Canonical autonomous-task transition audit. Additive and SQLite compatible.
CREATE TABLE IF NOT EXISTS autonomous_task_transitions (
    transition_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    worker_id TEXT,
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    reason TEXT,
    result_ref TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(task_id) REFERENCES autonomous_tasks(task_id)
);
CREATE INDEX IF NOT EXISTS idx_autonomous_task_transitions_task
    ON autonomous_task_transitions(task_id, transition_id);
