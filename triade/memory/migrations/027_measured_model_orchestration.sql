CREATE TABLE IF NOT EXISTS measured_model_routes (
    route_id TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    selected_model TEXT,
    reason TEXT NOT NULL,
    fallback_used INTEGER NOT NULL CHECK (fallback_used IN (0, 1)),
    requirements_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_adoption_decisions (
    decision_id TEXT PRIMARY KEY,
    baseline_model TEXT NOT NULL,
    candidate_routes_json TEXT NOT NULL,
    baseline_metrics_json TEXT,
    candidate_metrics_json TEXT,
    adopted INTEGER NOT NULL CHECK (adopted IN (0, 1)),
    rollback_ref TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
