"""T-007 — Comparación de soluciones: evalúa la nueva propuesta contra
soluciones existentes del mismo dominio para evitar duplicación."""

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


class ComparisonEngine:
    """Compara una propuesta de neurona contra soluciones existentes del mismo
    dominio. Calcula similitud, overlap funcional, y decide si se crea o se
    reutiliza."""

    SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS neuron_comparisons (
        comparison_id   TEXT PRIMARY KEY,
        proposal_name   TEXT NOT NULL,
        proposal_mission TEXT NOT NULL,
        domain          TEXT NOT NULL,
        compared_json   TEXT DEFAULT '[]',
        best_match_json TEXT DEFAULT '{}',
        similarity_score REAL DEFAULT 0.0,
        overlap_ratio   REAL DEFAULT 0.0,
        decision        TEXT DEFAULT 'create_new',
        decision_reason TEXT DEFAULT '',
        created_at      TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_comp_domain ON neuron_comparisons(domain);
    """

    def __init__(self, db_path: str | None = None, conn: sqlite3.Connection | None = None):
        self._conn = conn or sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(self.SCHEMA_SQL)

    def compare(
        self,
        proposal_name: str,
        proposal_mission: str,
        domain: str,
        proposal_capabilities: list[str],
        existing_neurons: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Compara propuesta con neuronas existentes del mismo dominio."""
        now = utc_now()
        comparison_id = _gen_id("comp")

        prop_caps = set(proposal_capabilities)
        results = []
        best_match = {}
        best_sim = 0.0

        for neuron in existing_neurons:
            neuron_caps = set(neuron.get("capabilities", []))
            jaccard = len(prop_caps & neuron_caps) / max(len(prop_caps | neuron_caps), 1)
            name_sim = _name_similarity(proposal_name, neuron.get("name", ""))
            sim = round(0.6 * jaccard + 0.4 * name_sim, 3)
            results.append(
                {
                    "neuron_id": neuron.get("neuron_id", ""),
                    "name": neuron.get("name", ""),
                    "capabilities": sorted(neuron_caps),
                    "jaccard_overlap": round(jaccard, 3),
                    "name_similarity": round(name_sim, 3),
                    "overall_similarity": sim,
                }
            )
            if sim > best_sim:
                best_sim = sim
                best_match = results[-1]

        overlap = best_match.get("jaccard_overlap", 0.0)
        decision, reason = _decide(best_sim, overlap, proposal_name, best_match)

        payload = {
            "comparison_id": comparison_id,
            "proposal_name": proposal_name,
            "proposal_mission": proposal_mission,
            "domain": domain,
            "compared": results,
            "best_match": best_match,
            "similarity_score": best_sim,
            "overlap_ratio": overlap,
            "decision": decision,
            "decision_reason": reason,
            "created_at": now,
        }

        self._conn.execute(
            """INSERT INTO neuron_comparisons
               (comparison_id, proposal_name, proposal_mission, domain,
                compared_json, best_match_json, similarity_score,
                overlap_ratio, decision, decision_reason, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                comparison_id,
                proposal_name,
                proposal_mission,
                domain,
                json.dumps(results, default=str),
                json.dumps(best_match, default=str),
                best_sim,
                overlap,
                decision,
                reason,
                now,
            ),
        )
        self._conn.commit()
        return payload

    def get(self, comparison_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM neuron_comparisons WHERE comparison_id=?", (comparison_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_by_domain(self, domain: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM neuron_comparisons WHERE domain=? ORDER BY created_at DESC",
            (domain,),
        ).fetchall()
        return [dict(r) for r in rows]


def _name_similarity(a: str, b: str) -> float:
    """Similitud simple basada en tokens compartidos."""
    tokens_a = set(a.lower().replace("_", " ").replace("-", " ").split())
    tokens_b = set(b.lower().replace("_", " ").replace("-", " ").split())
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def _decide(
    similarity: float,
    overlap: float,
    prop_name: str,
    best_match: dict,
) -> tuple[str, str]:
    if similarity > 0.85 and overlap > 0.8:
        return "reuse", f"Neurona '{best_match.get('name', '')}' cubre >85% de la propuesta"
    if similarity > 0.65:
        return "extend", f"Neurona '{best_match.get('name', '')}' cubre parcialmente; extiende"
    return "create_new", "No se encontró solucion suficientemente similar"
