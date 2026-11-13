-- Migration 006: Hipotálamo PV-14
-- Expande hypothalamus_state con señales de hardware y carga cognitiva.
-- Crea tabla hardware_senses para persistir snapshots del sistema.

-- Expandir hypothalamus_state con nuevas columnas
ALTER TABLE hypothalamus_state ADD COLUMN cpu_load REAL DEFAULT 0.0;
ALTER TABLE hypothalamus_state ADD COLUMN ram_usage REAL DEFAULT 0.0;
ALTER TABLE hypothalamus_state ADD COLUMN gpu_utilization REAL DEFAULT 0.0;
ALTER TABLE hypothalamus_state ADD COLUMN gpu_memory_used REAL DEFAULT 0.0;
ALTER TABLE hypothalamus_state ADD COLUMN gpu_temperature INTEGER DEFAULT 0;
ALTER TABLE hypothalamus_state ADD COLUMN cognitive_load REAL DEFAULT 0.0;
ALTER TABLE hypothalamus_state ADD COLUMN curiosity REAL DEFAULT 0.0;
ALTER TABLE hypothalamus_state ADD COLUMN uncertainty REAL DEFAULT 0.0;
ALTER TABLE hypothalamus_state ADD COLUMN tensions_json TEXT DEFAULT '{}';
ALTER TABLE hypothalamus_state ADD COLUMN cognitive_snapshot_json TEXT DEFAULT '{}';

-- Tabla de lecturas de hardware (snapshots)
CREATE TABLE IF NOT EXISTS hardware_senses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_hardware_senses_recorded_at ON hardware_senses(recorded_at);
CREATE INDEX IF NOT EXISTS idx_hypothalamus_state_run_id ON hypothalamus_state(run_id);
