-- Estado de modulación relacional PV-7 por usuario y sesión.

CREATE TABLE IF NOT EXISTS relational_modulation_states (
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    baseline_json TEXT NOT NULL,
    state_json TEXT NOT NULL,
    event_count INTEGER NOT NULL DEFAULT 0,
    last_event_at TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, session_id)
);

CREATE TABLE IF NOT EXISTS relational_modulation_events (
    event_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    before_json TEXT NOT NULL,
    requested_delta_json TEXT NOT NULL,
    applied_delta_json TEXT NOT NULL,
    after_json TEXT NOT NULL,
    explanation TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    rolled_back INTEGER NOT NULL DEFAULT 0 CHECK (rolled_back IN (0, 1)),
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id, session_id)
        REFERENCES relational_modulation_states(user_id, session_id)
);

CREATE INDEX IF NOT EXISTS idx_relational_events_scope
    ON relational_modulation_events(user_id, session_id, created_at);
