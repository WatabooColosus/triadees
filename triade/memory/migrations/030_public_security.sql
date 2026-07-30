CREATE TABLE IF NOT EXISTS auth_users (
    user_id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('viewer', 'operator', 'admin')),
    tenant_id TEXT NOT NULL,
    disabled INTEGER NOT NULL DEFAULT 0,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until REAL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    session_id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL,
    expires_at REAL NOT NULL,
    revoked_at REAL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES auth_users(user_id)
);

CREATE TABLE IF NOT EXISTS auth_rate_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    window_key INTEGER NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_auth_rate_window ON auth_rate_events(user_id, window_key);

CREATE TABLE IF NOT EXISTS auth_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor TEXT NOT NULL,
    tenant_id TEXT,
    action TEXT NOT NULL,
    outcome TEXT NOT NULL,
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL
);
