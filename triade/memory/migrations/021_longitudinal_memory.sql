-- Memoria longitudinal gobernada y aislada por scope.

CREATE TABLE IF NOT EXISTS longitudinal_memories (
    memory_id TEXT PRIMARY KEY,
    memory_type TEXT NOT NULL CHECK (memory_type IN
        ('fact', 'preference', 'correction', 'relationship', 'decision',
         'restriction', 'project', 'temporal')),
    memory_key TEXT NOT NULL,
    memory_value TEXT NOT NULL,
    normalized_value TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN
        ('observed', 'candidate', 'verified', 'stable', 'contradicted',
         'expired', 'quarantined')),
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    domain TEXT NOT NULL DEFAULT 'general',
    source_ref TEXT NOT NULL,
    source_type TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    valid_from TEXT,
    valid_until TEXT,
    expires_at TEXT,
    confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    supersedes_id TEXT,
    contradiction_of_id TEXT,
    review_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (supersedes_id) REFERENCES longitudinal_memories(memory_id),
    FOREIGN KEY (contradiction_of_id) REFERENCES longitudinal_memories(memory_id)
);

CREATE INDEX IF NOT EXISTS idx_longitudinal_scope
    ON longitudinal_memories(user_id, project_id, domain, memory_key, status);
CREATE INDEX IF NOT EXISTS idx_longitudinal_expiry
    ON longitudinal_memories(status, expires_at);

CREATE TABLE IF NOT EXISTS longitudinal_memory_events (
    event_id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    previous_status TEXT,
    new_status TEXT,
    actor TEXT NOT NULL,
    reason TEXT NOT NULL,
    evidence_ref TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (memory_id) REFERENCES longitudinal_memories(memory_id)
);
