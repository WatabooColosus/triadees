"""T-007 — Investigación pre-creación: analiza contexto, dominio, soluciones
existentes antes de generar una especificación de neurona."""

import json
import hashlib
import sqlite3
from datetime import datetime, timezone
from typing import Any

from triade.core.contracts import utc_now


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{hashlib.md5(str(datetime.now(timezone.utc).timestamp()).encode()).hexdigest()[:6]}"


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


class ResearchEngine:
    """Analiza contexto de dominio, soluciones existentes y gap analysis antes
    de que se genere una especificación de neurona."""

    SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS neuron_research (
        research_id   TEXT PRIMARY KEY,
        neuron_name   TEXT NOT NULL,
        domain        TEXT NOT NULL,
        mission       TEXT NOT NULL,
        existing_solutions_json TEXT DEFAULT '[]',
        gap_analysis_json       TEXT DEFAULT '{}',
        feasibility_score       REAL DEFAULT 0.0,
        risk_assessment_json     TEXT DEFAULT '{}',
        recommendation           TEXT DEFAULT 'proceed',
        created_at   TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_research_domain ON neuron_research(domain);
    """

    def __init__(self, db_path: str | None = None, conn: sqlite3.Connection | None = None):
        self._conn = conn or sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(self.SCHEMA_SQL)

    def investigate(
        self,
        neuron_name: str,
        domain: str,
        mission: str,
        existing_knowledge: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Ejecuta investigación: analiza dominio, lista soluciones existentes,
        identifica gaps, evalua factibilidad, genera recomendación."""
        now = utc_now()
        research_id = _gen_id("research")

        existing = existing_knowledge or []
        solutions = self._analyze_existing(existing)
        gaps = self._gap_analysis(mission, solutions)
        feasibility = self._feasibility_score(mission, solutions, gaps)
        risk = self._risk_assessment(feasibility, mission)
        recommendation = self._recommend(feasibility, risk)

        payload = {
            "research_id": research_id,
            "neuron_name": neuron_name,
            "domain": domain,
            "mission": mission,
            "existing_solutions": solutions,
            "gap_analysis": gaps,
            "feasibility_score": feasibility,
            "risk_assessment": risk,
            "recommendation": recommendation,
            "created_at": now,
        }

        self._conn.execute(
            """INSERT INTO neuron_research
               (research_id, neuron_name, domain, mission,
                existing_solutions_json, gap_analysis_json,
                feasibility_score, risk_assessment_json,
                recommendation, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                research_id,
                neuron_name,
                domain,
                mission,
                json.dumps(solutions, default=str),
                json.dumps(gaps, default=str),
                feasibility,
                json.dumps(risk, default=str),
                recommendation,
                now,
            ),
        )
        self._conn.commit()
        return payload

    def get(self, research_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM neuron_research WHERE research_id=?", (research_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_by_domain(self, domain: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM neuron_research WHERE domain=? ORDER BY created_at DESC",
            (domain,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------- internal analysis ----------

    @staticmethod
    def _analyze_existing(existing: list[dict]) -> list[dict]:
        """Clasifica soluciones existentes por tipo y cobertura."""
        solutions = []
        for e in existing:
            solutions.append(
                {
                    "name": e.get("name", "unknown"),
                    "type": e.get("type", "unknown"),
                    "capabilities": e.get("capabilities", []),
                    "maturity": e.get("maturity", "prototype"),
                    "coverage": _clamp(len(e.get("capabilities", [])) / 5.0),
                }
            )
        return solutions

    @staticmethod
    def _gap_analysis(mission: str, solutions: list[dict]) -> dict:
        """Identifica qué capacidades de la misión no están cubiertas."""
        all_caps = set()
        for s in solutions:
            all_caps.update(s.get("capabilities", []))

        mission_words = set(mission.lower().split())
        uncovered = list(mission_words - all_caps)
        coverage = _clamp(1.0 - len(uncovered) / max(len(mission_words), 1))
        return {
            "covered_capabilities": sorted(all_caps),
            "uncovered_keywords": uncovered[:20],
            "coverage_ratio": coverage,
            "needs_novel": coverage < 0.4,
        }

    @staticmethod
    def _feasibility_score(mission: str, solutions: list[dict], gaps: dict) -> float:
        """Score 0-1: factibilidad basada en gaps y soluciones existentes."""
        existing_coverage = gaps.get("coverage_ratio", 0.0)
        num_solutions = min(len(solutions) / 5.0, 1.0)
        mission_complexity = min(len(mission.split()) / 15.0, 1.0)
        score = _clamp(
            0.3 * existing_coverage + 0.3 * num_solutions + 0.4 * (1.0 - mission_complexity)
        )
        return round(score, 3)

    @staticmethod
    def _risk_assessment(feasibility: float, mission: str) -> dict:
        risk_level = "low" if feasibility > 0.7 else ("medium" if feasibility > 0.4 else "high")
        return {
            "level": risk_level,
            "factors": {
                "feasibility": feasibility,
                "mission_length": len(mission.split()),
            },
        }

    @staticmethod
    def _recommend(feasibility: float, risk: dict) -> str:
        if feasibility > 0.7 and risk["level"] == "low":
            return "proceed"
        if feasibility > 0.4:
            return "proceed_with_caution"
        return "revise_mission"
