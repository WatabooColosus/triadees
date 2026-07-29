"""Auditoría read-only de actividad real, candidata y autorreferencial."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


def audit(db_path: str | Path) -> dict[str, Any]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row

        def count(sql: str, params: tuple[Any, ...] = ()) -> int:
            return int(conn.execute(sql, params).fetchone()[0])

        return {
            "runs": {
                "user": count("SELECT COUNT(*) FROM runs WHERE source IN ('react-ui','single-port-ui','console')"),
                "synthetic": count("SELECT COUNT(*) FROM runs WHERE source LIKE 'system_pulse%' OR source IN ('worker','neuron_activity')"),
            },
            "organs": {
                "hypothalamus_signals": count("SELECT COUNT(*) FROM signal_states"),
                "crystal_states": count("SELECT COUNT(*) FROM crystal_states"),
                "qualia_experiences": count("SELECT COUNT(*) FROM qualia_experiences"),
                "qualia_worker_generated": count("SELECT COUNT(*) FROM qualia_experiences WHERE source='living_worker'"),
                "episodic_memories": count("SELECT COUNT(*) FROM episodic_memory"),
                "stable_semantic_memories": count("SELECT COUNT(*) FROM semantic_memory WHERE status='stable'"),
            },
            "learning": {
                "internally_checked": count("SELECT COUNT(*) FROM learning_queue WHERE status='internally_checked'"),
                "validated_in_runs": count("SELECT COUNT(*) FROM learning_queue WHERE status='validated_in_runs'"),
                "stable": count("SELECT COUNT(*) FROM learning_queue WHERE status IN ('consolidated','stable')"),
                "education_passed": count("SELECT COUNT(*) FROM neuron_education_sessions WHERE result IN ('passed','consolidated')"),
            },
            "research": {
                "with_candidate": count("SELECT COUNT(*) FROM autonomous_research_runs WHERE status='candidate_created'"),
                "without_evidence": count("SELECT COUNT(*) FROM autonomous_research_runs WHERE status='no_evidence'"),
            },
            "self_reference": {
                "worker_mission_evidence": count("SELECT COUNT(*) FROM neuron_evidence WHERE source='worker'"),
                "external_mission_evidence": count("SELECT COUNT(*) FROM neuron_evidence WHERE source NOT IN ('worker','experimental_light_pulse')"),
                "synthetic_neuron_activity": count("SELECT COUNT(*) FROM neuron_activity WHERE policy='experimental_light_pulse'"),
            },
            "truth": {
                "learned_requires": "validated_in_runs + measured improvement + reproducible evidence",
                "heartbeat_is_learning": False,
                "internally_checked_is_independent_truth": False,
                "worker_self_evidence_is_promotion_evidence": False,
            },
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="triade/memory/triade.db")
    args = parser.parse_args()
    print(json.dumps(audit(args.db), indent=2, ensure_ascii=False))
