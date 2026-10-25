"""Recover only genuine R6.3 pre-lesson functional runs with exact archived answers.

No manufactured runs, no altered report states, no identity changes.
The functional evaluator independently rechecks provenance and semantic-quarantine safety.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC
from pathlib import Path

from triade.neurons.functional_evidence import (
    CASES,
    register_actual_probe,
    supported_domain,
)


def recover(*, neuron_id: int, limit: int, apply: bool) -> dict:
    root = Path("/content/Triade")
    db = root / "triade/memory/triade.db"
    if not db.is_file():
        raise RuntimeError("Bodega de Colab R5 no encontrada")
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=25) as c:
        neuron = c.execute(
            "SELECT name,domain FROM neurons WHERE id=?", (neuron_id,)
        ).fetchone()
        if neuron is None:
            raise RuntimeError("Neurona desconocida")
        domain = supported_domain(str(neuron[0]), str(neuron[1]))
        if domain is None:
            raise RuntimeError("Dominio sin prueba funcional reconocida")
        cases = [case for case in CASES if case.domain == domain]
        records = c.execute(
            "SELECT r.run_id,r.user_input,e.content FROM runs r "
            "JOIN episodic_memory e ON e.run_id=r.run_id "
            "WHERE r.source='neuron_functional_probe' AND r.status='ok' "
            "AND EXISTS(SELECT 1 FROM neuron_activity na "
            "WHERE na.run_id=r.run_id AND na.neuron_id=? AND na.activated=1) "
            "ORDER BY r.rowid DESC LIMIT ?",
            (neuron_id, max(5, limit * 3)),
        ).fetchall()
        candidates = []
        seen = set()
        for run_id, prompt, episode in records:
            case = next(
                (
                    item
                    for item in cases
                    if str(prompt).startswith(item.question + "\nContexto de dominio:")
                ),
                None,
            )
            if case is None or case.id in seen:
                continue
            prefix = "Usuario: " + str(prompt) + "\nRespuesta: "
            if not isinstance(episode, str) or not episode.startswith(prefix):
                continue
            response = episode[len(prefix) :]
            if not response.strip():
                continue
            candidates.append((str(run_id), case.id, response))
            seen.add(case.id)
            if len(candidates) >= limit:
                break

    result = {
        "status": "preview" if not apply else "applied",
        "neuron_id": neuron_id,
        "source": "archived_real_runner_outputs",
        "recoverable_cases": [case_id for _, case_id, _ in candidates],
        "run_count": len(candidates),
        "recorded": 0,
        "rejected": [],
        "learning_proven": False,
        "causal_proof": False,
    }
    if not apply:
        return result

    # A verified consistent SQLite backup before the FIRST insert.
    if not candidates:
        return result
    import os
    from datetime import datetime

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    folder = Path("/content/triade_operacion_r5/actualizaciones/r631_recovery") / stamp
    folder.mkdir(parents=True, exist_ok=False)
    os.chmod(folder, 0o700)
    snapshot = folder / "pre_recovery.sqlite3"
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=30) as src:  # noqa: SIM117 - consistent SQLite copy
        with sqlite3.connect(snapshot) as dst:
            src.backup(dst, pages=128, sleep=0.1)
    with sqlite3.connect(snapshot) as c:
        if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Copia de Bodega inconsistente; recuperación bloqueada")
    os.chmod(snapshot, 0o600)
    result["local_backup"] = str(snapshot)

    for run_id, case_id, answer in candidates:
        try:
            outcome = register_actual_probe(
                db,
                run_id=run_id,
                neuron_id=neuron_id,
                case_id=case_id,
                phase="pre",
                answer=answer,
            )
            result["recorded"] += int(
                outcome["status"] in ("recorded", "already_recorded")
            )
            print(
                json.dumps(
                    {
                        "case_id": case_id,
                        "run_id": run_id,
                        "rubric_score": outcome["score"],
                        "status": outcome["status"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        except (ValueError, sqlite3.Error) as exc:
            result["rejected"].append({"case_id": case_id, "reason": str(exc)[:170]})
    return result


def main() -> int:
    p = argparse.ArgumentParser(
        description="Tríade R6.3.1 · recuperación fiel de pruebas PRE"
    )
    p.add_argument("--neuron", type=int, default=11)
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--apply", action="store_true")
    a = p.parse_args()
    if not 1 <= a.limit <= 5:
        p.error("El límite debe estar entre 1 y 5")
    outcome = recover(neuron_id=a.neuron, limit=a.limit, apply=a.apply)
    print(json.dumps(outcome, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
