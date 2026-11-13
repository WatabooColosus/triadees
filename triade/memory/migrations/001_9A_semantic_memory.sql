-- Tríade Ω · Semantic Memory 1.9A
-- Almacenamiento documental y vectorial preparado para embeddings locales.
-- Esta migración no genera embeddings; solo crea estructura persistente.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS semantic_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    normalized_content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    domain TEXT DEFAULT 'general',
    source_type TEXT DEFAULT 'manual',
    source_ref TEXT,
    metadata TEXT,
    status TEXT DEFAULT 'candidate',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS semantic_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    vector_json TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector_norm REAL NOT NULL,
    status TEXT DEFAULT 'stored',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(document_id, embedding_model),
    FOREIGN KEY (document_id) REFERENCES semantic_documents(document_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_semantic_documents_domain ON semantic_documents(domain);
CREATE INDEX IF NOT EXISTS idx_semantic_documents_hash ON semantic_documents(content_hash);
CREATE INDEX IF NOT EXISTS idx_semantic_documents_status ON semantic_documents(status);
CREATE INDEX IF NOT EXISTS idx_semantic_embeddings_document_id ON semantic_embeddings(document_id);
CREATE INDEX IF NOT EXISTS idx_semantic_embeddings_model ON semantic_embeddings(embedding_model);
