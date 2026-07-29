CREATE TABLE IF NOT EXISTS governed_research_runs (
    research_id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    trigger TEXT NOT NULL,
    scope TEXT NOT NULL,
    allowed_sources_json TEXT NOT NULL,
    minimum_independent_sources INTEGER NOT NULL,
    status TEXT NOT NULL,
    sources_json TEXT NOT NULL,
    source_failures_json TEXT NOT NULL,
    claims_json TEXT NOT NULL,
    contradictions_json TEXT NOT NULL,
    unresolved_questions_json TEXT NOT NULL,
    confidence REAL NOT NULL,
    evidence_bundle_json TEXT NOT NULL,
    candidate_id TEXT,
    created_at TEXT NOT NULL
);
