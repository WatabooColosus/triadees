CREATE TABLE IF NOT EXISTS governed_plan_dispatches (
    plan_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    task_id TEXT,
    capability_id TEXT NOT NULL,
    policy_decision_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    approval_required INTEGER NOT NULL DEFAULT 0,
    rollback_available INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(plan_id, step_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_plan_dispatch_task
    ON governed_plan_dispatches(task_id) WHERE task_id IS NOT NULL;
