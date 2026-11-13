CREATE TABLE IF NOT EXISTS resource_measurements (
    measurement_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ledger_entry_id INTEGER NOT NULL,
    resource_name TEXT NOT NULL,
    value REAL,
    unit TEXT NOT NULL,
    measurement_type TEXT NOT NULL,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    FOREIGN KEY(ledger_entry_id) REFERENCES resource_ledger(entry_id)
);
CREATE INDEX IF NOT EXISTS idx_resource_measurements_entry
    ON resource_measurements(ledger_entry_id, resource_name);
