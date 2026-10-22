"""Convierte fallos verificados en propuestas, nunca en promociones.

Únicamente genera una propuesta si:
- una señal procede de un informe de regresión;
- existen al menos cinco informes distintos ya cosechados que corroboran
  la misma brecha medible;
- la confianza supera el umbral gobernado (nunca inferior a 0,96);
- existe exactamente una especificación neuronal completa y declarada como
  'specified' para la capacidad solicitada.
No crea neuronas/especificaciones, no aprueba propuestas y no toca pesos.
"""
from __future__ import annotations

import hashlib
import json
import math
from contextlib import closing
from pathlib import Path
from typing import Any

from triade.db import sqlite3
from triade.neuron_factory import NeuronSpecificationStore

from .auto_approval import min_confidence
from .contracts import ImprovementProposal
from .failure_learning import FailureLearningLoop
from .store import ImprovementStore

MIN_INDEPENDENT_FAILURE_REPORTS = 5


def propose_from_measured_failures(
    db_path: str | Path,
    *,
    limit: int = 3,
) -> dict[str, Any]:
    """Escribe como máximo `limit` propuestas nuevas desde brechas verificadas.

    Los motivos de omisión son parte de la evidencia; no se fabrican filas de
    propuestas para alcanzar objetivos cuantitativos.
    """
    result: dict[str, Any] = {
        "signals_seen": 0,
        "proposals_created": 0,
        "created": [],
        "skipped": [],
    }
    if limit < 1:
        return result
    db_path = Path(db_path)
    if not db_path.is_file():
        return result

    learner = FailureLearningLoop(db_path)
    store = ImprovementStore(db_path)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if not {"neuron_specifications", "improvement_signals", "improvement_proposals"} <= tables:
            return result
        signals = [
            dict(row)
            for row in conn.execute(
                "SELECT signal_id, capability_id, metric_id, payload_json "
                "FROM improvement_signals WHERE status='open' "
                "ORDER BY created_at, signal_id LIMIT 30"
            )
        ]
        specifications = [
            dict(row)
            for row in conn.execute(
                "SELECT neuron_id, version, state, payload_json "
                "FROM neuron_specifications WHERE state='specified'"
            )
        ]
        existing = {
            str(row[0])
            for row in conn.execute(
                "SELECT signal_id FROM improvement_proposals"
            )
        }

    for signal in signals:
        result["signals_seen"] += 1
        sid = str(signal["signal_id"])
        capability = str(signal["capability_id"])
        metric = str(signal["metric_id"])
        def skip(reason: str) -> None:
            result["skipped"].append({"signal_id": sid, "reason": reason})

        if sid in existing:
            skip("proposal_already_exists_for_signal")
            continue
        try:
            payload = json.loads(signal["payload_json"])
        except (TypeError, ValueError):
            skip("invalid_signal_payload")
            continue
        if not isinstance(payload, dict):
            skip("invalid_signal_payload")
            continue
        if (
            payload.get("capability_id") != capability
            or payload.get("metric_id") != metric
            or not str(payload.get("source_ref") or "").startswith("regression_report:")
        ):
            skip("signal_has_no_verified_regression_origin")
            continue
        try:
            confidence = float(payload.get("confidence"))
        except (TypeError, ValueError):
            skip("signal_has_no_measurable_confidence")
            continue
        if not math.isfinite(confidence) or confidence < min_confidence():
            skip("confidence_below_governed_threshold")
            continue
        corroborations = learner.corroborations_for(capability, metric)
        if corroborations < MIN_INDEPENDENT_FAILURE_REPORTS:
            skip("insufficient_independent_regressions")
            continue
        valid_targets: list[dict[str, Any]] = []
        for candidate in specifications:
            try:
                spec = json.loads(candidate["payload_json"])
                validated = NeuronSpecificationStore.from_payload(spec)
                validated.validate()
            except (KeyError, TypeError, ValueError):
                continue
            if (
                validated.state == "specified"
                and validated.neuron_id == candidate["neuron_id"]
                and validated.version == candidate["version"]
                and capability in validated.provides_capabilities
            ):
                valid_targets.append(spec)
        if len(valid_targets) != 1:
            skip("no_unique_authorized_neuron_specification")
            continue
        spec = valid_targets[0]
        proposal_id = (
            "measured-" + hashlib.sha256(sid.encode("utf-8")).hexdigest()[:24]
        )
        proposal = ImprovementProposal(
            proposal_id=proposal_id,
            signal_id=sid,
            hypothesis=learner.hypothesis_for(capability, metric),
            requested_capability=capability,
            requires_human_approval=(
                payload.get("risk_level") in {"high", "critical"}
            ),
            max_candidates=1,
            cooldown_seconds=3600,
            neuron_id=str(spec["neuron_id"]),
            version=str(spec["version"]),
        )
        try:
            store.create_proposal(proposal)
        except (ValueError, KeyError) as exc:
            skip("proposal_store_rejected: " + str(exc))
            continue
        result["proposals_created"] += 1
        result["created"].append(
            {
                "proposal_id": proposal_id,
                "signal_id": sid,
                "neuron_id": str(spec["neuron_id"]),
                "version": str(spec["version"]),
                "corroborations": corroborations,
                "requires_human_approval": proposal.requires_human_approval,
            }
        )
        existing.add(sid)
        if result["proposals_created"] >= limit:
            break
    return result
