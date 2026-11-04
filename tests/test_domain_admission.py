import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_autonomous_neural_learning import _prepared_db

from triade.core.neuron_creator import NeuronCreator
from triade.core.neuron_formation_pipeline import form_candidate
from triade.core.neuron_registry import NeuronRegistry
from triade.neurons.domain_admission import DomainAdmissionCoordinator


def test_explicit_domain_survives_creator_and_formative_design():
    formed = form_candidate(
        {
            "name": "Ledger reasoning",
            "mission": "Evaluar procedimientos de integridad en tareas posteriores verificables",
            "domain": "ledger_integrity",
        }
    )
    assert formed["creator_spec"]["domain"] == "ledger_integrity"
    assert formed["activation_policy"]["default"] == "candidate_only"


@pytest.mark.parametrize("domain", ["*", "", "x/y", "general,*", "x' OR 1=1"])
def test_invalid_domain_is_not_silently_inferred(domain):
    with pytest.raises(ValueError, match="invalid_neuron_domain"):
        form_candidate({"domain": domain})


def test_routing_gap_persists_candidate_design_without_activation(tmp_path):
    db, candidate_id, _ = _prepared_db(tmp_path, baseline_score=0.5)
    NeuronRegistry(db).update_status("neurona-auditora", "quarantined")
    coordinator = DomainAdmissionCoordinator(db)
    result = coordinator.request(candidate_id, correlation_id="mission-transfer-1")
    assert result["decision"] == "CREATE_NEW_NEURON"
    assert result["creator_spec"]["domain"] == "audit"
    assert result["activated"] is False
    assert result["status"] == "awaiting_held_out_certification"
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM neurons").fetchone()[0] == 1
        assert (
            conn.execute("SELECT COUNT(*) FROM neuron_learning_assignments").fetchone()[
                0
            ]
            == 0
        )
    with ThreadPoolExecutor(max_workers=3) as pool:
        repeated = list(
            pool.map(
                lambda _: coordinator.request(
                    candidate_id, correlation_id="mission-transfer-1"
                ),
                range(3),
            )
        )
    assert {item["event_id"] for item in repeated} == {result["event_id"]}


def test_nearby_domain_is_proposed_for_training_not_declared_compatible(tmp_path):
    db, candidate_id, _ = _prepared_db(tmp_path, baseline_score=0.5)
    registry = NeuronRegistry(db)
    registry.update_status("neurona-auditora", "quarantined")
    spec = NeuronCreator().create(
        "Related specialist", "Process structured records", "audit_records"
    )
    parent_id = registry.register(
        spec,
        contract_payload={
            "domains": ["audit_records"],
            "capabilities": ["records"],
            "learning_interests": ["records"],
        },
    )
    registry.update_status(spec.name, "experimental")
    result = DomainAdmissionCoordinator(db).request(
        candidate_id, correlation_id="mission-transfer-2"
    )
    assert result["decision"] == "EXTEND_EXISTING_NEURON"
    assert result["parent_neuron_id"] == parent_id
    assert result["activated"] is False
    with sqlite3.connect(db) as conn:
        assert (
            conn.execute(
                "SELECT domain FROM neurons WHERE id=?", (parent_id,)
            ).fetchone()[0]
            == "audit_records"
        )


def test_existing_competence_does_not_create_admission(tmp_path):
    db, candidate_id, neuron_id = _prepared_db(tmp_path, baseline_score=0.5)
    result = DomainAdmissionCoordinator(db).request(
        candidate_id, correlation_id="mission-transfer-3"
    )
    assert result["status"] == "existing_competence_available"
    assert result["neuron_id"] == neuron_id
    with sqlite3.connect(db) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM neuron_education_events WHERE event_type='domain_admission_requested'"
            ).fetchone()[0]
            == 0
        )


def test_formed_candidate_is_planned_for_training_and_unmeasurable_stays_candidate(
    tmp_path,
):
    from triade.workers.mission_planner import MissionPlanner

    db, candidate_id, _ = _prepared_db(tmp_path, baseline_score=0.5)
    NeuronRegistry(db).update_status("neurona-auditora", "quarantined")
    coordinator = DomainAdmissionCoordinator(db)
    admission = coordinator.request(candidate_id, correlation_id="training-needed")
    formed = coordinator.form(admission["event_id"], correlation_id="training-needed")
    planned = MissionPlanner(db_path=db)._plan_neuron_formation()
    assert planned[0].payload["admission_phase"] == "training"
    assert planned[0].payload["correlation_id"] == "training-needed"

    def forbidden_generation(*args):
        raise AssertionError("unsupported source must not invoke the motor")

    outcome = coordinator.train(
        admission["event_id"],
        correlation_id="training-needed",
        generate=forbidden_generation,
    )
    assert outcome["status"] == "training_blocked"
    assert outcome["activated"] is False
    with sqlite3.connect(db) as conn:
        assert (
            conn.execute(
                "SELECT status FROM neurons WHERE id=?", (formed["neuron_id"],)
            ).fetchone()[0]
            == "candidate"
        )
    assert not any(
        t.payload.get("admission_phase") == "training"
        for t in MissionPlanner(db_path=db)._plan_neuron_formation()
    )
    with pytest.raises(ValueError, match="successful_training_required"):
        coordinator.certify(
            admission["event_id"],
            correlation_id="training-needed",
            generate=forbidden_generation,
        )


def test_certification_cannot_replace_missing_training_with_structural_review(tmp_path):
    db, candidate_id, _ = _prepared_db(tmp_path, baseline_score=0.5)
    NeuronRegistry(db).update_status("neurona-auditora", "quarantined")
    coordinator = DomainAdmissionCoordinator(db)
    admission = coordinator.request(candidate_id, correlation_id="no-competence-yet")
    formation = coordinator.form(
        admission["event_id"], correlation_id="no-competence-yet"
    )
    with pytest.raises(ValueError, match="completed_training_required"):
        coordinator.certify(
            admission["event_id"],
            correlation_id="no-competence-yet",
            generate=lambda *_: "",
        )
    with sqlite3.connect(db) as conn:
        assert (
            conn.execute(
                "SELECT status FROM neurons WHERE id=?", (formation["neuron_id"],)
            ).fetchone()[0]
            == "candidate"
        )


def test_new_admissions_do_not_starve_already_trained_certification(tmp_path):
    import json

    from triade.workers.mission_planner import MissionPlanner

    db, candidate_id, _ = _prepared_db(tmp_path, baseline_score=0.5)
    NeuronRegistry(db).update_status("neurona-auditora", "quarantined")
    coordinator = DomainAdmissionCoordinator(db)
    old = coordinator.request(candidate_id, correlation_id="existing-curriculum")
    coordinator.form(old["event_id"], correlation_id="existing-curriculum")
    # Planner fixture only: this is not a competence or certification proof.
    with coordinator.router._connect() as connection:
        connection.execute(
            "INSERT INTO neuron_education_events(event_type,payload_json,created_at) VALUES('domain_training_completed',?,CURRENT_TIMESTAMP)",
            (
                json.dumps(
                    {
                        "admission_event_id": old["event_id"],
                        "status": "training_completed",
                    }
                ),
            ),
        )
    fresh = coordinator.request(candidate_id, correlation_id="new-need")
    assert fresh["event_id"] != old["event_id"]
    task = MissionPlanner(db)._plan_neuron_formation()[0]
    assert task.payload["admission_phase"] == "certification"
    assert task.payload["admission_event_id"] == old["event_id"]


def test_pre_admission_rejection_reopens_once_without_retry_storm(
    tmp_path, monkeypatch
):
    import triade.neurons.learning_router as routing
    from triade.workers.mission_planner import MissionPlanner

    db, candidate_id, _ = _prepared_db(tmp_path, baseline_score=0.5)
    current_version = routing.ROUTER_VERSION
    monkeypatch.setattr(routing, "ROUTER_VERSION", "neural-learning-router-1.0.1")
    routing.NeuralLearningRouter(db).record_rejection(
        candidate_id, "no_compatible_neuron"
    )
    monkeypatch.setattr(routing, "ROUTER_VERSION", current_version)
    planner = MissionPlanner(db_path=db)
    assert [
        t.payload["candidate_id"] for t in planner._plan_neural_learning_distribution()
    ] == [candidate_id]
    routing.NeuralLearningRouter(db).record_rejection(
        candidate_id, "no_compatible_neuron"
    )
    assert planner._plan_neural_learning_distribution() == []


@pytest.mark.parametrize(
    "broken_field",
    [
        "inputs_allowed",
        "outputs_allowed",
        "success_metrics",
        "evidence_required",
        "training_requirements",
        "certification_requirements",
    ],
)
def test_incomplete_previous_admission_is_preserved_but_not_reused(
    tmp_path, broken_field
):
    import json

    db, candidate_id, _ = _prepared_db(tmp_path, baseline_score=0.5)
    NeuronRegistry(db).update_status("neurona-auditora", "quarantined")
    coordinator = DomainAdmissionCoordinator(db)
    first = coordinator.request(candidate_id, correlation_id="same-lineage")
    # Corrupt only the isolated test's old proposal to reproduce legacy schema.
    with sqlite3.connect(db) as conn:
        old = json.loads(
            conn.execute(
                "SELECT payload_json FROM neuron_education_events WHERE id=?",
                (first["event_id"],),
            ).fetchone()[0]
        )
        old["creator_spec"][broken_field] = []
        conn.execute(
            "UPDATE neuron_education_events SET payload_json=? WHERE id=?",
            (json.dumps(old), first["event_id"]),
        )
    next_request = coordinator.request(candidate_id, correlation_id="same-lineage")
    assert next_request["event_id"] != first["event_id"]
    assert next_request["request_id"] != first["request_id"]
    assert next_request["creator_spec"][broken_field]
    assert first["event_id"] in next_request["supersedes_event_ids"]
    assert next_request["activated"] is False


def test_changed_lineage_and_capability_create_distinct_requests(tmp_path):
    db, candidate_id, _ = _prepared_db(tmp_path, baseline_score=0.5)
    NeuronRegistry(db).update_status("neurona-auditora", "quarantined")
    coordinator = DomainAdmissionCoordinator(db)
    first = coordinator.request(candidate_id, correlation_id="origin-1")
    second = coordinator.request(candidate_id, correlation_id="origin-2")
    third = coordinator.request(
        candidate_id,
        correlation_id="origin-2",
        required_capability="verified_procedure_execution",
    )
    assert len({x["event_id"] for x in (first, second, third)}) == 3
    assert second["creator_spec"]["correlation_id"] == "origin-2"
    assert (
        coordinator.request(candidate_id, correlation_id="origin-1")["event_id"]
        == first["event_id"]
    )


def test_empty_specification_cannot_enter_training():
    from triade.neurons.domain_admission import require_complete_specification

    with pytest.raises(ValueError, match="SPEC_INCOMPLETE"):
        require_complete_specification({"domain": "audit"})


def test_planner_and_worker_form_only_governed_candidate(tmp_path):
    import json

    from triade.workers.contracts import WorkerRunConfig
    from triade.workers.mission_planner import MissionPlanner
    from triade.workers.task_queue import WorkerTask
    from triade.workers.worker_loop import WorkerLoop

    db, candidate_id, _ = _prepared_db(tmp_path, baseline_score=0.5)
    NeuronRegistry(db).update_status("neurona-auditora", "quarantined")
    request = DomainAdmissionCoordinator(db).request(
        candidate_id, correlation_id="formation-origin"
    )
    planned = MissionPlanner(db_path=db)._plan_neuron_formation()
    assert planned[0].payload["admission_event_id"] == request["event_id"]
    loop = WorkerLoop(
        db_path=db, runs_dir=tmp_path / "runs", lock_file=tmp_path / "worker.lock"
    )
    outcome = loop._neuron_candidate_formation(
        WorkerTask(task_type="neuron_candidate_formation", payload=planned[0].payload),
        "formation-run",
        tmp_path,
        WorkerRunConfig(),
    )
    formation = outcome["formation"]
    assert formation["status"] == "candidate"
    assert formation["activated"] is False
    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT status,contract_json FROM neurons WHERE id=?",
            (formation["neuron_id"],),
        ).fetchone()
        assert row[0] == "candidate"
        assert json.loads(row[1])["correlation_id"] == "formation-origin"
    assert (
        DomainAdmissionCoordinator(db).form(
            request["event_id"], correlation_id="formation-origin"
        )["neuron_id"]
        == formation["neuron_id"]
    )
    next_tasks = MissionPlanner(db_path=db)._plan_neuron_formation()
    assert not any(
        t.payload.get("admission_event_id") == request["event_id"]
        and t.payload.get("admission_phase") != "training"
        for t in next_tasks
    )
    assert next_tasks[0].payload["admission_phase"] == "training"


def test_resource_only_certification_retry_is_bounded_and_not_a_competence_override(
    tmp_path,
):
    import json

    from triade.neurons.domain_admission import DomainAdmissionCoordinator

    coordinator = DomainAdmissionCoordinator(tmp_path / "retry.db")
    assert coordinator.certification_attempt(42) == 1
    payload = {
        "admission_event_id": 42,
        "status": "certification_failed",
        "arms": {
            "treatment": [{"passed": True, "error": None}],
            "negative_control": [
                {"passed": False, "error": "certification_resource_budget_exceeded"}
            ],
        },
    }

    def receipt(value):
        with coordinator.router._connect() as connection:
            connection.execute(
                "INSERT INTO neuron_education_events(event_type,payload_json,created_at) VALUES('domain_certification_completed',?,CURRENT_TIMESTAMP)",
                (json.dumps(value),),
            )

    receipt(payload)
    assert coordinator.certification_attempt(42) == 2
    receipt(payload)
    assert coordinator.certification_attempt(42) == 3
    receipt(payload)
    assert coordinator.certification_attempt(42) is None
    payload["admission_event_id"] = 43
    payload["arms"]["treatment"] = [{"passed": False, "error": None}]
    receipt(payload)
    assert coordinator.certification_attempt(43) is None


def test_training_blocked_retries_only_after_evaluator_version_upgrade(
    tmp_path, monkeypatch
):
    """Un bloqueo sin oráculo no queda fijado, pero nunca se promueve sin él."""
    from triade.neurons import curriculum
    from triade.workers.mission_planner import MissionPlanner

    db, candidate_id, _ = _prepared_db(tmp_path, baseline_score=0.5)
    NeuronRegistry(db).update_status("neurona-auditora", "quarantined")
    coordinator = DomainAdmissionCoordinator(db)
    admission = coordinator.request(candidate_id, correlation_id="ab-evaluator-retry")
    formed = coordinator.form(
        admission["event_id"], correlation_id="ab-evaluator-retry"
    )

    def forbidden(*_args):
        raise AssertionError("sin oráculo no se invoca el modelo")

    blocked1 = coordinator.train(
        admission["event_id"],
        correlation_id="ab-evaluator-retry",
        generate=forbidden,
    )
    assert blocked1["status"] == "training_blocked"
    assert blocked1["curriculum_version"] == 1
    assert not any(
        t.payload.get("admission_phase") == "training"
        for t in MissionPlanner(db_path=db)._plan_neuron_formation()
    )

    monkeypatch.setattr(curriculum, "ADMISSION_CURRICULUM_VERSION", 2)
    plans = MissionPlanner(db_path=db)._plan_neuron_formation()
    assert any(
        t.payload.get("admission_event_id") == admission["event_id"]
        and t.payload.get("admission_phase") == "training"
        for t in plans
    )
    blocked2 = coordinator.train(
        admission["event_id"],
        correlation_id="ab-evaluator-retry",
        generate=forbidden,
    )
    assert blocked2["status"] == "training_blocked"
    assert blocked2["curriculum_version"] == 2
    with sqlite3.connect(db) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM neuron_education_events "
                "WHERE event_type='domain_training_completed' "
                "AND json_extract(payload_json,'$.admission_event_id')=?",
                (admission["event_id"],),
            ).fetchone()[0]
            == 2
        )
        assert (
            conn.execute(
                "SELECT status FROM neurons WHERE id=?", (formed["neuron_id"],)
            ).fetchone()[0]
            == "candidate"
        )
    assert not any(
        t.payload.get("admission_phase") == "training"
        for t in MissionPlanner(db_path=db)._plan_neuron_formation()
    )
