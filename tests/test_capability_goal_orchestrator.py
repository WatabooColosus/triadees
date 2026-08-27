from triade.core.capability_resolver import CapabilityResolver
from triade.core.goal_orchestrator import GoalOrchestrator


def test_resolver_only_delegates_explicit_actions():
    resolver = CapabilityResolver()
    assert resolver.resolve("Hola, ¿cómo estás?").actionable is False
    research = resolver.resolve("Investiga documentación sobre materiales auxéticos")
    assert research.worker_task_type == "goal_research"
    assert research.requires_human_approval is False
    install = resolver.resolve("Instala este paquete y pruébalo")
    assert install.execution_mode == "human_approval"
    assert install.requires_human_approval is True


def test_orchestrator_persists_and_queues_safe_goal(tmp_path):
    orchestrator = GoalOrchestrator(tmp_path / "triade.db")
    result = orchestrator.accept("Prueba todos los tests", run_id="run-1")
    assert result["status"] == "queued"
    assert result["task_id"] is not None
    status = orchestrator.status(result["goal_id"])
    assert status["goal"]["status"] == "queued"
    assert status["steps"][0]["status"] == "queued"
    orchestrator.record_task_result(
        {"goal_id": result["goal_id"], "goal_step_id": result["step_id"]},
        {"status": "ok"},
    )
    assert orchestrator.status(result["goal_id"])["goal"]["status"] == "completed"


def test_install_goal_waits_for_human_approval(tmp_path):
    result = GoalOrchestrator(tmp_path / "triade.db").accept(
        "Instala una dependencia desconocida", run_id="run-2"
    )
    assert result["status"] == "awaiting_approval"
    assert result["task_id"] is None


def test_candidate_or_no_evidence_never_completes_goal(tmp_path):
    for index, terminal in enumerate(("candidate_created", "no_evidence")):
        orchestrator = GoalOrchestrator(tmp_path / f"triade-{index}.db")
        accepted = orchestrator.accept(
            "Investiga documentación sobre materiales auxéticos", run_id=f"run-{index}"
        )
        orchestrator.record_task_result(
            {
                "goal_id": accepted["goal_id"],
                "goal_step_id": accepted["step_id"],
            },
            {"status": terminal},
        )
        status = orchestrator.status(accepted["goal_id"])
        assert status["goal"]["status"] == "blocked"
        assert status["steps"][0]["status"] == "blocked"


def test_un_goal_bloqueado_registra_por_que(tmp_path):
    """`blocked` es terminal: si no dice el motivo, la muerte es indiagnosticable.

    Desde `blocked` un goal sólo puede ir a `archived` — no se reintenta, no se
    aprueba, no vuelve. El 2026-08-27 tres peticiones reales («crea un
    diagnóstico interno breve… y guárdalo») murieron en 0,77 segundos con
    `reason: "blocked"`, que es el propio estado repetido. El motivo verdadero,
    `target_and_authorized_root_required`, existía —el handler lo devuelve— pero
    sólo llegaba a `autonomous_tasks.last_error`, en otra tabla y sin enlace con
    el goal, así que desde el goal no había forma de saber qué había fallado.
    """
    orchestrator = GoalOrchestrator(tmp_path / "triade.db")
    accepted = orchestrator.accept(
        "Redacta un informe breve y guárdalo como entregable", run_id="run-motivo"
    )
    orchestrator.record_task_result(
        {"goal_id": accepted["goal_id"], "goal_step_id": accepted["step_id"]},
        {"status": "blocked", "reason": "target_and_authorized_root_required"},
    )

    status = orchestrator.status(accepted["goal_id"])
    assert status["goal"]["status"] == "blocked"

    eventos = status.get("events") or []
    motivos = [str(e.get("reason") or "") for e in eventos]
    assert any("target_and_authorized_root_required" in m for m in motivos), motivos
    # El estado sigue estando, no se sustituye por el detalle.
    assert any(m.startswith("blocked:") for m in motivos), motivos


def test_un_bloqueo_sin_detalle_conserva_el_estado_a_secas(tmp_path):
    """No se inventa un motivo cuando el handler no lo da."""
    orchestrator = GoalOrchestrator(tmp_path / "triade.db")
    accepted = orchestrator.accept(
        "Investiga documentación sobre materiales auxéticos", run_id="run-sin-motivo"
    )
    orchestrator.record_task_result(
        {"goal_id": accepted["goal_id"], "goal_step_id": accepted["step_id"]},
        {"status": "no_evidence"},
    )

    eventos = orchestrator.status(accepted["goal_id"]).get("events") or []
    motivos = [str(e.get("reason") or "") for e in eventos]
    assert "no_evidence" in motivos
    assert not any(m.endswith(":") for m in motivos), motivos
