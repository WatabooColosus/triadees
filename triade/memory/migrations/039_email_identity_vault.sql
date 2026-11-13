CREATE TABLE IF NOT EXISTS auth_email_identities (
    user_id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    verified_at TEXT,
    verification_hash TEXT,
    verification_expires_at REAL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES auth_users(user_id)
);

CREATE TABLE IF NOT EXISTS auth_api_keys (
    key_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    label TEXT NOT NULL,
    ciphertext TEXT NOT NULL,
    key_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    revoked_at TEXT,
    FOREIGN KEY (user_id) REFERENCES auth_users(user_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_auth_api_keys_active
    ON auth_api_keys(user_id, provider, label) WHERE revoked_at IS NULL;
