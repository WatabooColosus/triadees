-- Runtime v2 canonical authority. Legacy remains readable and reconcilable.
CREATE TABLE IF NOT EXISTS runtime_queue_compatibility (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    mode TEXT NOT NULL,
    legacy_writes_enabled INTEGER NOT NULL CHECK (legacy_writes_enabled IN (0, 1)),
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    rollback_reason TEXT
);

INSERT OR IGNORE INTO runtime_queue_compatibility
    (singleton, mode, legacy_writes_enabled, updated_at, updated_by)
VALUES (1, 'v2_canonical', 0, CURRENT_TIMESTAMP, 'migration-019');

CREATE TABLE IF NOT EXISTS runtime_queue_compatibility_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_mode TEXT NOT NULL,
    to_mode TEXT NOT NULL,
    legacy_writes_enabled INTEGER NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS block_new_legacy_worker_tasks
BEFORE INSERT ON worker_tasks
WHEN (SELECT legacy_writes_enabled FROM runtime_queue_compatibility WHERE singleton=1) = 0
BEGIN
    SELECT RAISE(ABORT, 'legacy_worker_task_writes_disabled');
END;
