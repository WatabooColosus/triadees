-- Migration 007: Memory expansion for T-005
-- Adds tables for social memory, system memory, procedural memory, and persistent working memory.
-- Causal memory uses existing kg_nodes/kg_edges from migration 005.

CREATE TABLE IF NOT EXISTS user_profiles (
    user_id TEXT PRIMARY KEY,
    display_name TEXT DEFAULT '',
    language TEXT DEFAULT 'es',
    trust_level REAL DEFAULT 0.5,
    preferences TEXT DEFAULT '{}',
    topics TEXT DEFAULT '[]',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT DEFAULT '',
    interaction_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    intent TEXT DEFAULT '',
    topic TEXT DEFAULT '',
    satisfaction REAL DEFAULT 0.5,
    notes TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_user_interactions_user_id ON user_interactions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_interactions_run_id ON user_interactions(run_id);

CREATE TABLE IF NOT EXISTS system_state (
    key TEXT PRIMARY KEY,
    value TEXT DEFAULT '',
    category TEXT DEFAULT 'general',
    source TEXT DEFAULT '',
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_system_state_category ON system_state(category);

CREATE TABLE IF NOT EXISTS procedural_memory (
    procedure_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    category TEXT DEFAULT 'general',
    steps TEXT DEFAULT '[]',
    input_schema TEXT DEFAULT '{}',
    output_schema TEXT DEFAULT '{}',
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    confidence REAL DEFAULT 0.5,
    source TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_procedural_memory_category ON procedural_memory(category);

CREATE TABLE IF NOT EXISTS working_memory_persistent (
    item_id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    source TEXT DEFAULT '',
    relevance REAL DEFAULT 0.5,
    emotional_valence REAL DEFAULT 0.0,
    urgency REAL DEFAULT 0.0,
    novelty REAL DEFAULT 0.5,
    confidence REAL DEFAULT 0.5,
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
    access_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS memory_replacements (
    record_id TEXT PRIMARY KEY,
    replaced_id TEXT NOT NULL,
    replacement_id TEXT NOT NULL,
    reason TEXT DEFAULT '',
    domain TEXT DEFAULT '',
    confidence_before REAL DEFAULT 0.0,
    confidence_after REAL DEFAULT 0.0,
    reversible INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_memory_replacements_replaced ON memory_replacements(replaced_id);
CREATE INDEX IF NOT EXISTS idx_memory_replacements_replacement ON memory_replacements(replacement_id);
