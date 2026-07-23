"""Gate persistente de novedad para reducir candidatos repetidos."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any


class LearningNoveltyGate:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db", threshold: float = 0.88) -> None:
        self.db_path = Path(db_path)
        self.threshold = threshold
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS learning_novelty (
                    fingerprint TEXT PRIMARY KEY, candidate_id TEXT NOT NULL,
                    domain TEXT NOT NULL, tokens_json TEXT NOT NULL,
                    duplicate_hits INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS learning_novelty_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT NOT NULL,
                    decision TEXT NOT NULL, similarity REAL NOT NULL,
                    matched_candidate_id TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    @staticmethod
    def tokens(content: str) -> set[str]:
        return {word for word in re.findall(r"[a-záéíóúñ0-9]+", content.lower()) if len(word) > 2}

    @staticmethod
    def fingerprint(content: str) -> str:
        normalized = " ".join(sorted(LearningNoveltyGate.tokens(content)))
        return hashlib.sha256(normalized.encode()).hexdigest()

    def assess(self, content: str, domain: str) -> dict[str, Any]:
        tokens = self.tokens(content)
        fingerprint = self.fingerprint(content)
        best_id = None
        best_similarity = 0.0
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            exact = conn.execute("SELECT candidate_id FROM learning_novelty WHERE fingerprint=?", (fingerprint,)).fetchone()
            if exact:
                best_id, best_similarity = exact["candidate_id"], 1.0
            else:
                rows = conn.execute("SELECT candidate_id,tokens_json FROM learning_novelty WHERE domain=? ORDER BY rowid DESC LIMIT 500", (domain,)).fetchall()
                for row in rows:
                    other = set(json.loads(row["tokens_json"]))
                    union = tokens | other
                    similarity = len(tokens & other) / len(union) if union else 1.0
                    if similarity > best_similarity:
                        best_id, best_similarity = row["candidate_id"], similarity
            novel = best_id is None or best_similarity < self.threshold
            conn.execute(
                "INSERT INTO learning_novelty_events(fingerprint,decision,similarity,matched_candidate_id) VALUES (?,?,?,?)",
                (fingerprint, "novel" if novel else "duplicate", best_similarity, best_id),
            )
            if not novel:
                conn.execute("UPDATE learning_novelty SET duplicate_hits=duplicate_hits+1,last_seen_at=CURRENT_TIMESTAMP WHERE candidate_id=?", (best_id,))
        return {"novel": novel, "fingerprint": fingerprint, "similarity": round(best_similarity, 6),
                "matched_candidate_id": best_id, "threshold": self.threshold}

    def register(self, candidate_id: str, content: str, domain: str) -> None:
        tokens = sorted(self.tokens(content))
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO learning_novelty(fingerprint,candidate_id,domain,tokens_json) VALUES (?,?,?,?)",
                (self.fingerprint(content), candidate_id, domain, json.dumps(tokens, ensure_ascii=False)),
            )

    def metrics(self) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            rows = dict(conn.execute("SELECT decision,COUNT(*) FROM learning_novelty_events GROUP BY decision").fetchall())
        total = sum(rows.values())
        return {"events": total, "novel": rows.get("novel", 0), "duplicates": rows.get("duplicate", 0),
                "novelty_rate": round(rows.get("novel", 0) / total, 4) if total else None}

