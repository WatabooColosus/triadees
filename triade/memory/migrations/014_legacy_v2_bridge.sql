-- Explicit, reversible linkage while the legacy queue remains readable.
ALTER TABLE worker_tasks ADD COLUMN autonomous_task_id TEXT;
ALTER TABLE worker_tasks ADD COLUMN migration_status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE worker_tasks ADD COLUMN delegated_at TEXT;
ALTER TABLE worker_tasks ADD COLUMN reconciled_at TEXT;
ALTER TABLE worker_tasks ADD COLUMN migration_error TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_worker_tasks_autonomous_task
    ON worker_tasks(autonomous_task_id) WHERE autonomous_task_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_worker_tasks_migration
    ON worker_tasks(migration_status, status);
