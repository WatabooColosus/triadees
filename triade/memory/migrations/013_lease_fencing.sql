-- Lease heartbeat history. Existing columns are added idempotently by Python
-- because SQLite lacks ALTER TABLE ADD COLUMN IF NOT EXISTS.
CREATE TABLE IF NOT EXISTS autonomous_lease_heartbeats (
    heartbeat_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    lease_generation INTEGER NOT NULL,
    renewed INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(task_id) REFERENCES autonomous_tasks(task_id)
);
CREATE INDEX IF NOT EXISTS idx_autonomous_lease_heartbeats_task
    ON autonomous_lease_heartbeats(task_id, lease_generation, heartbeat_id);
