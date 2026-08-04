-- Fase 3: estados gobernados, auditoría y observaciones de aprendizaje.
-- Aditiva e idempotente; no modifica filas históricas automáticamente.

CREATE TABLE IF NOT EXISTS goal_events (
    event_id TEXT PRIMARY KEY,
    goal_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_goal_events_goal
ON goal_events(goal_id, created_at, event_id);

CREATE TABLE IF NOT EXISTS goal_learning_observations (
    observation_id TEXT PRIMARY KEY,
    goal_id TEXT NOT NULL,
    task_id TEXT,
    disposition TEXT NOT NULL,
    outcome_status TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_goal_learning_goal
ON goal_learning_observations(goal_id, created_at, observation_id);
