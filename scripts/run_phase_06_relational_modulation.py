#!/usr/bin/env python3
"""Evidencia runtime para continuidad de modulación relacional."""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from triade.memory.relational_modulation import RelationalModulationStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="artifacts/triade_verify/phase_06/relational_modulation.json",
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="triade-phase06-") as raw_tmp:
        root = Path(raw_tmp)
        store = RelationalModulationStore(root / "state.db")
        baseline = store.get("alice", "session-a")
        event = store.apply_event(
            "alice",
            "session-a",
            "conflict_signal",
            {"templanza": -9.0, "paciencia": 9.0},
            source_ref="runtime:event:1",
            explanation="Bounded conflict modulation exercise.",
        )
        isolated = store.get("bob", "session-a")
        restarted = RelationalModulationStore(root / "state.db").get(
            "alice", "session-a"
        )
        decay = store.decay(
            "alice", "session-a", elapsed_seconds=3600, half_life_seconds=3600
        )
        rollback = store.rollback_event(
            decay["event_id"], actor="human:phase06", reason="reversibility exercise"
        )
        backup = store.backup(root / "backup" / "state.db")
        restore = RelationalModulationStore.restore_to_sandbox(
            backup["path"], root / "restore" / "state.db", backup["fingerprint"]
        )
        checks = {
            "event_changed_state": event["after"] != baseline["pv7"],
            "extreme_input_bounded": max(
                abs(v) for v in event["applied_delta"].values()
            )
            <= 0.12,
            "user_isolation": isolated["pv7"] == isolated["baseline"],
            "restart_retention": restarted["pv7"] == event["after"],
            "decay_toward_baseline": abs(decay["after"]["templanza"] - 0.7)
            < abs(event["after"]["templanza"] - 0.7),
            "rollback_restored_previous": rollback["restored"] == event["after"],
            "restore_verified": restore["status"] == "verified",
            "no_subjective_claim": baseline["subjective_emotion_claimed"] is False,
        }
        payload = {
            "phase": 6,
            "generated_at": datetime.now(UTC).isoformat(),
            "state_type": "relational modulation state",
            "checks": checks,
            "event": event,
            "decay": decay,
            "rollback": rollback,
            "restore": restore,
            "passed": all(checks.values()),
        }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
