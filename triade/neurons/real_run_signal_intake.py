"""Promote real completed user runs to *signals*, never to learned facts.

Workers cannot make themselves their own source of independent evidence. A
completed, relevant UI run is a human-origin *request to examine a mission*,
NOT verification of the neuron's conclusions, an education application, or
a weight update. No user message text is copied into the evidence ledger.
"""

from __future__ import annotations

import json
import re
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from triade.core.neuron_missions import NeuronMission, select_relevant_missions
from triade.db import sqlite3

# These common intent words are not meaningful mission-level evidence.
_STOPWORDS = frozenset(
    {
        "para", "como", "quiero", "puedes", "hacer", "ayuda",
        "sobre", "necesito", "donde", "cuando", "favor", "gracias",
        "hola", "tengo", "estoy", "tienes", "debes", "algo",
    }
)


def _as_utc(value: str) -> datetime | None:
    try:
        result = datetime.fromisoformat(value)
    except (ValueError, TypeError, AttributeError):
        return None
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)


class RealRunSignalIntake:
    """Conservative, idempotent harvest of human-origin mission wakeup signals."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def harvest(self, *, limit: int = 2, max_age_hours: int = 24) -> dict[str, object]:
        if not 1 <= limit <= 5 or not 1 <= max_age_hours <= 48:
            raise ValueError("Límites de ingesta fuera de la ventana gobernada")
        now = datetime.now(UTC)
        with closing(sqlite3.connect(self.db_path, timeout=8)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            tables = {
                str(row[0]) for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if not {"runs", "neuron_missions", "neuron_evidence", "neuron_work_cycles"} <= tables:
                return {"status": "unsupported", "created": 0}
            missions: list[NeuronMission] = []
            for m in conn.execute(
                "SELECT id,neuron_id,title,mission,domain,status,allowed_sources_json "
                "FROM neuron_missions WHERE status IN ('stable','experimental') "
                "ORDER BY id"
            ):
                try:
                    sources = json.loads(m["allowed_sources_json"] or "[]")
                except (TypeError, ValueError):
                    continue
                if not isinstance(sources, list) or "run" not in sources or m["neuron_id"] is None:
                    continue
                missions.append(
                    NeuronMission(
                        id=int(m["id"]),
                        neuron_id=int(m["neuron_id"]),
                        title=str(m["title"]),
                        mission=str(m["mission"]),
                        domain=str(m["domain"]),
                        status=str(m["status"]),
                        allowed_sources=sources,
                    )
                )
            if not missions:
                return {"status": "no_eligible_missions", "created": 0}
            # No content is generated from a worker. Only completed UI runs
            # proven by the persisted runs table can enter this bridge.
            runs = conn.execute(
                "SELECT run_id,user_input,created_at FROM runs "
                "WHERE source='react-ui' AND status='ok' "
                "ORDER BY id DESC LIMIT 40"
            ).fetchall()
            created: list[dict[str, object]] = []
            seen: set[tuple[int, str]] = set()
            conn.execute("BEGIN IMMEDIATE")
            for run in runs:
                run_id = str(run["run_id"] or "").strip()
                observed_at = _as_utc(str(run["created_at"] or ""))
                if (
                    not run_id or len(run_id) > 150 or observed_at is None
                    or observed_at > now + timedelta(minutes=2)
                    or now - observed_at > timedelta(hours=max_age_hours)
                ):
                    continue
                tokens = re.findall(r"\w+", str(run["user_input"] or "").lower())
                meaningful = [t for t in tokens if len(t) >= 5 and t not in _STOPWORDS]
                if not meaningful:
                    continue
                # A keyword match triggers observation, *not* a truth claim.
                for mission in select_relevant_missions(
                    missions, user_input=" ".join(meaningful), limit=5
                ):
                    if len(created) >= limit:
                        break
                    mid = int(mission.id or 0)
                    nid = int(mission.neuron_id or 0)
                    if (mid, run_id) in seen:
                        continue
                    seen.add((mid, run_id))
                    last_cycle = conn.execute(
                        "SELECT MAX(created_at) FROM neuron_work_cycles WHERE mission_id=?",
                        (mid,),
                    ).fetchone()[0]
                    cycle_at = _as_utc(str(last_cycle)) if last_cycle else None
                    if cycle_at and observed_at <= cycle_at:
                        continue
                    refs_json = json.dumps([f"run:{run_id}"], ensure_ascii=False)
                    already = conn.execute(
                        "SELECT 1 FROM neuron_evidence WHERE mission_id=? "
                        "AND source='run' AND evidence_type='human_run_signal' "
                        "AND refs_json=? LIMIT 1",
                        (mid, refs_json),
                    ).fetchone()
                    if already:
                        continue
                    # No raw user text and never a positive performance score.
                    conn.execute(
                        "INSERT INTO neuron_evidence "
                        "(mission_id,neuron_id,evidence_type,source,content,"
                        "refs_json,score,created_at) VALUES(?,?,?,?,?,?,?,?)",
                        (
                            mid, nid, "human_run_signal", "run",
                            "Turno humano completado; señal de revisión, no aprendizaje",
                            refs_json, 0.0, datetime.now(UTC).isoformat(),
                        ),
                    )
                    created.append({"mission_id": mid, "run_ref": f"run:{run_id}"})
                if len(created) >= limit:
                    break
            conn.commit()
            return {
                "status": "signals_recorded" if created else "no_new_independent_signal",
                "created": len(created),
                "references": created,
                "fact_verified": False,
                "learning_applied": False,
            }
