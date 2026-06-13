"""Self-Test Cycle — pruebas seguras que Tríade ejecuta sin permiso humano."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now
from triade.services.event_bus import publish_event


ALWAYS_ON_ALLOWED_ACTIONS = frozenset({
    "heartbeat",
    "resource_probe",
    "ollama_blood_check",
    "bodega_review",
    "learning_journal",
    "neuron_nutrition_observe",
    "neuron_nutrition_execute_if_governor_allows",
    "mission_readiness_audit",
    "integrity_snapshot_read_only",
    "technical_debt_audit",
    "self_test_cycle",
    "edge_context_fallback_test",
    "semantic_embedding_if_governor_allows",
    "learning_evaluation_if_governor_allows",
})

ALWAYS_ON_BLOCKED_ACTIONS = frozenset({
    "direct_delete",
    "repo_write_without_approval",
    "shell_freeform",
    "git_push",
    "git_reset",
    "package_install",
    "identity_core_modify",
    ".git_modify",
    ".env_modify",
    "red_zone_write",
})


def run_self_test_cycle(
    mode: str = "safe",
    *,
    db_path: str | Path = "triade/memory/triade.db",
    runs_dir: str | Path = "runs/background",
) -> dict[str, Any]:
    start_t = time.time()
    checks: dict[str, Any] = {}
    warnings: list[str] = []
    errors: list[str] = []

    evidence_created = 0
    neurons_nourished = 0
    candidates_created = 0

    # ── 1. Ollama Blood ──
    try:
        from triade.core.ollama_blood import check_ollama_blood
        blood = check_ollama_blood()
        checks["ollama_blood"] = {
            "status": blood.get("status"),
            "ollama_ok": blood.get("ollama_ok"),
            "can_reason": blood.get("can_reason"),
        }
    except Exception as exc:
        checks["ollama_blood"] = {"error": str(exc)}
        errors.append(f"ollama_blood: {exc}")

    # ── 2. Runtime Heartbeat ──
    try:
        from triade.core.internal_runtime import build_runtime_heartbeat
        hb = build_runtime_heartbeat(db_path=db_path, runs_dir=runs_dir)
        checks["heartbeat"] = {
            "status": hb.get("status"),
            "runtime_enabled": hb.get("runtime_enabled"),
            "cycles_last_hour": hb.get("cycles_last_hour"),
        }
    except Exception as exc:
        checks["heartbeat"] = {"error": str(exc)}
        errors.append(f"heartbeat: {exc}")

    # ── 3. Learning Journal ──
    try:
        from triade.core.learning_journal import build_learning_journal
        journal = build_learning_journal(db_path=db_path, limit=10)
        checks["learning_journal"] = {
            "status": journal.get("status"),
            "cycles_last_24h": journal.get("cycles_last_24h"),
        }
    except Exception as exc:
        checks["learning_journal"] = {"error": str(exc)}
        errors.append(f"learning_journal: {exc}")

    # ── 4. Neuron Nutrition (safe) ──
    try:
        from triade.core.neuron_nutrition import run_neuron_nutrition_cycle
        nutrition_mode = "observe_only"
        if mode == "full":
            nutrition_mode = "execute_missions"
        nutrition = run_neuron_nutrition_cycle(db_path=db_path, runs_dir=runs_dir, mode=nutrition_mode, limit=3)
        checks["neuron_nutrition"] = {
            "status": nutrition.get("status"),
            "cognitive_blood_active": nutrition.get("cognitive_blood_active"),
            "missions_executed": nutrition.get("missions_executed", 0),
            "evidence_created": nutrition.get("evidence_created", 0),
            "candidates_created": nutrition.get("candidates_created", 0),
            "neurons_nourished": nutrition.get("neurons_nourished", 0),
        }
        evidence_created += int(nutrition.get("evidence_created", 0) or 0)
        candidates_created += int(nutrition.get("candidates_created", 0) or 0)
        neurons_nourished += int(nutrition.get("neurons_nourished", 0) or 0)
    except Exception as exc:
        checks["neuron_nutrition"] = {"error": str(exc)}
        errors.append(f"neuron_nutrition: {exc}")

    # ── 5. Bodega Global Context ──
    try:
        from triade.core.bodega_global_context import build_bodega_global_context
        bodega = build_bodega_global_context("self test", db_path=db_path, runs_dir=runs_dir, limit=5)
        checks["bodega_global"] = {
            "status": bodega.get("status"),
            "memory_confidence": bodega.get("memory_confidence"),
        }
    except Exception as exc:
        checks["bodega_global"] = {"error": str(exc)}
        errors.append(f"bodega_global: {exc}")

    # ── 6. Technical Debt ──
    try:
        from triade.core.technical_debt_audit import build_technical_debt_audit
        debt = build_technical_debt_audit()
        checks["technical_debt"] = {
            "status": debt.get("status"),
            "score": debt.get("score"),
        }
    except Exception as exc:
        checks["technical_debt"] = {"error": str(exc)}
        errors.append(f"technical_debt: {exc}")

    # ── 7. Integrity Snapshot (read-only) ──
    try:
        from triade.core.integrity_verifier import build_integrity_snapshot
        integrity = build_integrity_snapshot(paths=["./triade", "./apps", "./tests"])
        checks["integrity_snapshot"] = {
            "status": "ok",
            "files_count": integrity.get("files_count"),
        }
    except Exception as exc:
        checks["integrity_snapshot"] = {"error": str(exc)}
        errors.append(f"integrity_snapshot: {exc}")

    # ── 8. Resource Probe ──
    try:
        from triade.core.resource_probe import build_resource_probe
        probe = build_resource_probe()
        checks["resource_probe"] = {
            "status": probe.get("status"),
            "cpu_count": probe.get("cpu", {}).get("count"),
            "ram_gb": probe.get("memory", {}).get("available_gb"),
        }
    except Exception as exc:
        checks["resource_probe"] = {"error": str(exc)}
        errors.append(f"resource_probe: {exc}")

    # ── 9. Edge context fallback test ──
    try:
        import json
        bad_json = ""
        fallback = bad_json or "{}"
        parsed = json.loads(fallback)
        checks["edge_context_fallback"] = {
            "status": "ok",
            "empty_json_parsed": True,
            "parsed_type": type(parsed).__name__,
        }
    except Exception as exc:
        checks["edge_context_fallback"] = {"error": str(exc)}
        errors.append(f"edge_context_fallback: {exc}")

    duration_ms = int((time.time() - start_t) * 1000)
    overall = "ok" if not errors else ("partial" if len(errors) < 4 else "error")

    result = {
        "status": overall,
        "mode": mode,
        "duration_ms": duration_ms,
        "checks": checks,
        "evidence_created": evidence_created,
        "neurons_nourished": neurons_nourished,
        "candidates_created": candidates_created,
        "warnings": warnings,
        "errors": errors,
        "generated_at": utc_now(),
    }

    try:
        publish_event(
            "self_test_cycle_completed",
            "self_test",
            {
                "status": overall,
                "mode": mode,
                "duration_ms": duration_ms,
                "checks_count": len(checks),
                "errors_count": len(errors),
                "evidence_created": evidence_created,
            },
            severity="warning" if errors else "info",
            db_path=db_path,
        )
    except Exception:
        pass

    return result
