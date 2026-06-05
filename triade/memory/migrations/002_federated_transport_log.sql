-- Triade Omega · Federated Transport Log
-- Bitacora opcional para auditoria de mensajes HTTP firmados.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS federated_transport_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    nonce TEXT,
    signature_alg TEXT DEFAULT 'hmac-sha256',
    payload_hash TEXT,
    status TEXT DEFAULT 'accepted',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_federated_transport_node_id ON federated_transport_log(node_id);
CREATE INDEX IF NOT EXISTS idx_federated_transport_created_at ON federated_transport_log(created_at);
CREATE INDEX IF NOT EXISTS idx_federated_transport_nonce ON federated_transport_log(nonce);

