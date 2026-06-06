"""Gobierno humano de neuronas candidatas generadas por deuda del sistema.

Lee candidatas desde artifacts de runs y registra decisiones auditables sin
promover automáticamente a memoria estable. La promoción real a experimental o
stable debe pasar por revisión humana y pruebas.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class NeuronCandidateGovernance:
    """Lista y gobierna candidatas desde artifacts locales de runs."""

    def __init__(self, runs_dir: str | Path = "runs") -> None:
        self.runs_dir = Path(runs_dir)

    def list_candidates(self, limit_runs: int = 50, include_decided: bool = True) -> dict[str, Any]:
        candidates: list[dict[str, Any]] = []
        run_dirs = sorted(
            [path for path in self.runs_dir.glob("run-*") if path.is_dir()],
            key=lambda path: path.name,
            reverse=True,
        )[:limit_runs]
        for run_path in run_dirs:
            run_id = run_path.name
            raw_candidates = _read_json(run_path / "background_neuron_candidates.json", [])
            decisions = self._decisions_by_name(run_path)
            if not isinstance(raw_candidates, list):
                continue
            for item in raw_candidates:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or item.get("display_name") or "").strip()
                if not name:
                    continue
                decision = decisions.get(name)
                if decision and not include_decided:
                    continue
                candidates.append(
                    {
                        "run_id": run_id,
                        "name": name,
                        "display_name": item.get("display_name") or name,
                        "status": item.get("status", "candidate"),
                        "activation": item.get("activation", "requires_human_approval"),
                        "severity": item.get("severity", "medium"),
                        "source": item.get("source"),
                        "mission": item.get("mission"),
                        "policy": item.get("policy"),
                        "suggested_roles": item.get("suggested_roles", []),
                        "evidence": item.get("evidence", {}),
                        "decision": decision,
                    }
                )
        return {"status": "ok", "count": len(candidates), "candidates": candidates}

    def approve(self, run_id: str, name: str, approved_by: str = "human", notes: str = "") -> dict[str, Any]:
        return self._record_decision(
            run_id=run_id,
            name=name,
            decision="approved",
            next_status="experimental",
            decided_by=approved_by,
            notes=notes,
        )

    def reject(self, run_id: str, name: str, rejected_by: str = "human", notes: str = "") -> dict[str, Any]:
        return self._record_decision(
            run_id=run_id,
            name=name,
            decision="rejected",
            next_status="rejected",
            decided_by=rejected_by,
            notes=notes,
        )

    def _record_decision(self, run_id: str, name: str, decision: str, next_status: str, decided_by: str, notes: str = "") -> dict[str, Any]:
        run_path = self.runs_dir / run_id
        if not run_path.exists() or not run_path.is_dir():
            return {"status": "error", "error": f"Run no encontrado: {run_id}"}
        candidate = self._find_candidate(run_path, name)
        if candidate is None:
            return {"status": "error", "error": f"Candidata no encontrada: {name}"}
        decisions_path = run_path / "neuron_candidate_decisions.json"
        decisions = _read_json(decisions_path, [])
        if not isinstance(decisions, list):
            decisions = []
        record = {
            "run_id": run_id,
            "name": candidate.get("name") or name,
            "display_name": candidate.get("display_name") or candidate.get("name") or name,
            "decision": decision,
            "previous_status": candidate.get("status", "candidate"),
            "next_status": next_status,
            "decided_by": decided_by or "human",
            "decided_at": datetime.now(timezone.utc).isoformat(),
            "notes": notes,
            "policy": "human_governance_required_before_activation",
            "candidate": candidate,
        }
        decisions = [item for item in decisions if not (isinstance(item, dict) and item.get("name") == record["name"])]
        decisions.append(record)
        _write_json(decisions_path, decisions)
        return {"status": "ok", "decision": record}

    def _find_candidate(self, run_path: Path, name: str) -> dict[str, Any] | None:
        raw_candidates = _read_json(run_path / "background_neuron_candidates.json", [])
        if not isinstance(raw_candidates, list):
            return None
        for item in raw_candidates:
            if not isinstance(item, dict):
                continue
            if item.get("name") == name or item.get("display_name") == name:
                return item
        return None

    @staticmethod
    def _decisions_by_name(run_path: Path) -> dict[str, dict[str, Any]]:
        decisions = _read_json(run_path / "neuron_candidate_decisions.json", [])
        if not isinstance(decisions, list):
            return {}
        result: dict[str, dict[str, Any]] = {}
        for item in decisions:
            if isinstance(item, dict) and item.get("name"):
                result[str(item["name"])] = item
        return result
