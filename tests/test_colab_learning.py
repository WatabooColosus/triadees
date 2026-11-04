"""Prospective education contracts use isolated SQLite and model fixtures only."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_neuron_education_applications import SESSION, _db, _run
from tests.test_neuron_education_cycle import _database, _material
from tools import triade_colab_continuous as panel
from tools import triade_colab_learning as learning
from tools import triade_colab_release as adapter


def test_application_recorder_is_scoped_idempotent_and_preserves_old_sessions(tmp_path):
    db = _db(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO neuron_education_sessions SELECT 'old',curriculum_id,neuron_id,competency_id,state,material_refs_json,independent_source_count,lesson_json,exercise_json,evaluation_json,baseline_score,post_score,applied_run_count,regression_count,result,rollback_ref,created_at,finished_at FROM neuron_education_sessions"
        )
        original = conn.execute(
            "SELECT * FROM neuron_education_sessions WHERE session_id='old'"
        ).fetchone()
    _run(db, "before", cuando="2026-07-29T10:00:00+00:00")
    _run(db, "actual-post", cuando="2026-07-30T10:00:00+00:00")
    _run(db, "unrelated", cuando="2026-07-30T10:00:00+00:00")
    _run(db, "not-activated", cuando="2026-07-30T10:00:00+00:00", activated=0)
    _run(
        db,
        "unsafe",
        cuando="2026-07-30T10:00:00+00:00",
        scores=(0.9, 0.9, 0.1, 0.9, 0.9),
    )
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO verification_reports(run_id,status,coherence_score,memory_score,safety_score,usefulness_score,traceability_score,created_at) SELECT run_id,status,.7,memory_score,safety_score,usefulness_score,traceability_score,created_at FROM verification_reports WHERE run_id='actual-post'"
        )
    ids = {"before", "actual-post", "not-activated", "unsafe"}
    assert (
        learning._record_target_applications(db, SESSION, ids)["applications_added"]
        == 1
    )
    assert (
        learning._record_target_applications(db, SESSION, ids)["applications_added"]
        == 0
    )
    with sqlite3.connect(db) as conn:
        assert (
            conn.execute(
                "SELECT * FROM neuron_education_sessions WHERE session_id='old'"
            ).fetchone()
            == original
        )
        assert conn.execute(
            "SELECT run_id,evidence_ref FROM neuron_education_applications"
        ).fetchall() == [("actual-post", "verification_reports:actual-post")]


def test_budget_denial_never_calls_model(monkeypatch):
    monkeypatch.setattr(
        learning, "_ledger", lambda r5: SimpleNamespace(allows=lambda task: False)
    )
    with pytest.raises(learning.NotReady, match="resource_budget"):
        learning._measured(
            None, "deep_evaluation", lambda: pytest.fail("model must not run")
        )


def test_planning_requires_native_source_and_safety_gates(tmp_path):
    db, neuron = _database(tmp_path)
    long_research_tail = " " + " ".join(f"archiveword{index}" for index in range(80))
    _material(
        db,
        "https://docs.python.org/testing",
        "Pruebas",
        "reparar código requiere pruebas reproducibles" + long_research_tail,
    )
    _material(
        db,
        "https://sqlite.org/testing.html",
        "Validación",
        "código reparado requiere pruebas y validación independiente"
        + long_research_tail,
    )
    engine = learning._engine(db)
    from triade.learning.retrieval import LearningRetriever
    from triade.neurons.curriculum import domain_query, relevant_material

    candidate_materials = engine._candidate_materials()
    query = f"{engine._target(force=True, target_neuron_id=neuron)['mission']} {domain_query('code_repair')}"
    selected = relevant_material(candidate_materials, query, "code_repair")
    assert selected
    assert all(
        not LearningRetriever(db)
        .retrieve_decision(
            query,
            run_id="short-query-control",
            domain="code_repair",
            only_candidate_ids={item["candidate_id"]},
        )
        .injected_ids
        for item in selected
    )
    target = learning._target(engine, db)
    assert target["neuron_id"] == neuron
    assert target["suite"] == "python_text"
    assert len(target["material_ids"]) == 2
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE learning_queue SET status='quarantined'")
    with pytest.raises(learning.NotReady, match="independent_material"):
        learning._target(engine, db)


def test_new_lesson_baseline_uses_only_this_study_and_frozen_material(tmp_path):
    from triade.neurons.functional_evidence import VERSION, ensure_schema

    db, neuron = _database(tmp_path)
    _material(
        db,
        "https://docs.python.org/testing",
        "Pruebas",
        "reparar código requiere pruebas reproducibles",
    )
    _material(
        db,
        "https://sqlite.org/testing.html",
        "Validación",
        "código reparado requiere pruebas y validación independiente",
    )
    _material(
        db,
        "https://example.org/new",
        "Self-produced",
        "reparar código pruebas del mismo examen",
    )
    with sqlite3.connect(db) as conn:
        ensure_schema(conn)
        for idx in range(3):
            for prefix, score in (("mine", 0.0), ("other", 1.0)):
                conn.execute(
                    "INSERT INTO neuron_functional_assessments(run_id,neuron_id,case_id,domain,phase,score,rubric_version,answer_digest,created_at) VALUES(?,?,?,'python_text','pre',?,?,?,'2026-01-01')",
                    (
                        f"{prefix}-{idx}",
                        neuron,
                        f"py{idx + 1}",
                        score,
                        VERSION,
                        "a" * 64,
                    ),
                )
    engine = learning._engine(
        db,
        {"candidate-Pruebas", "candidate-Validación"},
        {f"mine-{idx}" for idx in range(3)},
    )
    result = engine.run_once(target_neuron_id=neuron)
    assert result["status"] == "lesson_prepared"
    with sqlite3.connect(db) as conn:
        baseline, lesson = conn.execute(
            "SELECT baseline_score,lesson_json FROM neuron_education_sessions"
        ).fetchone()
    assert baseline == 0.0
    assert "candidate-Self-produced" not in json.loads(lesson)["candidate_ids"]


@pytest.mark.parametrize("fallback", [False, True])
def test_probe_requires_actual_model_response_and_native_activation_proof(
    monkeypatch, tmp_path, fallback
):
    from triade.core import ollama_blood, runner
    from triade.neurons import functional_evidence

    calls = []

    class Runner:
        def __init__(self, **kwargs):
            pass

        def run(self, **kwargs):
            calls.append(kwargs)
            return {
                "run_id": "actual-fixture-run",
                "response": "4",
                "models": {
                    role: {"ok": not fallback} for role in ("central", "hypothalamus")
                },
            }

    monkeypatch.setattr(runner, "TriadeRunner", Runner)
    monkeypatch.setattr(
        ollama_blood, "check_ollama_blood", lambda: {"reasoning_model": "fixture-model"}
    )
    monkeypatch.setattr(learning, "_measured", lambda r5, kind, call, model: call())
    proofs = []

    def register(db, **kwargs):
        proofs.append(kwargs)
        return {"score": 1.0}

    monkeypatch.setattr(functional_evidence, "register_actual_probe", register)
    state = {
        "domain": "code_repair",
        "neuron_name": "Código",
        "neuron_id": 11,
        "study_id": "study",
    }
    r5 = SimpleNamespace(DB=tmp_path / "db", ROOT=tmp_path)
    case = functional_evidence.CASES_BY_ID["py1"]
    if fallback:
        with pytest.raises(learning.NotReady, match="fallback"):
            learning._probe(r5, state, case, "pre")
        assert not proofs
    else:
        assert learning._probe(r5, state, case, "pre")["run_id"] == "actual-fixture-run"
        assert proofs[0]["answer"] == "4"
        assert calls[0]["context"]["active_neuron"] == "Código"
        assert calls[0]["propose_neurons"] is False
        assert calls[0]["semantic_recall_enabled"] is False


def test_unauthorized_post_material_stops_before_model(monkeypatch, tmp_path):
    from triade.core import ollama_blood
    from triade.neurons.functional_evidence import CASES_BY_ID

    monkeypatch.setattr(
        ollama_blood, "check_ollama_blood", lambda: {"reasoning_model": "fixture"}
    )
    monkeypatch.setattr(
        learning,
        "_authorize_material_ids",
        lambda *args, **kw: [],
    )
    state = {
        "domain": "code_repair",
        "neuron_name": "Código",
        "study_id": "study",
        "material_query": "code",
        "candidate_ids": ["blocked"],
    }
    with pytest.raises(learning.NotReady, match="not_authorized"):
        learning._probe(
            SimpleNamespace(DB=tmp_path / "db"), state, CASES_BY_ID["py1"], "post"
        )


def test_terminal_gate_does_not_retry_inference_forever(monkeypatch, tmp_path):
    calls, receipts = [], []

    def blocked(context):
        calls.append(True)
        raise learning.NotReady("model_fallback_is_not_a_functional_measurement")

    monkeypatch.setattr(learning, "step", blocked)
    r5 = SimpleNamespace(WORK=tmp_path)
    context = {
        "r5": r5,
        "protection_module": SimpleNamespace(
            _json=lambda path, value: receipts.append(value)
        ),
    }
    learning.start(context)
    r5._prospective_learning_monitor["thread"].join(timeout=1)
    assert not r5._prospective_learning_monitor["thread"].is_alive()
    assert len(calls) == 1
    assert receipts[0]["reason"].startswith("model_fallback")


def test_adapter_returns_model_block_without_starting_study(monkeypatch):
    def blocked(context):
        raise learning.NotReady("resource_budget:model_install")

    r5 = SimpleNamespace(DB="unused", _owner_account_status=lambda db: None)
    module = SimpleNamespace(
        NotReady=learning.NotReady,
        prepare_models=blocked,
        start=lambda c: pytest.fail("must not start"),
    )
    monkeypatch.setattr(adapter, "_learning", lambda c: module)
    monkeypatch.setattr(
        adapter,
        "_protection",
        lambda c: SimpleNamespace(_backend_environment=lambda r: None),
    )
    assert adapter.learning_start({"r5": r5}) == {
        "status": "blocked",
        "reason": "resource_budget:model_install",
        "learned": False,
    }


def test_rerender_rebuilds_widgets_but_preserves_verified_context(
    monkeypatch, tmp_path
):
    class Widget:
        def __init__(self, *args, **kwargs):
            self.children = args[0] if args else ()
            self.value = kwargs.get("value", False)
            self.description = kwargs.get("description", "")

        def on_click(self, callback):
            self.callback = callback

        def observe(self, *args, **kwargs):
            pass

    widgets = SimpleNamespace(
        **{
            name: Widget
            for name in (
                "HTML",
                "IntProgress",
                "Output",
                "Layout",
                "Button",
                "Checkbox",
                "Box",
            )
        }
    )
    monkeypatch.setitem(sys.modules, "ipywidgets", widgets)
    google = SimpleNamespace(
        colab=SimpleNamespace(drive=SimpleNamespace(mount=lambda p: None))
    )
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.colab", google.colab)
    display_module = SimpleNamespace(
        display=lambda *args: None, clear_output=lambda **kw: None
    )
    monkeypatch.setitem(sys.modules, "IPython", SimpleNamespace(display=display_module))
    monkeypatch.setitem(sys.modules, "IPython.display", display_module)
    monkeypatch.setattr(panel, "_active_client", None)
    r5 = SimpleNamespace(BASE=tmp_path, WORK=tmp_path)
    old = panel.render(r5, watch=False)
    old.module = SimpleNamespace(
        learning_status=lambda context: {"status": "observed", "neuron_id": 11}
    )
    old.context = {"progress": old.progress, "verified_counts": {"neurons": 16}}
    old.auto_apply = True
    old.progress("Tríade ya está encendida")
    new = panel.render(r5, watch=False)
    assert new is not old
    assert new.view[0] is not old.view[0]
    assert new.module is old.module
    assert new.context["verified_counts"] == {"neurons": 16}
    assert new.context["progress"].__self__ is new
    assert new.auto_apply is True
    assert new.view[-2].value is True
    assert "Iniciar aprendizaje verificado" not in [
        b.description for b in new.view[3].children
    ]
    status_button = next(
        button
        for button in new.view[3].children
        if button.description == "Ver circuito de aprendizaje"
    )
    status_button.callback(None)
    assert "&quot;status&quot;: &quot;observed&quot;" in new.view[-1].value
    assert "&quot;neuron_id&quot;: 11" in new.view[-1].value


def test_learning_attach_uses_stable_html_for_legacy_output_widget(monkeypatch):
    class Widget:
        def __init__(self, *args, **kwargs):
            self.children = args[0] if args else ()
            self.value = kwargs.get("value", "")
            self.description = kwargs.get("description", "")

        def on_click(self, callback):
            self.callback = callback

    class LegacyOutput:
        pass

    widgets = SimpleNamespace(
        Button=Widget,
        HTML=Widget,
        Layout=Widget,
        Box=Widget,
    )
    monkeypatch.setitem(sys.modules, "ipywidgets", widgets)
    display_calls = []
    display_module = SimpleNamespace(display=lambda item: display_calls.append(item))
    monkeypatch.setitem(sys.modules, "IPython", SimpleNamespace(display=display_module))
    monkeypatch.setitem(sys.modules, "IPython.display", display_module)

    class Client:
        def __init__(self):
            self.view = (
                None,
                None,
                None,
                Widget((Widget(description="Estado real"),)),
                None,
                None,
                LegacyOutput(),
            )
            self.results = []

        def progress(self, message):
            pass

        def action(self, name):
            self.results.append(name)
            return {"status": "observed", "action": name}

    client = Client()
    assert learning.attach({"progress": client.progress}) == {
        "status": "learning_controls_attached"
    }
    assert display_calls == [client.view[-1]]
    button = next(
        item
        for item in client.view[3].children
        if item.description == "Ver circuito de aprendizaje"
    )
    button.callback(button)
    assert client.results == ["learning_status"]
    assert "&quot;status&quot;: &quot;observed&quot;" in client.view[-1].value


def test_complete_prospective_fixture_preserves_history_and_does_not_claim_causality(
    monkeypatch, tmp_path
):
    from triade.core import ollama_blood, runner
    from triade.neurons.competency_store import CompetencyStore
    from triade.neurons.functional_evidence import CASES_BY_ID
    from triade.runtime.task_leases import AutonomousTaskStore

    db, neuron = _database(tmp_path)
    AutonomousTaskStore(db)
    _material(
        db,
        "https://docs.python.org/testing",
        "Pruebas",
        "reparar código requiere pruebas reproducibles",
    )
    _material(
        db,
        "https://sqlite.org/testing.html",
        "Validación",
        "código reparado requiere pruebas y validación independiente",
    )
    engine = learning._engine(db)
    competency = engine.store.ensure_competency(neuron, "code_repair", "old-fixture")
    curriculum = engine.store.ensure_curriculum(
        neuron, None, "code_repair", "old-fixture"
    )
    old = CompetencyStore(db).record_session(
        curriculum_id=curriculum["curriculum_id"],
        neuron_id=neuron,
        competency_id=competency["competency_id"],
        state="lesson_prepared",
        material_refs=[],
        independent_sources=0,
        lesson={},
        exercise={},
        evaluation={},
        result="uncertain",
    )
    with sqlite3.connect(db) as conn:
        historical = conn.execute(
            "SELECT * FROM neuron_education_sessions WHERE session_id=?",
            (old["session_id"],),
        ).fetchone()

    calls = []

    class FixtureRunner:
        def __init__(self, **kwargs):
            pass

        def run(self, **kwargs):
            calls.append(kwargs)
            run_id = f"fixture-{len(calls)}"
            is_post = "experimental_material_ids" in kwargs["context"]
            when = "2100-01-01" if is_post else "2000-01-01"
            case = CASES_BY_ID[kwargs["context"]["functional_probe_case"]]
            with sqlite3.connect(db) as conn:
                conn.execute(
                    "INSERT INTO runs(run_id,source,user_input,status) VALUES(?,?,?,'ok')",
                    (run_id, kwargs["source"], "explicit test fixture"),
                )
                conn.execute(
                    "INSERT INTO neuron_activity(run_id,neuron_id,activated,created_at) VALUES(?,?,1,?)",
                    (run_id, neuron, when),
                )
                conn.execute(
                    "INSERT INTO verification_reports(run_id,status,coherence_score,memory_score,safety_score,usefulness_score,traceability_score,errors,warnings) VALUES(?,'ok',.8,.8,.8,.8,.8,'[]','[]')",
                    (run_id,),
                )
            return {
                "run_id": run_id,
                "response": case.expected,
                "models": {role: {"ok": True} for role in ("central", "hypothalamus")},
            }

    monkeypatch.setattr(runner, "TriadeRunner", FixtureRunner)
    monkeypatch.setattr(
        ollama_blood, "check_ollama_blood", lambda: {"reasoning_model": "fixture-model"}
    )
    monkeypatch.setattr(learning, "_measured", lambda r5, kind, call, model: call())
    r5 = SimpleNamespace(
        DB=db,
        ROOT=tmp_path,
        WORK=tmp_path / "work",
        BASE=tmp_path / "drive",
        _owner_account_status=lambda db: None,
    )

    def save(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    protection = SimpleNamespace(
        _json=save,
        _paths=lambda r: tmp_path / "scope",
        _backend_environment=lambda r: None,
        repair=lambda r: {"status": "fixture_backup"},
    )
    context = {"r5": r5, "protection_module": protection}
    for _ in range(12):
        state = learning.step(context)
    assert state["phase"] == "done"
    assert state["result"]["resolution"]["decision"] == "neutral"
    assert state["result"]["session"]["applied_run_count"] == 5
    assert state["result"]["causal_improvement_certified"] is False
    assert len(calls) == 10
    assert all(
        "LEARNING_CANDIDATES_EXPERIMENTAL" not in c["user_input"] for c in calls[:5]
    )
    assert all("LEARNING_CANDIDATES_EXPERIMENTAL" in c["user_input"] for c in calls[5:])
    with sqlite3.connect(db) as conn:
        assert (
            conn.execute(
                "SELECT * FROM neuron_education_sessions WHERE session_id=?",
                (old["session_id"],),
            ).fetchone()
            == historical
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM neuron_functional_assessments"
            ).fetchone()[0]
            == 10
        )
    assert learning.step(context)["phase"] == "done"
    assert len(calls) == 10


def test_inspector_is_read_only_and_reports_no_fake_certification(
    monkeypatch, tmp_path
):
    from triade.core import ollama_blood

    db, _ = _database(tmp_path)
    learning._engine(db)
    before = db.read_bytes()
    (tmp_path / "prospective_launch.json").write_text(
        json.dumps({"status": "blocked", "reason": "embedding_inference_failed"})
    )
    monkeypatch.setattr(
        ollama_blood, "check_ollama_blood", lambda: {"can_embed": False}
    )
    r5 = SimpleNamespace(DB=db, ROOT=tmp_path, WORK=tmp_path)
    result = learning.inspect(r5)
    assert result["read_only"] is True
    assert result["full_certified"] is False
    assert result["functional_probes"] == []
    assert result["study_launch"]["reason"] == "embedding_inference_failed"
    assert db.read_bytes() == before


def test_colab_refresh_reloads_schema_owners_before_cached_runner(monkeypatch):
    """R5's cached imports must not keep old cwd-relative schema paths."""
    order = []
    modules = (
        "triade.core.neuron_registry",
        "triade.core.neuron_activity_store",
        "triade.learning.pipeline",
        "triade.core.experimental_neuron_runtime",
        "triade.core.neuron_autopromoter",
        "triade.core.run_neuron_orchestrator",
        "triade.core.runner",
    )
    for name in modules:
        monkeypatch.setitem(sys.modules, name, SimpleNamespace(__name__=name))
    monkeypatch.setattr(
        learning.Path, "is_dir", lambda path: str(path) == "/content/Triade"
    )
    monkeypatch.setattr(
        learning.importlib, "reload", lambda module: order.append(module.__name__)
    )

    learning._refresh_worker_runtime_modules(reload_runner=True)

    assert set(modules).issubset(order)
    assert order.index("triade.core.neuron_registry") < order.index(
        "triade.core.experimental_neuron_runtime"
    )
    assert order.index("triade.core.neuron_activity_store") < order.index(
        "triade.core.run_neuron_orchestrator"
    )
    assert order.index("triade.learning.pipeline") < order.index("triade.core.runner")


@pytest.mark.parametrize(
    ("source", "artifact"),
    [
        (
            "triade/core/neuron_registry.py",
            "tools/colab_patch_sources/neuron_registry_schema.py",
        ),
        (
            "triade/core/neuron_activity_store.py",
            "tools/colab_patch_sources/neuron_activity_schema.py",
        ),
        (
            "triade/learning/pipeline.py",
            "tools/colab_patch_sources/learning_pipeline_schema.py",
        ),
    ],
)
def test_colab_schema_patch_sources_match_runtime_modules(source, artifact):
    """Old panel accepts tools/ paths; staged sources must match the audited code."""
    root = Path(__file__).resolve().parents[1]
    assert (root / source).read_bytes() == (root / artifact).read_bytes()


def test_colab_study_startup_receipt_records_reason_without_sensitive_data(
    monkeypatch, tmp_path
):
    writes = []

    def persist(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        writes.append(path)

    protection = SimpleNamespace(_json=persist)
    monkeypatch.setattr(adapter, "_protection", lambda context: protection)
    context = {
        "r5": SimpleNamespace(WORK=tmp_path),
        "progress": lambda message: None,
    }
    adapter._record_learning_launch(
        context,
        {
            "status": "blocked",
            "reason": "embedding_inference_failed",
            "models": {"token": "DO_NOT_PERSIST"},
        },
    )
    report = json.loads((tmp_path / "prospective_launch.json").read_text())
    assert report["status"] == "blocked"
    assert report["reason"] == "embedding_inference_failed"
    assert "models" not in report
    assert "DO_NOT_PERSIST" not in json.dumps(report)
    assert len(writes) == 1

    adapter._record_learning_launch(
        context,
        {
            "status": "automatic_learning_blocked",
            "error_type": "RuntimeError",
            "reason": "DO_NOT_PERSIST",
        },
    )
    report = json.loads((tmp_path / "prospective_launch.json").read_text())
    assert report["status"] == "automatic_learning_blocked"
    assert report["reason"] == "RuntimeError"
    assert "DO_NOT_PERSIST" not in json.dumps(report)


def test_colab_install_reports_blocked_learning_launch_without_failing(
    monkeypatch, tmp_path
):
    def persist(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    protection = SimpleNamespace(
        repair=lambda r5: {"status": "encrypted_copy_verified"},
        start_watch=lambda r5: None,
        _json=persist,
    )
    monkeypatch.setattr(adapter, "_auditor", lambda context: None)
    monkeypatch.setattr(adapter, "_protection", lambda context: protection)
    monkeypatch.setattr(
        adapter,
        "_learning",
        lambda context: SimpleNamespace(attach=lambda context: None),
    )
    monkeypatch.setattr(
        adapter,
        "learning_start",
        lambda context: {"status": "blocked", "reason": "embedding_inference_failed"},
    )
    context = {
        "r5": SimpleNamespace(WORK=tmp_path),
        "progress": lambda message: None,
    }
    result = adapter._attach_panel_components(context)
    assert result["status"] == "encrypted_copy_verified"
    assert result["learning"]["status"] == "blocked"
    receipt = json.loads((tmp_path / "prospective_launch.json").read_text())
    assert receipt["status"] == "blocked"
    assert receipt["reason"] == "embedding_inference_failed"


def test_colab_embed_transient_failure_retries_once_with_real_valid_vector(
    monkeypatch, tmp_path
):
    from triade.core import ollama_blood
    from triade.models import ollama_client

    calls = []

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["timeout"] == 120

        def embed(self, model, prompt):
            calls.append(model)
            if len(calls) == 1:
                return ollama_client.EmbeddingResult(
                    ok=False, model=model, error="timed out"
                )
            return ollama_client.EmbeddingResult(
                ok=True, model=model, embeddings=[[0.1, 0.2, 0.3]]
            )

    monkeypatch.setattr(ollama_client, "OllamaClient", FakeClient)
    monkeypatch.setattr(
        ollama_blood,
        "check_ollama_blood",
        lambda: {
            "can_reason": True,
            "can_embed": True,
            "reasoning_model": "fixture-reasoner",
            "embedding_model": "nomic-embed-text:latest",
        },
    )
    monkeypatch.setattr(learning, "_measured", lambda r5, task, fn, model: fn())
    monkeypatch.setattr(learning.time, "sleep", lambda duration: None)
    context = {"r5": SimpleNamespace(DB=tmp_path / "db.sqlite3")}
    result = learning.prepare_models(context)
    assert result["embedding_dimensions"] == 3
    assert len(calls) == 2
    assert context["embedding_probe"] == {
        "status": "passed",
        "failure_code": None,
        "dimensions": 3,
        "vector_count": 1,
        "attempts": 2,
    }


def test_colab_embed_permanent_backend_failure_has_no_retry_or_raw_error(
    monkeypatch, tmp_path
):
    from triade.core import ollama_blood
    from triade.models import ollama_client

    calls = []

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def embed(self, model, prompt):
            calls.append(model)
            return ollama_client.EmbeddingResult(
                ok=False,
                model=model,
                error="HTTP Error 404: PRIVATE_BACKEND_DETAIL",
            )

    monkeypatch.setattr(ollama_client, "OllamaClient", FakeClient)
    monkeypatch.setattr(
        ollama_blood,
        "check_ollama_blood",
        lambda: {
            "can_reason": True,
            "can_embed": True,
            "embedding_model": "nomic-embed-text:latest",
        },
    )
    monkeypatch.setattr(learning, "_measured", lambda r5, task, fn, model: fn())
    context = {"r5": SimpleNamespace(DB=tmp_path / "db.sqlite3")}
    with pytest.raises(learning.NotReady, match="embedding_inference_failed"):
        learning.prepare_models(context)
    assert len(calls) == 1
    assert context["embedding_probe"]["failure_code"] == "model_or_endpoint_not_found"
    assert "PRIVATE_BACKEND_DETAIL" not in json.dumps(context["embedding_probe"])


def test_colab_embedding_failure_categories_do_not_forward_backend_errors():
    from triade.models.ollama_client import EmbeddingResult

    scenarios = {
        "HTTP Error 500: internal": "backend_internal_error",
        "HTTP Error 503: unavailable": "backend_transient",
        "connection refused": "connection_unavailable",
        "UNIQUE_SECRET": "inference_unspecified",
    }
    for backend_error, expected in scenarios.items():
        result = EmbeddingResult(
            ok=False, model="nomic-embed-text", error=backend_error
        )
        assert learning._embedding_failure_code(result) == expected
    empty = EmbeddingResult(ok=True, model="nomic-embed-text", embeddings=[])
    assert learning._embedding_failure_code(empty) == "empty_embedding_response"


def test_colab_neutral_diagnostics_read_only_and_redacts_error_details(
    monkeypatch, tmp_path
):
    from datetime import UTC, datetime

    from triade.core import ollama_blood
    from triade.neurons.functional_evidence import ensure_schema

    db, neuron_id = _database(tmp_path)
    learning._engine(db)
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(db) as conn:
        ensure_schema(conn)
        conn.execute(
            "INSERT INTO neuron_functional_assessments "
            "(run_id,neuron_id,case_id,domain,phase,session_id,score,"
            "rubric_version,answer_digest,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "audited-real-run",
                neuron_id,
                "py1",
                "python_text",
                "pre",
                None,
                0.0,
                "functional-probe-1",
                "digest-not-model-output",
                now,
            ),
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS worker_events "
            "(id INTEGER PRIMARY KEY,run_ref TEXT,task_id INTEGER,"
            "task_type TEXT,event_type TEXT,status TEXT,message TEXT,"
            "payload_json TEXT,created_at TEXT)"
        )
        conn.execute(
            "INSERT INTO worker_events "
            "(task_type,event_type,status,message,payload_json,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                "runner.learning_usage",
                "internal_error",
                "error",
                "error visible only in DB",
                json.dumps(
                    {
                        "error_type": "OperationalError",
                        "error_message": "database is locked TOKEN_DO_NOT_EXPOSE",
                        "traceback": "sensitive path information",
                    }
                ),
                now,
            ),
        )
    before = db.read_bytes()
    monkeypatch.setattr(ollama_blood, "check_ollama_blood", dict)
    r5 = SimpleNamespace(DB=db, ROOT=tmp_path, WORK=tmp_path)
    report = learning.inspect(r5)
    assert report["read_only"] is True
    assert report["full_certified"] is False
    assert db.read_bytes() == before
    assert report["functional_case_scores"] == [
        {
            "neuron_id": neuron_id,
            "phase": "pre",
            "case_id": "py1",
            "runs": 1,
            "passed": 0,
            "mean_score": 0.0,
        }
    ]
    assert report["recent_error_classes"] == [
        {
            "scope": "runner.learning_usage",
            "error_type": "OperationalError",
            "failure_code": "database_locked",
            "at": now,
        }
    ]
    assert "TOKEN_DO_NOT_EXPOSE" not in json.dumps(report)
    assert "sensitive path information" not in json.dumps(report)
