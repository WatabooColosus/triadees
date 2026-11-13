-- Persist baseline-first education coordination across worker restarts.
CREATE TABLE IF NOT EXISTS neuron_education_coordination (
    coordination_id TEXT PRIMARY KEY,
    neuron_id INTEGER NOT NULL,
    case_id TEXT NOT NULL,
    session_id TEXT,
    phase TEXT NOT NULL CHECK (phase IN ('pre','post')),
    state TEXT NOT NULL CHECK (state IN (
        'baseline_requested','baseline_registered','session_created',
        'post_requested','resolved','failed'
    )),
    task_id TEXT,
    run_id TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(neuron_id, case_id, phase, session_id)
);
CREATE INDEX IF NOT EXISTS idx_education_coordination_state
    ON neuron_education_coordination(state, updated_at);
