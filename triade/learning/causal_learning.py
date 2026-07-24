"""T-014 — Learning avanzado: causal learning (relaciones causa-efecto),
compresión de conocimiento, estados granulares (deprecated/archived/retired),
y integración con spaced repetition existente."""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from triade.core.contracts import utc_now


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{hashlib.md5(str(datetime.now(timezone.utc).timestamp()).encode()).hexdigest()[:6]}"


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS causal_edges (
    edge_id        TEXT PRIMARY KEY,
    cause_id       TEXT NOT NULL,
    effect_id      TEXT NOT NULL,
    relation_type  TEXT DEFAULT 'direct',
    confidence     REAL DEFAULT 0.5,
    evidence_json  TEXT DEFAULT '[]',
    domain         TEXT DEFAULT '',
    status         TEXT DEFAULT 'active',
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ce_cause ON causal_edges(cause_id);
CREATE INDEX IF NOT EXISTS idx_ce_effect ON causal_edges(effect_id);
CREATE TABLE IF NOT EXISTS causal_nodes (
    node_id        TEXT PRIMARY KEY,
    label          TEXT NOT NULL,
    node_type      TEXT DEFAULT 'event',
    domain         TEXT DEFAULT '',
    metadata_json  TEXT DEFAULT '{}',
    created_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS knowledge_granular_states (
    item_id        TEXT PRIMARY KEY,
    current_state  TEXT NOT NULL,
    previous_state TEXT,
    reason         TEXT DEFAULT '',
    actor          TEXT DEFAULT 'system',
    changed_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS knowledge_compressions (
    compression_id TEXT PRIMARY KEY,
    source_items_json TEXT DEFAULT '[]',
    compressed_summary TEXT NOT NULL,
    domain         TEXT DEFAULT '',
    items_count    INTEGER DEFAULT 0,
    compression_ratio REAL DEFAULT 0.0,
    status         TEXT DEFAULT 'active',
    created_at     TEXT NOT NULL
);
"""


GRANULAR_STATES = {
    "candidate", "experimental", "validated", "stable",
    "deprecated", "archived", "retired", "quarantined",
}


class CausalLearningEngine:
    """Aprende relaciones causa-efecto entre eventos/conocimiento."""

    def __init__(self, db_path: str | None = None, conn: sqlite3.Connection | None = None):
        self._conn = conn or sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)

    def add_node(self, label: str, node_type: str = "event",
                 domain: str = "", metadata: dict | None = None) -> dict:
        node_id = _gen_id("cnode")
        now = utc_now()
        self._conn.execute(
            """INSERT INTO causal_nodes (node_id, label, node_type, domain, metadata_json, created_at)
               VALUES (?,?,?,?,?,?)""",
            (node_id, label, node_type, domain,
             json.dumps(metadata or {}, default=str), now),
        )
        self._conn.commit()
        return {"node_id": node_id, "label": label, "type": node_type}

    def add_edge(self, cause_id: str, effect_id: str,
                 relation_type: str = "direct", confidence: float = 0.5,
                 evidence: list | None = None, domain: str = "") -> dict:
        edge_id = _gen_id("cedge")
        now = utc_now()
        self._conn.execute(
            """INSERT INTO causal_edges
               (edge_id, cause_id, effect_id, relation_type,
                confidence, evidence_json, domain, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (edge_id, cause_id, effect_id, relation_type,
             _clamp(confidence), json.dumps(evidence or [], default=str),
             domain, "active", now),
        )
        self._conn.commit()
        return {"edge_id": edge_id, "cause": cause_id, "effect": effect_id,
                "confidence": round(confidence, 3)}

    def strengthen(self, edge_id: str, amount: float = 0.1) -> dict:
        row = self._conn.execute(
            "SELECT confidence FROM causal_edges WHERE edge_id=?", (edge_id,)
        ).fetchone()
        if not row:
            return {"error": "edge not found"}
        new_conf = _clamp(row["confidence"] + amount)
        self._conn.execute(
            "UPDATE causal_edges SET confidence=? WHERE edge_id=?",
            (new_conf, edge_id),
        )
        self._conn.commit()
        return {"edge_id": edge_id, "new_confidence": round(new_conf, 3)}

    def weaken(self, edge_id: str, amount: float = 0.1) -> dict:
        return self.strengthen(edge_id, -amount)

    def effects_of(self, node_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM causal_edges WHERE cause_id=? AND status='active' ORDER BY confidence DESC",
            (node_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def causes_of(self, node_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM causal_edges WHERE effect_id=? AND status='active' ORDER BY confidence DESC",
            (node_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def chains_from(self, node_id: str, max_depth: int = 5) -> list[list[dict]]:
        chains = []
        visited = set()

        def _traverse(current_id: str, chain: list, depth: int):
            if depth >= max_depth or current_id in visited:
                return
            visited.add(current_id)
            edges = self.effects_of(current_id)
            for e in edges:
                new_chain = chain + [e]
                chains.append(new_chain)
                _traverse(e["effect_id"], new_chain, depth + 1)
            visited.discard(current_id)

        _traverse(node_id, [], 0)
        return chains

    def domain_stats(self, domain: str) -> dict:
        nodes = self._conn.execute(
            "SELECT COUNT(*) as c FROM causal_nodes WHERE domain=?", (domain,)
        ).fetchone()["c"]
        edges = self._conn.execute(
            "SELECT COUNT(*) as c FROM causal_edges WHERE domain=? AND status='active'",
            (domain,),
        ).fetchone()["c"]
        avg_conf = self._conn.execute(
            "SELECT AVG(confidence) as a FROM causal_edges WHERE domain=? AND status='active'",
            (domain,),
        ).fetchone()["a"] or 0.0
        return {"domain": domain, "nodes": nodes, "edges": edges,
                "avg_confidence": round(avg_conf, 3)}

    def doctor(self) -> dict:
        nodes = self._conn.execute("SELECT COUNT(*) as c FROM causal_nodes").fetchone()["c"]
        edges = self._conn.execute("SELECT COUNT(*) as c FROM causal_edges WHERE status='active'").fetchone()["c"]
        return {"nodes": nodes, "active_edges": edges}


class KnowledgeGranularStates:
    """Estados granulares de conocimiento con transiciones auditables."""

    VALID_TRANSITIONS = {
        "candidate": {"experimental", "deprecated", "quarantined"},
        "experimental": {"validated", "deprecated", "quarantined"},
        "validated": {"stable", "deprecated", "quarantined"},
        "stable": {"deprecated", "archived"},
        "deprecated": {"archived", "retired", "quarantined"},
        "archived": {"retired"},
        "retired": set(),
        "quarantined": {"candidate", "experimental", "deprecated", "retired"},
    }

    def __init__(self, db_path: str | None = None, conn: sqlite3.Connection | None = None):
        self._conn = conn or sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)

    def transition(self, item_id: str, new_state: str, reason: str = "",
                   actor: str = "system") -> dict:
        if new_state not in GRANULAR_STATES:
            raise ValueError(f"Invalid state: {new_state}")

        row = self._conn.execute(
            "SELECT current_state FROM knowledge_granular_states WHERE item_id=?",
            (item_id,),
        ).fetchone()
        current = row["current_state"] if row else "candidate"

        allowed = self.VALID_TRANSITIONS.get(current, set())
        if new_state not in allowed:
            raise ValueError(f"Cannot transition from '{current}' to '{new_state}'")

        now = utc_now()
        self._conn.execute(
            """INSERT INTO knowledge_granular_states
               (item_id, current_state, previous_state, reason, actor, changed_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(item_id) DO UPDATE SET
                 current_state=?, previous_state=?, reason=?, actor=?, changed_at=?""",
            (item_id, new_state, current, reason, actor, now,
             new_state, current, reason, actor, now),
        )
        self._conn.commit()
        return {"item_id": item_id, "from": current, "to": new_state, "reason": reason}

    def get_state(self, item_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM knowledge_granular_states WHERE item_id=?", (item_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_by_state(self, state: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM knowledge_granular_states WHERE current_state=? ORDER BY changed_at DESC",
            (state,),
        ).fetchall()
        return [dict(r) for r in rows]

    def state_distribution(self) -> dict:
        rows = self._conn.execute(
            "SELECT current_state, COUNT(*) as c FROM knowledge_granular_states GROUP BY current_state"
        ).fetchall()
        return {r["current_state"]: r["c"] for r in rows}


class KnowledgeCompressor:
    """Comprime conocimiento acumulado en resúmenes concisos."""

    def __init__(self, db_path: str | None = None, conn: sqlite3.Connection | None = None):
        self._conn = conn or sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)

    def compress(self, items: list[dict], domain: str = "") -> dict:
        """Comprime una lista de items de conocimiento en un resumen."""
        if not items:
            return {"error": "no items to compress"}

        labels = [it.get("label", it.get("title", str(it))) for it in items]
        combined_text = " | ".join(labels)
        total_chars = len(combined_text)
        summary = _generate_summary(items)

        compression_id = _gen_id("kcomp")
        now = utc_now()
        ratio = len(summary) / max(total_chars, 1)

        self._conn.execute(
            """INSERT INTO knowledge_compressions
               (compression_id, source_items_json, compressed_summary,
                domain, items_count, compression_ratio, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (compression_id, json.dumps(items, default=str), summary,
             domain, len(items), round(ratio, 4), now),
        )
        self._conn.commit()
        return {
            "compression_id": compression_id,
            "items_count": len(items),
            "original_chars": total_chars,
            "summary_chars": len(summary),
            "compression_ratio": round(ratio, 4),
            "summary": summary,
        }

    def get(self, compression_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM knowledge_compressions WHERE compression_id=?",
            (compression_id,),
        ).fetchone()
        return dict(row) if row else None

    def list_by_domain(self, domain: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM knowledge_compressions WHERE domain=? ORDER BY created_at DESC",
            (domain,),
        ).fetchall()
        return [dict(r) for r in rows]


def _generate_summary(items: list[dict]) -> str:
    summaries = []
    for it in items:
        label = it.get("label", it.get("title", ""))
        content = it.get("content", it.get("summary", ""))
        if content:
            summaries.append(f"{label}: {content[:200]}")
        elif label:
            summaries.append(label)
    return "; ".join(summaries)[:2000] if summaries else "Empty compression"
