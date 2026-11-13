-- TriadeOS: Knowledge Graph, Event Engine state, Neuron Scheduler state

-- ============================================================
-- KNOWLEDGE GRAPH
-- ============================================================

CREATE TABLE IF NOT EXISTS kg_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_type TEXT NOT NULL CHECK(node_type IN ('fact','concept','entity','claim','hypothesis')),
    content TEXT NOT NULL,
    domain TEXT,
    evidence_level TEXT NOT NULL DEFAULT 'candidate'
        CHECK(evidence_level IN ('candidate','contested','corroborated','established','canonical')),
    confidence REAL NOT NULL DEFAULT 0.0 CHECK(confidence BETWEEN 0.0 AND 1.0),
    source_ref TEXT,
    neuron_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS kg_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES kg_nodes(id) ON DELETE CASCADE,
    target_id INTEGER NOT NULL REFERENCES kg_nodes(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL
        CHECK(relation_type IN ('supports','contradicts','refines','depends_on','originates_from','related_to')),
    weight REAL NOT NULL DEFAULT 1.0 CHECK(weight BETWEEN 0.0 AND 1.0),
    evidence_refs TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kg_contradictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_a_id INTEGER NOT NULL REFERENCES kg_nodes(id),
    node_b_id INTEGER NOT NULL REFERENCES kg_nodes(id),
    description TEXT,
    resolution_status TEXT NOT NULL DEFAULT 'unresolved'
        CHECK(resolution_status IN ('unresolved','investigating','resolved','accepted')),
    resolution TEXT,
    resolved_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_kg_nodes_domain ON kg_nodes(domain);
CREATE INDEX IF NOT EXISTS idx_kg_nodes_evidence ON kg_nodes(evidence_level);
CREATE INDEX IF NOT EXISTS idx_kg_nodes_type ON kg_nodes(node_type);
CREATE INDEX IF NOT EXISTS idx_kg_edges_source ON kg_edges(source_id);
CREATE INDEX IF NOT EXISTS idx_kg_edges_target ON kg_edges(target_id);
CREATE INDEX IF NOT EXISTS idx_kg_edges_relation ON kg_edges(relation_type);
CREATE INDEX IF NOT EXISTS idx_kg_contradictions_status ON kg_contradictions(resolution_status);

-- ============================================================
-- EVENT ENGINE STATE
-- ============================================================

CREATE TABLE IF NOT EXISTS triadeos_event_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- ============================================================
-- NEURON SCHEDULER STATE
-- ============================================================

CREATE TABLE IF NOT EXISTS neuron_priority_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    neuron_id INTEGER NOT NULL,
    priority_score REAL NOT NULL,
    evidence_gap REAL,
    staleness REAL,
    impact REAL,
    reputation REAL,
    resource_freshness REAL,
    reason TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_neuron_priority_log_neuron ON neuron_priority_log(neuron_id);
CREATE INDEX IF NOT EXISTS idx_neuron_priority_log_created ON neuron_priority_log(created_at);
