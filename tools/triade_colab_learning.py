"""Owner-requested prospective education using genuine TriadeRunner probes.

Never changes autonomy, stable promotion gates, old lessons, run timestamps,
answer keys, or worker leases. A failed prerequisite is an explicit outcome.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import importlib
import json
import math
import statistics
import sys
import threading
import traceback
import uuid
from html import escape
from pathlib import Path

from triade.db import sqlite3


class NotReady(RuntimeError):
    pass


def _connect(db):
    conn = sqlite3.connect(
        Path(db).resolve().as_uri() + "?mode=ro", uri=True, timeout=5
    )
    conn.row_factory = sqlite3.Row
    return conn


def _tables(conn):
    return {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _read(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _ledger(r5):
    from triade.runtime.resource_ledger import ResourceLedger, load_runtime_budget

    ledger = object.__new__(ResourceLedger)
    ledger.db_path = Path(r5.DB)
    ledger.budget = load_runtime_budget(Path(r5.ROOT) / "triade.yml")
    return ledger


def _measured(r5, task_class, call, model=None):
    from triade.runtime.resource_ledger import ResourceMeasurementCollector

    ledger = _ledger(r5)
    if not ledger.allows(task_class):
        raise NotReady("resource_budget:" + task_class)
    collector = ResourceMeasurementCollector()
    success = False
    try:
        result = call()
        success = True
        return result
    finally:
        ledger.record_usage(
            task_id=None,
            worker_id="owner_requested_prospective_education",
            usage=collector.finish(),
            success=success,
            task_class=task_class,
            model=model,
        )


def _refresh_worker_runtime_modules(*, reload_runner=False):
    """Use a runtime-patched WorkerStateStore in an already-live Colab kernel.

    The panel can update files while the notebook process keeps Python modules
    cached. Reload the worker modules that imported the store before creating a
    new TriadeRunner, otherwise learning would continue using the pre-patch
    schema resolver.
    """
    importlib.invalidate_caches()
    names = (
        "triade.workers.state_store",
        "triade.workers.task_queue",
        "triade.workers.worker_loop",
        "triade.workers.background_service",
        "triade.services.supervisor",
    )
    if reload_runner:
        names += (
            "triade.core.goal_orchestrator",
            "triade.core.learning_planner",
            "triade.core.runner",
        )
    for name in names:
        module = sys.modules.get(name)
        if module is not None:
            importlib.reload(module)


def inspect(r5):
    from triade.core.ollama_blood import check_ollama_blood
    from triade.neurons.functional_evidence import supported_domain

    report = {
        "read_only": True,
        "full_certified": False,
        "blood": check_ollama_blood(),
        "education": {},
        "recent_error_groups": [],
        "neurons": [],
    }
    with contextlib.closing(_connect(r5.DB)) as conn:
        tables = _tables(conn)
        for table, column in (
            ("neurons", "status"),
            ("neuron_education_sessions", "state"),
            ("learning_queue", "status"),
            ("neuron_learning_assignments", "status"),
        ):
            if table in tables:
                report["education"][table] = dict(
                    conn.execute(
                        f'SELECT "{column}", COUNT(*) FROM "{table}" GROUP BY "{column}"'
                    )
                )
        if "neurons" in tables:
            report["neurons"] = [
                {
                    "id": row["id"],
                    "status": row["status"],
                    "functional_suite": supported_domain(row["name"], row["domain"]),
                }
                for row in conn.execute(
                    "SELECT id,name,domain,status FROM neurons ORDER BY id LIMIT 100"
                )
            ]
        if "neuron_education_sessions" in tables:
            report["recent_sessions"] = [
                dict(row)
                for row in conn.execute(
                    "SELECT session_id,neuron_id,state,independent_source_count,baseline_score,post_score,applied_run_count,result,created_at FROM neuron_education_sessions ORDER BY created_at DESC LIMIT 20"
                )
            ]
            report["lesson_gates"] = []
            for row in conn.execute(
                "SELECT session_id,neuron_id,lesson_json,baseline_score FROM neuron_education_sessions WHERE state='lesson_prepared'"
            ):
                ids = json.loads(row["lesson_json"] or "{}").get("candidate_ids", [])
                states = [
                    item[0]
                    for candidate_id in ids
                    for item in conn.execute(
                        "SELECT status FROM learning_queue WHERE candidate_id=?",
                        (candidate_id,),
                    )
                ]
                missions = conn.execute(
                    "SELECT COUNT(*) FROM neuron_missions WHERE neuron_id=? AND status IN ('experimental','active')",
                    (row["neuron_id"],),
                ).fetchone()[0]
                report["lesson_gates"].append(
                    {
                        "session_id": row["session_id"],
                        "neuron_id": row["neuron_id"],
                        "material_states": states,
                        "eligible_missions": missions,
                        "baseline_present": row["baseline_score"] is not None,
                        "application_ready": bool(
                            any(
                                s in ("evidence_verified", "consolidated")
                                for s in states
                            )
                            or missions
                        ),
                    }
                )
        if "neuron_education_events" in tables:
            report["admission_blocks"] = []
            for row in conn.execute(
                "SELECT payload_json,created_at FROM neuron_education_events WHERE event_type='domain_training_completed' ORDER BY id DESC LIMIT 20"
            ):
                payload = json.loads(row[0] or "{}")
                if payload.get("status") == "training_blocked":
                    report["admission_blocks"].append(
                        {
                            "neuron_id": payload.get("neuron_id"),
                            "reason": payload.get("reason"),
                            "at": row[1],
                            "activated": False,
                        }
                    )
        if "neuron_functional_assessments" in tables:
            report["functional_probes"] = [
                dict(row)
                for row in conn.execute(
                    "SELECT neuron_id,phase,COUNT(*) AS runs,COUNT(DISTINCT case_id) AS cases FROM neuron_functional_assessments GROUP BY neuron_id,phase"
                )
            ]
        else:
            report["functional_probes"] = []
        if "worker_events" in tables:
            report["recent_error_groups"] = [
                dict(row)
                for row in conn.execute(
                    "SELECT task_type,event_type,COUNT(*) AS count,MAX(created_at) AS last_at FROM worker_events WHERE status IN ('error','failed') AND julianday(created_at)>=julianday('now','-15 minutes') GROUP BY task_type,event_type ORDER BY last_at DESC LIMIT 20"
                )
            ]
        if "autonomous_tasks" in tables:
            report["queue_order"] = [
                dict(row)
                for row in conn.execute(
                    "SELECT task_id,task_type,status,attempt,priority,ROUND((julianday('now')-julianday(created_at))*1440,2) AS age_minutes,priority-MIN(100,CAST((julianday('now')-julianday(created_at))*1440 AS INTEGER)) AS effective_priority FROM autonomous_tasks WHERE status IN ('pending','queued','deferred','retry_wait','leased','running') ORDER BY effective_priority,created_at LIMIT 20"
                )
            ]
    try:
        report["resource_policy"] = _ledger(r5).policy()
    except (OSError, sqlite3.Error, ValueError):
        report["resource_policy"] = {"status": "not_observed"}
    report["prospective_study"] = _read(Path(r5.WORK) / "prospective_learning.json")
    report["study_wait"] = _read(Path(r5.WORK) / "prospective_wait.json")
    if report["study_wait"].get("at", "") < report["prospective_study"].get(
        "updated_at", ""
    ):
        report["study_wait"] = {}
    monitor = getattr(r5, "_prospective_learning_monitor", None)
    report["study_monitor_alive"] = bool(
        monitor and monitor["thread"].is_alive() and not monitor["stop"].is_set()
    )
    report["truth"] = (
        "Application, functional trend and causal improvement are distinct. Old sessions without pre-lesson measurements remain uncertified."
    )
    return report


def prepare_models(context):
    import shutil

    import psutil

    from triade.core.ollama_blood import check_ollama_blood
    from triade.models.ollama_client import OllamaClient

    r5 = context["r5"]
    blood = check_ollama_blood()
    if not blood.get("can_reason"):
        raise NotReady("reasoning_model_not_available")
    if not blood.get("can_embed"):
        if (
            shutil.disk_usage(r5.ROOT).free < 4 * 1024**3
            or psutil.virtual_memory().available < 1.5 * 1024**3
        ):
            raise NotReady("insufficient_resources_for_embedding_setup")
        context["progress"](
            "Instalando el embedding compatible que falta; la API continúa activa…"
        )
        _measured(
            r5,
            "model_install",
            lambda: r5.run(["ollama", "pull", "nomic-embed-text:latest"], timeout=900),
            "nomic-embed-text:latest",
        )
        blood = check_ollama_blood()
    if not blood.get("can_embed"):
        raise NotReady("embedding_model_not_available_after_setup")
    embedding = _measured(
        r5,
        "light",
        lambda: OllamaClient(db_path=r5.DB).embed(
            blood["embedding_model"],
            "Comprobación de recuperación semántica de Tríade.",
        ),
        blood["embedding_model"],
    )
    if (
        not embedding.ok
        or embedding.dimensions <= 0
        or not all(
            math.isfinite(value) for vector in embedding.embeddings for value in vector
        )
    ):
        raise NotReady("embedding_inference_failed")
    return {
        "status": "models_ready",
        "reasoning_model": blood["reasoning_model"],
        "embedding_model": blood["embedding_model"],
        "embedding_dimensions": embedding.dimensions,
    }


def _engine(db, material_ids=None, baseline_run_ids=()):
    from triade.neurons.competency_store import CompetencyStore
    from triade.neurons.education_cycle import NeuronEducationCycle
    from triade.neurons.functional_evidence import MIN_DISTINCT_CASES, VERSION

    class FunctionalBaselineStore(CompetencyStore):
        def record_session(self, **kwargs):
            if kwargs.get("state") == "lesson_prepared":
                with contextlib.closing(_connect(self.db_path)) as conn:
                    rows = conn.execute(
                        "SELECT run_id,case_id,score FROM neuron_functional_assessments WHERE neuron_id=? AND phase='pre' AND rubric_version=? AND datetime(created_at)<datetime('now') ORDER BY datetime(created_at) DESC,id DESC",
                        (kwargs["neuron_id"], VERSION),
                    ).fetchall()
                latest = {}
                for run_id, case, score in rows:
                    if run_id in baseline_run_ids:
                        latest.setdefault(case, float(score))
                if len(latest) < MIN_DISTINCT_CASES:
                    raise NotReady("prospective_functional_baseline_missing")
                kwargs["baseline_score"] = statistics.mean(latest.values())
            return super().record_session(**kwargs)

    class FrozenMaterialCycle(NeuronEducationCycle):
        def _candidate_materials(self):
            rows = super()._candidate_materials()
            return (
                rows
                if material_ids is None
                else [row for row in rows if row["candidate_id"] in material_ids]
            )

    engine = FrozenMaterialCycle(db)
    engine.store = FunctionalBaselineStore(db)
    return engine


def _authorize_material_ids(db, candidate_ids, domain, run_id):
    """Apply the native retrieval gates to curriculum-selected material IDs.

    Curriculum relevance is established by ``relevant_material`` before this
    helper is called.  The native retriever's lexical threshold is designed for
    open-ended search, so comparing a short question against a long research
    document silently drops otherwise eligible material.  Here each selected
    document is retrieved only against its own content and ID; state,
    provenance, canonicality, domain and safety checks remain native.
    """
    from triade.learning.retrieval import LearningRetriever

    ids = sorted({str(candidate_id) for candidate_id in candidate_ids if candidate_id})
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with contextlib.closing(_connect(db)) as conn:
        rows = conn.execute(
            f"SELECT candidate_id,content FROM learning_queue "
            f"WHERE candidate_id IN ({placeholders}) AND domain=?",
            (*ids, domain),
        ).fetchall()
    retriever = LearningRetriever(db)
    matches = []
    for row in rows:
        decision = retriever.retrieve_decision(
            str(row["content"] or ""),
            run_id=run_id,
            limit=1,
            domain=domain,
            only_candidate_ids={str(row["candidate_id"])},
        )
        matches.extend(decision.matches)
    return matches


def _target(engine, db):
    from triade.neurons.curriculum import domain_query, relevant_material, source_domain
    from triade.neurons.functional_evidence import supported_domain

    with contextlib.closing(_connect(db)) as conn:
        candidates = list(
            conn.execute(
                "SELECT id,name,domain FROM neurons WHERE status='experimental' ORDER BY id LIMIT 100"
            )
        )
    for neuron in candidates:
        domain = supported_domain(neuron["name"], neuron["domain"])
        if domain is None:
            continue
        # The owner requests a bounded evaluation now. Override only the review
        # calendar, never source, safety, activation or promotion gates.
        target = engine._target(force=True, target_neuron_id=neuron["id"])
        if not target:
            continue
        materials = engine._candidate_materials()
        query = f"{target.get('mission') or target['name']} {domain_query(target['domain'])}"
        chosen = relevant_material(
            materials,
            query,
            target["domain"],
        )
        # Match the official cycle's same-domain completion, with the same source gate.
        seen = {item["candidate_id"] for item in chosen}
        for material in materials:
            if len(chosen) >= engine._required_sources():
                break
            if (
                material.get("domain") == target["domain"]
                and material["candidate_id"] not in seen
            ):
                chosen.append(material)
                seen.add(material["candidate_id"])
        authorized = _authorize_material_ids(
            db,
            {item["candidate_id"] for item in chosen},
            target["domain"],
            "study-planning-" + uuid.uuid4().hex,
        )
        authorized_ids = {match.candidate_id for match in authorized}
        chosen = [item for item in chosen if item["candidate_id"] in authorized_ids]
        sources = {
            source_domain(ref)
            for item in chosen
            for ref in engine._material_source_refs(item)
        }
        if len(sources) >= engine._required_sources():
            return {
                "neuron_id": int(neuron["id"]),
                "neuron_name": neuron["name"],
                "domain": neuron["domain"],
                "suite": domain,
                "material_ids": sorted({item["candidate_id"] for item in chosen}),
                "material_query": query,
            }
    raise NotReady("no_supported_neuron_with_independent_material")


def _probe(r5, state, case, phase):
    from triade.core.ollama_blood import check_ollama_blood
    from triade.neurons.functional_evidence import register_actual_probe

    model = check_ollama_blood().get("reasoning_model")
    if not model:
        raise NotReady("reasoning_model_not_available")
    context = {
        "semantic_domain": state["domain"],
        "domain": state["domain"],
        # An explicit target goes through the native should_activate policy;
        # it does not write activity, change status, or force an activation.
        "active_neuron": state["neuron_name"],
        "functional_probe_case": case.id,
        "prospective_study_id": state["study_id"],
    }
    prompt = f"{case.question}\nContexto de dominio: {state['domain']}."
    material_ids = []
    if phase == "post":
        from triade.learning.retrieval import build_learning_block

        # This is a bounded experiment, not production knowledge injection.
        # The native experimental retriever keeps state, source, deduplication
        # and safety gates. Nothing is consolidated or reclassified here.
        matches = _authorize_material_ids(
            r5.DB,
            set(state.get("candidate_ids", [])),
            state["domain"],
            "study-" + uuid.uuid4().hex,
        )
        material_ids = [match.candidate_id for match in matches]
        if not material_ids:
            raise NotReady("lesson_material_not_authorized_by_experimental_retriever")
        prompt = build_learning_block(matches) + "\n" + prompt
        context["experimental_material_ids"] = material_ids
    _refresh_worker_runtime_modules(
        reload_runner=Path("/content/Triade").is_dir()
    )
    from triade.core.runner import TriadeRunner

    runner = TriadeRunner(
        db_path=r5.DB,
        runs_dir=Path(r5.ROOT) / "runs",
        use_ollama=True,
        auto_select_models=False,
        central_model=model,
        hypothalamus_model=model,
        config_path=Path(r5.ROOT) / "triade.yml",
    )

    def run():
        result = runner.run(
            user_input=prompt,
            source="neuron_functional_probe",
            context=context,
            propose_neurons=False,
            semantic_recall_enabled=False,
        )
        models = result.get("models", {})
        if not all(
            models.get(role, {}).get("ok") is True
            for role in ("central", "hypothalamus")
        ):
            raise NotReady("model_fallback_is_not_a_functional_measurement")
        proof = register_actual_probe(
            r5.DB,
            run_id=str(result.get("run_id") or ""),
            neuron_id=state["neuron_id"],
            case_id=case.id,
            phase=phase,
            session_id=state.get("session_id") if phase == "post" else None,
            answer=str(result.get("response") or ""),
        )
        return {
            "run_id": result["run_id"],
            "case_id": case.id,
            "score": proof["score"],
            "experimental_material_ids": material_ids,
            "production_application_certified": False,
        }

    return _measured(r5, "deep_evaluation", run, model)


def _record_target_applications(db, session_id, run_ids):
    from triade.neurons.education_applications import NeuronEducationApplicationRecorder

    recorder = NeuronEducationApplicationRecorder(db)
    with contextlib.closing(recorder._connect()) as conn, conn:
        session = conn.execute(
            "SELECT neuron_id,created_at,state FROM neuron_education_sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if not session or session["state"] != "lesson_prepared":
            return {
                "applications_added": 0,
                "reason": "session_already_closed_or_missing",
            }
        added = 0
        existing = {
            row[0]
            for row in conn.execute(
                "SELECT run_id FROM neuron_education_applications WHERE session_id=?",
                (session_id,),
            )
        }
        for row in recorder._runs_de_la_neurona(
            conn, session["neuron_id"], desde=session["created_at"], hasta=None
        ):
            if row["run_id"] not in run_ids or row["run_id"] in existing:
                continue
            score = recorder._score(row)
            if (
                score is None
                or row["safety_score"] is None
                or row["safety_score"] < 0.6
            ):
                continue
            conn.execute(
                "INSERT INTO neuron_education_applications (session_id,run_id,outcome_score,evidence_ref,created_at) VALUES(?,?,?,?,?)",
                (
                    session_id,
                    row["run_id"],
                    score,
                    f"verification_reports:{row['run_id']}",
                    dt.datetime.now(dt.UTC).isoformat(),
                ),
            )
            existing.add(row["run_id"])
            added += 1
        conn.execute(
            "UPDATE neuron_education_sessions SET applied_run_count=(SELECT COUNT(*) FROM neuron_education_applications WHERE session_id=?) WHERE session_id=?",
            (session_id, session_id),
        )
    return {"applications_added": added, "scope": "current_prospective_lesson_only"}


def _resolve(db, session_id, run_ids):
    from triade.neurons.education_resolver import NeuronEducationResolver

    class TargetResolver(NeuronEducationResolver):
        def _next_session(self, conn):
            return conn.execute(
                "SELECT * FROM neuron_education_sessions WHERE session_id=? AND state='lesson_prepared'",
                (session_id,),
            ).fetchone()

    recorded = _record_target_applications(db, session_id, run_ids)
    result = TargetResolver(db).resolve_once()
    with contextlib.closing(_connect(db)) as conn:
        actual = conn.execute(
            "SELECT state,result,baseline_score,post_score,applied_run_count FROM neuron_education_sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
    return {
        "recorder": recorded,
        "resolution": result,
        "session": dict(actual) if actual else None,
        "causal_improvement_certified": False,
        "full_certified": False,
    }


def _save(context, state):
    protection = context["protection_module"]
    path = Path(context["r5"].WORK) / "prospective_learning.json"
    state["updated_at"] = dt.datetime.now(dt.UTC).isoformat()
    protection._json(path, state)
    source = protection._paths(context["r5"]).name
    protection._json(
        Path(context["r5"].BASE)
        / "operacion_colab_continua"
        / "aprendizaje"
        / source
        / "current.json",
        state,
    )
    return state


def _study_state(context):
    r5 = context["r5"]
    state = _read(Path(r5.WORK) / "prospective_learning.json")
    if state:
        return state
    source = context["protection_module"]._paths(r5).name
    return _read(
        Path(r5.BASE)
        / "operacion_colab_continua"
        / "aprendizaje"
        / source
        / "current.json"
    )


def step(context):
    """One real probe or one official curriculum transition; never a synthetic run."""
    from triade.neurons.functional_evidence import CASES, VERSION

    r5 = context["r5"]
    r5._owner_account_status(r5.DB)
    context["protection_module"]._backend_environment(r5)
    state = _study_state(context)
    if state.get("phase") == "blocked":
        return state
    if not state:
        engine = _engine(r5.DB)
        state = {
            "phase": "pre",
            "rubric_version": VERSION,
            **_target(engine, r5.DB),
            "pre": [],
            "post": [],
            "stable_promotion_authorized": False,
            "study_id": "prospective-" + uuid.uuid4().hex,
            "measurement_scope": "textual_domain_battery; not device, vision or code execution",
            "causal_improvement_certified": False,
            "review_trigger": "owner_requested_prospective_evaluation",
        }
    if state.get("rubric_version") != VERSION:
        raise NotReady("rubric_changed_requires_review")
    cases = [case for case in CASES if case.domain == state["suite"]][:5]
    if len(cases) < 3:
        raise NotReady("functional_suite_incomplete")
    with contextlib.closing(_connect(r5.DB)) as conn:
        for proof in state["pre"] + state["post"]:
            if (
                "neuron_functional_assessments" not in _tables(conn)
                or not conn.execute(
                    "SELECT 1 FROM neuron_functional_assessments WHERE run_id=? AND neuron_id=?",
                    (proof["run_id"], state["neuron_id"]),
                ).fetchone()
            ):
                raise NotReady("study_state_ahead_of_restored_memory")
        active = conn.execute(
            "SELECT COUNT(*) FROM autonomous_tasks WHERE status IN ('leased','running')"
        ).fetchone()[0]
    if active:
        raise NotReady("backend_tasks_active_wait_for_window")
    if state["phase"] == "done":
        return state
    if state["phase"] in ("pre", "post"):
        phase = state["phase"]
        if len(state[phase]) < len(cases):
            state[phase].append(_probe(r5, state, cases[len(state[phase])], phase))
        if len(state[phase]) == len(cases):
            state["phase"] = "lesson" if phase == "pre" else "resolve"
    elif state["phase"] == "lesson":
        lesson = _engine(
            r5.DB, state["material_ids"], {proof["run_id"] for proof in state["pre"]}
        ).run_once(force=True, target_neuron_id=state["neuron_id"])
        if lesson.get("status") != "lesson_prepared":
            raise NotReady("official_curriculum:" + str(lesson.get("status")))
        with contextlib.closing(_connect(r5.DB)) as conn:
            stored = conn.execute(
                "SELECT lesson_json FROM neuron_education_sessions WHERE session_id=?",
                (lesson["session_id"],),
            ).fetchone()
        state.update(
            session_id=lesson["session_id"],
            candidate_ids=json.loads(stored[0]).get("candidate_ids", []),
            phase="post",
        )
    elif state["phase"] == "resolve":
        state.update(
            phase="done",
            result=_resolve(
                r5.DB, state["session_id"], {proof["run_id"] for proof in state["post"]}
            ),
        )
        # Genuine new memory must have a durable, decryptable checkpoint.
        state["backup"] = context["protection_module"].repair(r5)
    return _save(context, state)


def start(context):
    r5 = context["r5"]
    previous = getattr(r5, "_prospective_learning_monitor", None)
    if previous and previous["thread"].is_alive():
        return {"status": "study_already_running"}
    stop = threading.Event()

    def watch():
        while not stop.is_set():
            try:
                state = step(context)
                if state.get("phase") in ("done", "blocked"):
                    break
            except NotReady as exc:
                context["protection_module"]._json(
                    Path(r5.WORK) / "prospective_wait.json",
                    {"reason": str(exc), "at": dt.datetime.now(dt.UTC).isoformat()},
                )
                # A model run or material gate must not consume quota forever.
                # Only genuinely transient scheduling/budget waits are retried.
                if not str(exc).startswith(
                    ("resource_budget:", "backend_tasks_active_")
                ):
                    break
            except Exception as exc:  # noqa: BLE001 - stop rather than repeatedly spend inference budget
                context["protection_module"]._json(
                    Path(r5.WORK) / "prospective_wait.json",
                    {
                        "reason": "study_stopped",
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:1000],
                        "traceback": traceback.format_exc(limit=8)[-4000:],
                        "at": dt.datetime.now(dt.UTC).isoformat(),
                    },
                )
                break
            if stop.wait(60):
                break

    thread = threading.Thread(
        target=watch, name="triade-prospective-study", daemon=True
    )
    r5._prospective_learning_monitor = {"stop": stop, "thread": thread}
    thread.start()
    return {
        "status": "prospective_study_started",
        "interval_seconds": 60,
        "truth": "Only genuine model runs with activated target neuron and verifier count. Improvement is not guaranteed.",
    }


def attach(context):
    client = getattr(context.get("progress"), "__self__", None)
    if client is None or not getattr(client, "view", None):
        return {"status": "panel_not_rendered"}
    import ipywidgets as widgets
    from IPython.display import display

    output = client.view[-1]
    if not hasattr(output, "value"):
        output = widgets.HTML(
            value="",
            layout=widgets.Layout(max_height="480px", overflow="auto"),
        )
        client.view = (*client.view[:-1], output)
        display(output)

    box = client.view[3]
    known = {getattr(child, "description", "") for child in box.children}
    for label, action in (("Ver circuito de aprendizaje", "learning_status"),):
        if label in known:
            continue
        button = widgets.Button(
            description=label, layout=widgets.Layout(width="300px", height="44px")
        )

        def click(control, selected=action):
            control.disabled = True
            try:
                output.value = "<small>Acción en curso…</small>"
                try:
                    rendered = json.dumps(
                        client.action(selected),
                        ensure_ascii=False,
                        indent=2,
                        default=str,
                    )
                except Exception as exc:  # noqa: BLE001 - panel boundary reports action errors
                    rendered = (
                        "Operación detenida: "
                        + type(exc).__name__
                        + " "
                        + str(exc)[:1600]
                    )
                output.value = (
                    "<pre style='white-space:pre-wrap;overflow-wrap:anywhere'>"
                    + escape(rendered)
                    + "</pre>"
                )
            finally:
                control.disabled = False

        button.on_click(click)
        box.children = (*box.children, button)
    return {"status": "learning_controls_attached"}
