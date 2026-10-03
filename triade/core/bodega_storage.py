"""Infraestructura SQLite y migraciones de Bodega, separada de su API cognitiva."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from triade.db import sqlite3


class BodegaStorage:
    CRYSTAL_V2_COLUMNS: ClassVar = {
        "pv7_score": "REAL DEFAULT 0.5",
        "stability": "REAL DEFAULT 0.5",
        "intensity": "REAL DEFAULT 0.5",
        "q_crystal": "REAL DEFAULT 0.0",
        "ethics_vector": "TEXT",
        "regulation_notes": "TEXT",
        "previous_q_crystal": "REAL",
        "previous_stability": "REAL",
        "q_delta": "REAL DEFAULT 0.0",
        "stability_delta": "REAL DEFAULT 0.0",
        "temporal_status": "TEXT DEFAULT 'baseline'",
        "temporal_alerts": "TEXT",
        "history_window": "INTEGER DEFAULT 0",
        "context_scope": "TEXT DEFAULT 'source_intent'",
        "context_key": "TEXT",
        "comparison_basis": "TEXT",
        "source": "TEXT",
        "intent": "TEXT",
        "session_id": "TEXT",
        "project_id": "TEXT",
        "active_neuron": "TEXT",
    }

    def __init__(
        self,
        db_path: str | Path = "triade/memory/triade.db",
        semantic_search_engine: Any | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.schema_path = (
            Path(__file__).resolve().parents[2] / "triade/memory/schemas.sql"
        )
        self.semantic_search_engine = semantic_search_engine
        self.fts5_enabled = False
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        if not self.schema_path.exists():
            raise FileNotFoundError(
                f"No existe el esquema de memoria: {self.schema_path}"
            )
        with self._connect() as conn:
            conn.executescript(self.schema_path.read_text(encoding="utf-8"))
            self._migrate_crystal_v2(conn)
            self.fts5_enabled = self._init_fts5(conn)


    @staticmethod
    def _init_fts5(conn: sqlite3.Connection) -> bool:
        """Índices full-text opcionales; falla seguro si FTS5 no está compilado."""
        try:
            existing = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name IN ('semantic_documents_fts','episodic_memory_fts')"
                ).fetchall()
            }
            if "semantic_documents_fts" not in existing:
                conn.executescript(
                    """
                    CREATE VIRTUAL TABLE semantic_documents_fts USING fts5(
                        content, domain,
                        content='semantic_documents', content_rowid='id'
                    );
                    CREATE TRIGGER semantic_documents_fts_ai AFTER INSERT ON semantic_documents BEGIN
                      INSERT INTO semantic_documents_fts(rowid, content, domain)
                      VALUES (new.id, new.content, new.domain);
                    END;
                    CREATE TRIGGER semantic_documents_fts_ad AFTER DELETE ON semantic_documents BEGIN
                      INSERT INTO semantic_documents_fts(
                        semantic_documents_fts, rowid, content, domain
                      ) VALUES ('delete', old.id, old.content, old.domain);
                    END;
                    CREATE TRIGGER semantic_documents_fts_au AFTER UPDATE ON semantic_documents BEGIN
                      INSERT INTO semantic_documents_fts(
                        semantic_documents_fts, rowid, content, domain
                      ) VALUES ('delete', old.id, old.content, old.domain);
                      INSERT INTO semantic_documents_fts(rowid, content, domain)
                      VALUES (new.id, new.content, new.domain);
                    END;
                    INSERT INTO semantic_documents_fts(semantic_documents_fts)
                    VALUES ('rebuild');
                    """
                )
            if "episodic_memory_fts" not in existing:
                conn.executescript(
                    """
                    CREATE VIRTUAL TABLE episodic_memory_fts USING fts5(
                        title, content, summary, tags,
                        content='episodic_memory', content_rowid='id'
                    );
                    CREATE TRIGGER episodic_memory_fts_ai AFTER INSERT ON episodic_memory BEGIN
                      INSERT INTO episodic_memory_fts(rowid, title, content, summary, tags)
                      VALUES (new.id, new.title, new.content, new.summary, new.tags);
                    END;
                    CREATE TRIGGER episodic_memory_fts_ad AFTER DELETE ON episodic_memory BEGIN
                      INSERT INTO episodic_memory_fts(
                        episodic_memory_fts, rowid, title, content, summary, tags
                      ) VALUES (
                        'delete', old.id, old.title, old.content, old.summary, old.tags
                      );
                    END;
                    CREATE TRIGGER episodic_memory_fts_au AFTER UPDATE ON episodic_memory BEGIN
                      INSERT INTO episodic_memory_fts(
                        episodic_memory_fts, rowid, title, content, summary, tags
                      ) VALUES (
                        'delete', old.id, old.title, old.content, old.summary, old.tags
                      );
                      INSERT INTO episodic_memory_fts(rowid, title, content, summary, tags)
                      VALUES (new.id, new.title, new.content, new.summary, new.tags);
                    END;
                    INSERT INTO episodic_memory_fts(episodic_memory_fts)
                    VALUES ('rebuild');
                    """
                )
            return True
        except sqlite3.OperationalError:
            return False

    def _migrate_crystal_v2(self, conn: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(crystal_states)").fetchall()
        }
        for column, definition in self.CRYSTAL_V2_COLUMNS.items():
            if column not in columns:
                conn.execute(
                    f"ALTER TABLE crystal_states ADD COLUMN {column} {definition}"
                )
        for column in ("run_id", "q_crystal", "temporal_status", "context_key"):
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_crystal_states_{column} ON crystal_states({column})"
            )
