#!/usr/bin/env python3
"""Launcher CLI para Tríade Ω Digimon."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

from triade.core.alignment import CoreAlignment
from triade.core.conversation_analyzer import ConversationAnalyzer, add_analyze_conversations_args
from triade.core.context_engine import build_living_context_for_chat
from triade.core.internal_runtime import (
    build_runtime_heartbeat,
    get_internal_runtime_state,
    get_internal_runtime_supervisor,
    start_internal_runtime_background,
    stop_internal_runtime_background,
)
from triade.core.living_report import build_living_report
from triade.core.model_policy import get_model_cognitive_policy
from triade.core.ollama_blood import check_ollama_blood, ollama_blood_policy
from triade.core.runner import TriadeRunner
from triade.core.self_reflection import SelfReflectionEngine, add_reflect_core_args
from triade.federation.federation import Federation
from triade.federation.relay_client import PublicRelayClient
from triade.learning.pipeline import LearningPipeline
from triade.memory.semantic_continuity import SemanticContinuity
from triade.models.model_router import ModelRouter
from triade.models.ollama_client import OllamaClient, check_ollama_cognitive_health
from triade.qualia.bus import QualiaBus
from triade.qualia.contracts import NeuronExperience
from triade.qualia.store import QualiaStore
from triade.services.event_bus import list_recent_events
from triade.workers.background_service import WorkerBackgroundService


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--runs-dir", default="runs", help="Carpeta donde se guardan runs")
    parser.add_argument("--db", default="triade/memory/triade.db", help="Ruta de base SQLite")
    parser.add_argument("--config", default="triade.yml", help="Ruta de configuración")
    parser.add_argument("--no-ollama", action="store_true", help="Desactiva Ollama y usa fallback por plantilla")
    parser.add_argument("--hypothalamus-model", default=None, help="Modelo Ollama para Hipotálamo")
    parser.add_argument("--central-model", default=None, help="Modelo Ollama para Central")


def make_runner(args: argparse.Namespace) -> TriadeRunner:
    return TriadeRunner(
        runs_dir=args.runs_dir,
        db_path=args.db,
        config_path=args.config,
        use_ollama=not args.no_ollama,
        hypothalamus_model=args.hypothalamus_model,
        central_model=args.central_model,
    )


def print_json(payload: object) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def load_run_learning_candidate(
    run_ref: str,
    runs_dir: str | Path = "runs",
    title: str | None = None,
    domain: str = "triade-runs",
    risk_override: str | None = None,
) -> dict[str, str]:
    run_path = Path(run_ref)
    if not run_path.exists():
        run_path = Path(runs_dir) / run_ref
    if not run_path.exists() or not run_path.is_dir():
        raise FileNotFoundError(f"No existe el run auditable: {run_ref}")

    input_payload = _read_run_json(run_path, "input.json")
    output_payload = _read_run_json(run_path, "output.json")
    report_payload = _read_run_json(run_path, "report.json", required=False)
    safety_payload = _read_run_json(run_path, "safety.json", required=False)

    run_id = str(output_payload.get("run_id") or input_payload.get("run_id") or run_path.name)
    user_input = str(input_payload.get("user_input") or "").strip()
    response = str(output_payload.get("response") or "").strip()
    if not user_input or not response:
        raise ValueError(f"El run {run_id} no contiene input/output suficiente para aprendizaje.")

    actions = output_payload.get("actions_taken") or []
    report_status = report_payload.get("status") if isinstance(report_payload, dict) else None
    risk_level = risk_override or str(safety_payload.get("risk_level") or "low")
    content = "\n".join(
        [
            f"Run auditable: {run_id}",
            f"Entrada: {user_input}",
            f"Respuesta: {response}",
            f"Acciones: {', '.join(actions) if isinstance(actions, list) else actions}",
            f"Reporte: {report_status or 'unknown'}",
            f"Riesgo: {risk_level}",
        ]
    )
    return {
        "content": content,
        "source_type": "conversation",
        "source_ref": f"run:{run_id}",
        "title": title or f"Aprendizaje desde {run_id}",
        "domain": domain,
        "risk_level": risk_level,
    }


def _read_run_json(run_path: Path, name: str, required: bool = True) -> dict[str, object]:
    path = run_path / name
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Falta artefacto requerido: {path}")
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def handle_models(args: argparse.Namespace) -> None:
    health = OllamaClient(base_url=args.ollama_url).health()
    router = ModelRouter(available_models=health.get("models", []))

    if args.models_command == "ollama-health":
        print_json(check_ollama_cognitive_health(base_url=args.ollama_url))
        return

    if args.models_command == "ollama-blood":
        blood = check_ollama_blood(base_url=args.ollama_url)
        print_json(
            {
                "status": blood.get("status"),
                "ollama_blood": blood,
                "policies": {
                    role: ollama_blood_policy(role, blood)
                    for role in [
                        "chat_response",
                        "central_reasoning",
                        "hypothalamus_analysis",
                        "semantic_embedding",
                        "bodega_diagnosis",
                        "neuron_nutrition",
                        "learning_evaluation",
                        "stable_consolidation",
                        "memory_contradiction_check",
                        "worker_cycle",
                    ]
                },
            }
        )
        return

    if args.models_command == "cognitive-policy":
        cognitive_health = check_ollama_cognitive_health(base_url=args.ollama_url)
        reasoning_ready = bool(cognitive_health.get("ok") and cognitive_health.get("reasoning_model_available"))
        embedding_ready = bool(cognitive_health.get("ok") and cognitive_health.get("embedding_model_available"))
        selected = cognitive_health.get("selected_models") or {}
        roles = [
            "chat_response",
            "hypothalamus_analysis",
            "central_reasoning",
            "semantic_embedding",
            "neuron_nutrition",
            "learning_evaluation",
            "memory_diagnosis",
            "stable_consolidation",
            "federation_probe",
            "safety_review",
        ]
        print_json(
            {
                "status": "ok",
                "ollama_health": cognitive_health,
                "policies": {
                    role: get_model_cognitive_policy(
                        role=role,
                        ollama_available=embedding_ready if role == "semantic_embedding" else reasoning_ready,
                        requested_model=selected.get("embeddings" if role == "semantic_embedding" else "reasoning"),
                    )
                    for role in roles
                },
            }
        )
        return

    if args.models_command == "route":
        decision = router.route(
            role=args.role,
            intent=args.intent,
            urgency=args.urgency,
            prefer_speed=args.prefer_speed,
            prefer_depth=args.prefer_depth,
        )
        print_json({"status": "ok", "ollama": health, "decision": decision.to_dict()})
        return

    if args.models_command == "doctor":
        print_json({"status": "ok", "ollama": health, "router": router.route_many(intent=args.intent, urgency=args.urgency)})
        return

    raise SystemExit("Comando models inválido")


def handle_learn(args: argparse.Namespace) -> None:
    pipe = LearningPipeline(db_path=args.db)

    if args.learn_command == "ingest":
        print_json(pipe.ingest(content=args.content, source_type=args.source_type,
                               source_ref=args.source_ref, title=args.title,
                               domain=args.domain, risk_level=args.risk))
        return
    if args.learn_command == "from-run":
        candidate = load_run_learning_candidate(
            args.run,
            runs_dir=args.runs_dir,
            title=args.title,
            domain=args.domain,
            risk_override=args.risk,
        )
        print_json(pipe.ingest(**candidate))
        return
    if args.learn_command == "evaluate":
        print_json(pipe.evaluate(args.candidate_id))
        return
    if args.learn_command == "verify":
        print_json(pipe.verify(args.candidate_id))
        return
    if args.learn_command == "consolidate":
        print_json(pipe.consolidate(args.candidate_id, approved_by=args.approved_by))
        return
    if args.learn_command == "reject":
        print_json(pipe.reject(args.candidate_id, reason=args.reason))
        return
    if args.learn_command == "list":
        print_json({"status": "ok", "candidates": pipe.list_candidates(status=args.status, limit=args.limit)})
        return
    if args.learn_command == "doctor":
        print_json(pipe.doctor())
        return

    raise SystemExit("Comando learn inválido")


def handle_analyze_conversations(args: argparse.Namespace) -> None:
    analyzer = ConversationAnalyzer(db_path=args.db)
    payload = analyzer.analyze(limit=args.limit, since=args.since, source=args.source)
    exported = None
    if args.export:
        exported = analyzer.export_markdown(payload, args.export)
        payload["exported_to"] = str(exported)
    if args.json or not args.export:
        print_json(payload)
        return
    print(f"Reporte exportado: {exported}")


def handle_reflect_core(args: argparse.Namespace) -> None:
    engine = SelfReflectionEngine(db_path=args.db)
    payload = engine.reflect(
        limit=args.limit,
        since=args.since,
        source=args.source,
        register_neuron_candidates=args.register_neuron_candidates,
    )
    exported = None
    if args.export:
        exported = engine.export_markdown(payload, args.export)
        payload["exported_to"] = str(exported)
    if args.json or not args.export:
        print_json(payload)
        return
    print(f"Reflexion exportada: {exported}")


def handle_semantic_continuity(args: argparse.Namespace) -> None:
    continuity = SemanticContinuity(db_path=args.db, auto_ollama_embed=not args.no_ollama_embed)
    if args.semantic_continuity_command == "doctor":
        print_json(continuity.doctor())
        return
    if args.semantic_continuity_command == "backfill-runs":
        print_json(continuity.backfill_recent_runs(limit=args.limit))
        return
    raise SystemExit("Comando semantic-continuity inválido")


def handle_federate(args: argparse.Namespace) -> None:
    federation = Federation(db_path=args.db)

    if args.federate_command == "register":
        capabilities = json.loads(args.capabilities) if args.capabilities else None
        print_json(federation.register_node(node_id=args.node_id, name=args.name, owner=args.owner,
                                            endpoint=args.endpoint, trust_level=args.trust,
                                            permissions=args.permission or [], capabilities=capabilities))
        return
    if args.federate_command == "list":
        print_json({"status": "ok", "nodes": federation.list_nodes(status=args.status)})
        return
    if args.federate_command == "revoke":
        print_json(federation.revoke_node(args.node_id, reason=args.reason or ""))
        return
    if args.federate_command == "capabilities":
        print_json(federation.update_capabilities(args.node_id, json.loads(args.payload)))
        return
    if args.federate_command == "detect-capabilities":
        print_json(federation.update_local_capabilities(args.node_id))
        return
    if args.federate_command == "capable":
        print_json({"status": "ok", "nodes": federation.list_capable_nodes(min_tier=args.min_tier, require_gpu=args.require_gpu)})
        return
    if args.federate_command == "receive":
        print_json(federation.receive_exchange(source_node_id=args.node_id, exchange_type=args.type,
                                               payload=args.payload, risk_level=args.risk, domain=args.domain))
        return
    if args.federate_command == "send":
        print_json(federation.send_exchange(target_node_id=args.node_id, exchange_type=args.type,
                                            payload=args.payload, risk_level=args.risk))
        return
    if args.federate_command == "exchanges":
        print_json({"status": "ok", "exchanges": federation.list_exchanges(node_id=args.node_id, limit=args.limit)})
        return
    if args.federate_command == "doctor":
        print_json(federation.doctor())
        return

    raise SystemExit("Comando federate inválido")




def handle_qualia(args: argparse.Namespace) -> None:
    store = QualiaStore(db_path=args.db)
    bus = QualiaBus(db_path=args.db, store=store)

    if args.qualia_command == "state":
        print_json({"status": "ok", "state": store.latest_state(run_id=args.run_id), "states": store.list_states(run_id=args.run_id, limit=args.limit)})
        return
    if args.qualia_command == "experiences":
        print_json({"status": "ok", "experiences": store.list_experiences(run_id=args.run_id, limit=args.limit)})
        return
    if args.qualia_command == "report":
        print_json(bus.report(run_id=args.run_id))
        return
    if args.qualia_command == "publish-test":
        exp = NeuronExperience(
            run_id=args.run_id or "qualia-cli-test",
            neuron_id="qualia_cli",
            neuron_type="cli_test",
            mission="Validar publicación manual segura de QualiaBus.",
            source="triade_digimon.qualia.publish_test",
            source_type="cli_test",
            observation=args.observation,
            extracted_pattern="El bus convierte una experiencia de prueba en señal, paquete central, almacenamiento y estado.",
            proposed_learning=args.proposed_learning or "",
            confidence=args.confidence,
            risk=args.risk,
            usefulness=args.usefulness,
            emotional_signal={"valence": 0.2, "urgency": 0.2},
            evidence_refs=["cli:qualia:publish-test"],
        )
        print_json(bus.publish_experience(exp, ingest_learning=bool(args.proposed_learning)))
        return

    raise SystemExit("Comando qualia inválido")

def handle_neuron(args: argparse.Namespace) -> None:
    from triade.core.neuron_identity_view import NeuronIdentityView
    from triade.core.stable_neuron_audit import audit_stable_neurons, apply_stable_neuron_audit

    view = NeuronIdentityView(db_path=args.db, runs_dir=args.runs_dir)
    if args.neuron_command == "list":
        print_json(view.list(limit=args.limit))
        return
    if args.neuron_command == "show":
        payload = view.detail(args.name, limit=args.limit)
        if payload is None:
            raise SystemExit(f"No existe neurona: {args.name}")
        print_json(payload)
        return
    if args.neuron_command == "audit-stable":
        if args.apply:
            print_json(apply_stable_neuron_audit(db_path=args.db, runs_dir=args.runs_dir, limit=args.limit, apply=True))
        else:
            print_json(audit_stable_neurons(db_path=args.db, runs_dir=args.runs_dir, limit=args.limit))
        return
    raise SystemExit("Comando neuron inválido")


def handle_neuron_missions(args: argparse.Namespace) -> None:
    from triade.core.neuron_missions import NeuronMissionStore
    from triade.workers.neuron_mission_backfill import backfill_neuron_missions, neuron_missions_doctor

    store = NeuronMissionStore(db_path=args.db)
    if args.neuron_missions_command == "backfill":
        print_json(backfill_neuron_missions(db_path=args.db, runs_dir=args.runs_dir, limit=args.limit))
        return
    if args.neuron_missions_command == "list":
        missions = store.list_missions(limit=args.limit)
        print_json({"status": "ok", "count": len(missions), "missions": [m.to_dict() for m in missions]})
        return
    if args.neuron_missions_command == "doctor":
        print_json(neuron_missions_doctor(db_path=args.db, runs_dir=args.runs_dir, limit=args.limit))
        return
    raise SystemExit("Comando neuron-missions inválido")


def handle_workers(args: argparse.Namespace) -> None:
    service = WorkerBackgroundService(db_path=args.db, runs_dir=args.runs_dir)

    if args.workers_command == "once":
        print_json(service.run_once(dry_run=args.dry_run, task_timeout=args.task_timeout))
        return
    if args.workers_command == "start":
        print_json(service.start(max_iterations=args.max_iterations, sleep_seconds=args.sleep, dry_run=args.dry_run, task_timeout=args.task_timeout))
        return
    if args.workers_command == "daemon":
        print_json(service.start(max_iterations=args.max_iterations, sleep_seconds=args.sleep, dry_run=False, task_timeout=args.task_timeout))
        return
    if args.workers_command == "status":
        print_json(service.status())
        return
    if args.workers_command == "stop":
        print_json(service.stop())
        return
    if args.workers_command == "queue":
        print_json(service.queue_status(status=args.status, limit=args.limit))
        return
    if args.workers_command == "events":
        print_json(service.events(limit=args.limit, run_ref=args.run_ref))
        return
    if args.workers_command == "doctor":
        print_json(service.doctor())
        return

    raise SystemExit("Comando workers inválido")


def handle_runtime(args: argparse.Namespace) -> None:
    supervisor = get_internal_runtime_supervisor(db_path=args.db, runs_dir=args.runs_dir)

    if args.runtime_command == "status":
        print_json(get_internal_runtime_state(db_path=args.db, runs_dir=args.runs_dir))
        return
    if args.runtime_command == "heartbeat":
        print_json(build_runtime_heartbeat(db_path=args.db, runs_dir=args.runs_dir, limit=args.limit))
        return
    if args.runtime_command == "blood":
        blood = check_ollama_blood()
        print_json(
            {
                "status": blood.get("status"),
                "ollama_blood": blood,
                "worker_policy": ollama_blood_policy("worker_cycle", blood),
            }
        )
        return
    if args.runtime_command == "once":
        print_json(supervisor.run_once(mode=args.mode))
        return
    if args.runtime_command == "start":
        print_json(supervisor.run_forever(interval_seconds=args.interval_seconds, max_cycles=args.max_cycles, mode=args.mode))
        return
    if args.runtime_command == "stop":
        print_json(stop_internal_runtime_background(db_path=args.db, runs_dir=args.runs_dir))
        return
    if args.runtime_command == "events":
        print_json({"status": "ok", "count": len(list_recent_events(limit=args.limit, db_path=args.db)), "events": list_recent_events(limit=args.limit, db_path=args.db)})
        return
    if args.runtime_command == "context":
        print_json(build_living_context_for_chat(user_input=args.user_input or "", db_path=args.db, runs_dir=args.runs_dir, limit=args.limit))
        return
    if args.runtime_command == "report":
        print_json(build_living_report(db_path=args.db, runs_dir=args.runs_dir, limit=args.limit))
        return
    raise SystemExit("Comando runtime inválido")

def handle_relay(args: argparse.Namespace) -> None:
    base_url = args.url.rstrip("/")
    headers = {"Authorization": f"Bearer {args.admin_token}"} if args.admin_token else {}

    if args.relay_command == "health":
        response = httpx.get(f"{base_url}/health", timeout=15)
        response.raise_for_status()
        print_json(response.json())
        return
    if args.relay_command == "nodes":
        response = httpx.get(f"{base_url}/api/nodes", headers=headers, timeout=20)
        response.raise_for_status()
        print_json(response.json())
        return
    if args.relay_command == "jobs":
        response = httpx.get(f"{base_url}/api/jobs", headers=headers, timeout=20)
        response.raise_for_status()
        print_json(response.json())
        return
    if args.relay_command == "create-job":
        payload = json.loads(args.payload) if args.payload else {}
        response = httpx.post(
            f"{base_url}/api/jobs",
            headers=headers,
            json={"node_id": args.node_id, "task": args.task, "payload": payload, "seconds": args.seconds},
            timeout=20,
        )
        response.raise_for_status()
        print_json(response.json())
        return
    if args.relay_command == "sync-nodes":
        _require_admin_token(args.admin_token)
        federation = Federation(db_path=args.db)
        client = PublicRelayClient(base_url=base_url, admin_token=args.admin_token)
        print_json(client.sync_nodes_to_federation(federation))
        return
    if args.relay_command == "benchmark":
        _require_admin_token(args.admin_token)
        federation = Federation(db_path=args.db)
        client = PublicRelayClient(base_url=base_url, admin_token=args.admin_token)
        print_json(client.benchmark_online_nodes(federation, seconds=args.seconds, wait_timeout=args.wait_timeout))
        return
    if args.relay_command == "model-feed":
        _require_admin_token(args.admin_token)
        federation = Federation(db_path=args.db)
        nodes = federation.list_capable_nodes(min_tier=args.min_tier)
        print_json(
            {
                "status": "ok",
                "mode": "federated-model-feed",
                "nodes": [
                    {
                        "node_id": node["node_id"],
                        "name": node["name"],
                        "capability_status": node.get("capability_status"),
                        "online": (node.get("capabilities") or {}).get("online"),
                        "benchmark_score": (node.get("capabilities") or {}).get("benchmark_score", 0),
                        "model_support": (node.get("capabilities") or {}).get("model_support", {}),
                    }
                    for node in nodes
                ],
                "policy": {
                    "browser_nodes_host_llm": False,
                    "current_use": "preprocesamiento, hash, benchmark y planificación de capacidad",
                    "next_step_for_real_model_workers": "agente nativo con Ollama/llama.cpp en dispositivo autorizado",
                },
            }
        )
        return
    if args.relay_command == "preprocess-text":
        _require_admin_token(args.admin_token)
        federation = Federation(db_path=args.db)
        client = PublicRelayClient(base_url=base_url, admin_token=args.admin_token)
        print_json(
            client.preprocess_text_online(
                federation,
                text=args.text,
                max_chunk_chars=args.max_chunk_chars,
                wait_timeout=args.wait_timeout,
            )
        )
        return

    raise SystemExit("Comando relay invalido")


def _require_admin_token(admin_token: str | None) -> None:
    if not admin_token:
        raise SystemExit("Este comando requiere --admin-token.")


def handle_always_on(args: argparse.Namespace) -> None:
    from triade.core.always_on import (
        build_always_on_status,
        load_always_on_config,
        start_always_on_if_enabled,
        stop_always_on,
    )

    if args.always_on_command == "status":
        cfg = load_always_on_config()
        status = build_always_on_status()
        print_json({
            "config_source": cfg.get("_config_source", "default"),
            "always_on_enabled": cfg.get("enabled", False),
            "configured_mode": cfg.get("mode", "observe_only"),
            "effective_mode": status.get("effective_mode", "observe_only"),
            "interval_seconds": cfg.get("interval_seconds", 60),
            "max_cycles": cfg.get("max_cycles", 0),
            "background_thread_alive": status.get("background_thread_alive", False),
            "status": status.get("status", "disabled"),
            "last_self_test_status": status.get("last_self_test_status"),
        })
        return

    if args.always_on_command == "enable":
        import yaml
        path = Path(args.config or "triade.yml")
        try:
            with open(path) as f:
                yml = yaml.safe_load(f) or {}
        except Exception:
            yml = {}
        if "runtime" not in yml:
            yml["runtime"] = {}
        yml["runtime"]["always_on"] = True
        if args.mode:
            yml["runtime"]["mode"] = args.mode
        if args.interval:
            yml["runtime"]["interval_seconds"] = args.interval
        if args.safe_only is not None:
            yml["runtime"]["safe_only"] = args.safe_only
        if args.require_ollama is not None:
            yml["runtime"]["require_ollama"] = args.require_ollama
        if args.self_test_every is not None:
            yml["runtime"]["self_test_every_cycles"] = args.self_test_every
        with open(path, "w") as f:
            yaml.dump(yml, f, default_flow_style=False)
        print_json({"status": "ok", "message": "ALWAYS-ON habilitado en triade.yml.", "config": yml["runtime"]})
        return

    if args.always_on_command == "disable":
        import yaml
        path = Path(args.config or "triade.yml")
        try:
            with open(path) as f:
                yml = yaml.safe_load(f) or {}
        except Exception:
            yml = {}
        if "runtime" in yml:
            yml["runtime"]["always_on"] = False
        with open(path, "w") as f:
            yaml.dump(yml, f, default_flow_style=False)
        result = stop_always_on()
        print_json({"status": "ok", "message": "ALWAYS-ON deshabilitado en triade.yml.", "stop_result": result})
        return

    if args.always_on_command == "start":
        result = start_always_on_if_enabled()
        print_json(result)
        return

    if args.always_on_command == "stop":
        result = stop_always_on()
        print_json(result)
        return

    print_json(build_always_on_status())


def handle_self_test(args: argparse.Namespace) -> None:
    from triade.core.self_test_cycle import run_self_test_cycle
    result = run_self_test_cycle(mode=args.mode)
    print_json(result)


def main() -> None:
    parser = argparse.ArgumentParser(description="Tríade Ω · MVP local auditable con memoria SQLite")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Ejecuta un mensaje como run auditable")
    run_parser.add_argument("text", help="Texto de entrada para Tríade")
    add_common_args(run_parser)

    chat_parser = subparsers.add_parser("chat", help="Abre consola interactiva")
    add_common_args(chat_parser)

    recall_parser = subparsers.add_parser("recall", help="Consulta memoria episódica reciente")
    recall_parser.add_argument("query", nargs="?", default="", help="Texto a buscar en memoria")
    recall_parser.add_argument("--limit", type=int, default=10, help="Cantidad máxima de episodios")
    recall_parser.add_argument("--db", default="triade/memory/triade.db", help="Ruta de base SQLite")

    doctor_parser = subparsers.add_parser("doctor", help="Diagnostica instalación local de Tríade")
    add_common_args(doctor_parser)

    analyze_parser = subparsers.add_parser("analyze-conversations", help="Analiza conversaciones locales en modo solo lectura")
    add_analyze_conversations_args(analyze_parser)

    reflect_parser = subparsers.add_parser("reflect-core", help="Reflexiona sobre el nucleo y propone mejoras/neuronas")
    add_reflect_core_args(reflect_parser)

    semantic_continuity_parser = subparsers.add_parser("semantic-continuity", help="Gestiona continuidad semántica real desde runs")
    semantic_continuity_parser.add_argument("--db", default="triade/memory/triade.db", help="Ruta de base SQLite")
    semantic_continuity_parser.add_argument("--no-ollama-embed", action="store_true", help="Usa solo embedding local hash")
    semantic_continuity_sub = semantic_continuity_parser.add_subparsers(dest="semantic_continuity_command")
    semantic_continuity_sub.add_parser("doctor", help="Diagnostica documentos/embeddings de continuidad")
    semantic_backfill = semantic_continuity_sub.add_parser("backfill-runs", help="Crea documentos semánticos candidatos desde runs recientes")
    semantic_backfill.add_argument("--limit", type=int, default=50, help="Cantidad de runs recientes")

    align_parser = subparsers.add_parser("align", help="Audita alineación teórica de órganos internos")
    align_parser.add_argument("--artifacts", nargs="*", default=None, help="Lista opcional de artefactos de un run")

    api_parser = subparsers.add_parser("api", help="Levanta API local FastAPI")
    api_parser.add_argument("--host", default="127.0.0.1", help="Host de escucha")
    api_parser.add_argument("--port", type=int, default=8000, help="Puerto de escucha")
    api_parser.add_argument("--reload", action="store_true", help="Recarga automática para desarrollo")

    models_parser = subparsers.add_parser("models", help="Recomienda modelos por rol/tarea")
    models_parser.add_argument("--ollama-url", default="http://127.0.0.1:11434", help="URL local de Ollama")
    models_subparsers = models_parser.add_subparsers(dest="models_command")

    models_route = models_subparsers.add_parser("route", help="Recomienda un modelo para un rol")
    models_route.add_argument("--role", default="central", help="Rol: hypothalamus, central, creator, trainer, coder, embedding, fast, deep")
    models_route.add_argument("--intent", default="conversation", help="Intención detectada")
    models_route.add_argument("--urgency", default="medium", help="Urgencia: low, medium, high")
    models_route.add_argument("--prefer-speed", action="store_true", help="Prioriza velocidad")
    models_route.add_argument("--prefer-depth", action="store_true", help="Prioriza profundidad")

    models_doctor = models_subparsers.add_parser("doctor", help="Muestra recomendaciones para todos los roles")
    models_doctor.add_argument("--intent", default="conversation", help="Intención detectada")
    models_doctor.add_argument("--urgency", default="medium", help="Urgencia: low, medium, high")
    models_subparsers.add_parser("ollama-health", help="Diagnostica Ollama como motor cognitivo local")
    models_subparsers.add_parser("ollama-blood", help="Diagnostica Ollama Blood como sangre cognitiva local")
    models_subparsers.add_parser("cognitive-policy", help="Muestra la política cognitiva por rol")

    learn_parser = subparsers.add_parser("learn", help="Pipeline de aprendizaje controlado (learning_queue)")
    learn_parser.add_argument("--db", default="triade/memory/triade.db", help="Ruta de base SQLite")
    learn_subparsers = learn_parser.add_subparsers(dest="learn_command")

    learn_ingest = learn_subparsers.add_parser("ingest", help="Ingesta un candidato de aprendizaje")
    learn_ingest.add_argument("content", help="Contenido del candidato")
    learn_ingest.add_argument("--source-type", dest="source_type", default="conversation",
                              help="conversation|document|web|repo|model|node|tool")
    learn_ingest.add_argument("--source-ref", dest="source_ref", default=None, help="Referencia de fuente")
    learn_ingest.add_argument("--title", default=None, help="Título del candidato")
    learn_ingest.add_argument("--domain", default="general", help="Dominio del candidato")
    learn_ingest.add_argument("--risk", default="low", help="low|medium|high|critical")

    learn_from_run = learn_subparsers.add_parser("from-run", help="Crea candidato desde un run auditable")
    learn_from_run.add_argument("run", help="ID del run o ruta a carpeta de run")
    learn_from_run.add_argument("--runs-dir", default="runs", help="Carpeta base de runs")
    learn_from_run.add_argument("--title", default=None, help="Título del candidato")
    learn_from_run.add_argument("--domain", default="triade-runs", help="Dominio del candidato")
    learn_from_run.add_argument("--risk", default=None, help="Override de riesgo: low|medium|high|critical")

    learn_eval = learn_subparsers.add_parser("evaluate", help="Evalúa utilidad, confianza y riesgo")
    learn_eval.add_argument("candidate_id", help="ID del candidato")

    learn_verify = learn_subparsers.add_parser("verify", help="Verifica un candidato evaluado")
    learn_verify.add_argument("candidate_id", help="ID del candidato")

    learn_consol = learn_subparsers.add_parser("consolidate", help="Consolida a memoria estable (autónomo)")
    learn_consol.add_argument("candidate_id", help="ID del candidato")
    learn_consol.add_argument("--approved-by", dest="approved_by", required=True, help="Aprobador humano")

    learn_reject = learn_subparsers.add_parser("reject", help="Rechaza un candidato")
    learn_reject.add_argument("candidate_id", help="ID del candidato")
    learn_reject.add_argument("--reason", required=True, help="Razón del rechazo")

    learn_list = learn_subparsers.add_parser("list", help="Lista candidatos de aprendizaje")
    learn_list.add_argument("--status", default=None, help="Filtrar por estado")
    learn_list.add_argument("--limit", type=int, default=50, help="Cantidad máxima")

    learn_subparsers.add_parser("doctor", help="Diagnóstico del pipeline de aprendizaje")

    fed_parser = subparsers.add_parser("federate", help="Federación entre nodos autorizados")
    fed_parser.add_argument("--db", default="triade/memory/triade.db", help="Ruta de base SQLite")
    fed_subparsers = fed_parser.add_subparsers(dest="federate_command")

    fed_register = fed_subparsers.add_parser("register", help="Registra o actualiza un nodo federado")
    fed_register.add_argument("node_id", help="Identificador del nodo")
    fed_register.add_argument("--name", required=True, help="Nombre del nodo")
    fed_register.add_argument("--owner", default=None, help="Propietario del nodo")
    fed_register.add_argument("--endpoint", default=None, help="Endpoint del nodo")
    fed_register.add_argument("--trust", default="low", help="low|medium|high")
    fed_register.add_argument("--permission", action="append", help="Permiso autorizado; se puede repetir")
    fed_register.add_argument("--capabilities", default=None, help="Perfil hardware JSON opcional del nodo")

    fed_list = fed_subparsers.add_parser("list", help="Lista nodos federados")
    fed_list.add_argument("--status", default=None, help="Filtrar por estado")

    fed_revoke = fed_subparsers.add_parser("revoke", help="Revoca un nodo")
    fed_revoke.add_argument("node_id", help="Identificador del nodo")
    fed_revoke.add_argument("--reason", default="", help="Razón de la revocación")

    fed_capabilities = fed_subparsers.add_parser("capabilities", help="Actualiza capacidades hardware de un nodo")
    fed_capabilities.add_argument("node_id", help="Identificador del nodo")
    fed_capabilities.add_argument("--payload", required=True, help="Perfil hardware/capacidades en JSON")

    fed_local_capabilities = fed_subparsers.add_parser("detect-capabilities", help="Detecta y guarda capacidades locales para un nodo")
    fed_local_capabilities.add_argument("node_id", help="Identificador del nodo")

    fed_capable = fed_subparsers.add_parser("capable", help="Lista nodos activos aptos para computo")
    fed_capable.add_argument("--min-tier", default="low", help="low|medium|high")
    fed_capable.add_argument("--require-gpu", action="store_true", help="Exige GPU/VRAM detectada")

    fed_receive = fed_subparsers.add_parser("receive", help="Recibe un intercambio de un nodo")
    fed_receive.add_argument("node_id", help="Nodo origen")
    fed_receive.add_argument("--type", required=True, help="knowledge|pattern|neuron_spec|verification|learning_candidate")
    fed_receive.add_argument("--payload", required=True, help="Contenido del intercambio")
    fed_receive.add_argument("--risk", default="low", help="low|medium|high|critical")
    fed_receive.add_argument("--domain", default="federated", help="Dominio del candidato")

    fed_send = fed_subparsers.add_parser("send", help="Envía un intercambio a un nodo")
    fed_send.add_argument("node_id", help="Nodo destino")
    fed_send.add_argument("--type", required=True, help="knowledge|pattern|neuron_spec|verification|learning_candidate")
    fed_send.add_argument("--payload", required=True, help="Contenido del intercambio")
    fed_send.add_argument("--risk", default="low", help="low|medium|high|critical")

    fed_exchanges = fed_subparsers.add_parser("exchanges", help="Lista el log de intercambios")
    fed_exchanges.add_argument("--node-id", dest="node_id", default=None, help="Filtrar por nodo")
    fed_exchanges.add_argument("--limit", type=int, default=50, help="Cantidad máxima")

    fed_subparsers.add_parser("doctor", help="Diagnóstico de la federación")


    qualia_parser = subparsers.add_parser("qualia", help="QualiaBus: experiencias neuronales y estado circulatorio")
    qualia_parser.add_argument("--db", default="triade/memory/triade.db", help="Ruta de base SQLite")
    qualia_sub = qualia_parser.add_subparsers(dest="qualia_command")

    qualia_state = qualia_sub.add_parser("state", help="Muestra estado QualiaBus reciente")
    qualia_state.add_argument("--run-id", default=None, help="Filtrar por run_id")
    qualia_state.add_argument("--limit", type=int, default=20, help="Cantidad máxima")

    qualia_exp = qualia_sub.add_parser("experiences", help="Lista experiencias neuronales Qualia")
    qualia_exp.add_argument("--run-id", default=None, help="Filtrar por run_id")
    qualia_exp.add_argument("--limit", type=int, default=50, help="Cantidad máxima")

    qualia_report = qualia_sub.add_parser("report", help="Reporte completo QualiaBus")
    qualia_report.add_argument("--run-id", default=None, help="Filtrar por run_id")

    qualia_pub = qualia_sub.add_parser("publish-test", help="Publica una experiencia Qualia de prueba")
    qualia_pub.add_argument("--run-id", default="qualia-cli-test", help="run_id de prueba")
    qualia_pub.add_argument("--observation", default="Experiencia de prueba QualiaBus desde CLI.", help="Observación")
    qualia_pub.add_argument("--proposed-learning", default="", help="Contenido opcional para candidato de aprendizaje")
    qualia_pub.add_argument("--risk", default="low", help="low|medium|high|critical")
    qualia_pub.add_argument("--confidence", type=float, default=0.7, help="Confianza")
    qualia_pub.add_argument("--usefulness", type=float, default=0.7, help="Utilidad")

    neuron_common = argparse.ArgumentParser(add_help=False)
    neuron_common.add_argument("--db", default="triade/memory/triade.db", help="Ruta de base SQLite")
    neuron_common.add_argument("--runs-dir", default="runs", help="Directorio de runs auditables")
    neuron_parser = subparsers.add_parser("neuron", help="Neuronas internas con identidad y evidencia", parents=[neuron_common])
    neuron_sub = neuron_parser.add_subparsers(dest="neuron_command")
    neuron_list = neuron_sub.add_parser("list", help="Lista neuronas con identidad diferenciada", parents=[neuron_common])
    neuron_list.add_argument("--limit", type=int, default=50, help="Cantidad máxima")
    neuron_show = neuron_sub.add_parser("show", help="Muestra detalle de una neurona", parents=[neuron_common])
    neuron_show.add_argument("name", help="Nombre de la neurona")
    neuron_show.add_argument("--limit", type=int, default=20, help="Cantidad máxima de evidencias")
    neuron_audit = neuron_sub.add_parser("audit-stable", help="Audita neuronas stable débiles", parents=[neuron_common])
    neuron_audit.add_argument("--limit", type=int, default=300, help="Cantidad máxima a inspeccionar")
    neuron_audit.add_argument("--apply", action="store_true", help="Aplica la auditoría de forma explícita")

    neuron_missions_common = argparse.ArgumentParser(add_help=False)
    neuron_missions_common.add_argument("--db", default="triade/memory/triade.db", help="Ruta de base SQLite")
    neuron_missions_common.add_argument("--runs-dir", default="runs", help="Directorio de runs auditables")
    neuron_missions_common.add_argument("--limit", type=int, default=500, help="Cantidad máxima a inspeccionar")
    neuron_missions_parser = subparsers.add_parser("neuron-missions", help="Backfill y doctor de misiones neuronales", parents=[neuron_missions_common])
    neuron_missions_sub = neuron_missions_parser.add_subparsers(dest="neuron_missions_command")
    neuron_missions_sub.add_parser("backfill", help="Crea misiones faltantes desde neuronas activas", parents=[neuron_missions_common])
    neuron_missions_sub.add_parser("list", help="Lista misiones neuronales", parents=[neuron_missions_common])
    neuron_missions_sub.add_parser("doctor", help="Diagnóstico operativo de misiones neuronales", parents=[neuron_missions_common])

    workers_parser = subparsers.add_parser("workers", help="Triade Living Workers en segundo plano controlado")
    workers_parser.add_argument("--db", default="triade/memory/triade.db", help="Ruta de base SQLite")
    workers_parser.add_argument("--runs-dir", default="runs/background", help="Directorio de artefactos background")
    workers_sub = workers_parser.add_subparsers(dest="workers_command")

    workers_once = workers_sub.add_parser("once", help="Ejecuta un ciclo worker único")
    workers_once.add_argument("--dry-run", action="store_true", help="Planifica sin ejecutar mutaciones")
    workers_once.add_argument("--task-timeout", type=float, default=30.0, help="Timeout por tarea")

    workers_start = workers_sub.add_parser("start", help="Ejecuta worker daemon acotado")
    workers_start.add_argument("--max-iterations", type=int, default=5, help="Máximo de iteraciones")
    workers_start.add_argument("--sleep", type=float, default=2.0, help="Segundos entre iteraciones")
    workers_start.add_argument("--dry-run", action="store_true", help="Planifica sin ejecutar mutaciones")
    workers_start.add_argument("--task-timeout", type=float, default=30.0, help="Timeout por tarea")

    workers_sub.add_parser("status", help="Estado de workers")
    workers_sub.add_parser("stop", help="Solicita stop mediante .triade_stop")

    workers_queue = workers_sub.add_parser("queue", help="Lista cola worker")
    workers_queue.add_argument("--status", default=None, help="Filtrar por status")
    workers_queue.add_argument("--limit", type=int, default=50, help="Cantidad máxima")

    workers_events = workers_sub.add_parser("events", help="Lista eventos worker")
    workers_events.add_argument("--run-ref", default=None, help="Filtrar por run_ref")
    workers_events.add_argument("--limit", type=int, default=50, help="Cantidad máxima")

    workers_sub.add_parser("doctor", help="Diagnóstico de Living Workers")

    workers_daemon = workers_sub.add_parser("daemon", help="Ejecuta workers en modo daemon controlado (sin shell, sin red externa)")
    workers_daemon.add_argument("--max-iterations", type=int, default=10, help="Máximo de iteraciones (default: 10)")
    workers_daemon.add_argument("--sleep", type=float, default=5.0, help="Segundos entre iteraciones (default: 5.0)")
    workers_daemon.add_argument("--task-timeout", type=float, default=30.0, help="Timeout por tarea")

    runtime_common = argparse.ArgumentParser(add_help=False)
    runtime_common.add_argument("--db", default="triade/memory/triade.db", help="Ruta de base SQLite")
    runtime_common.add_argument("--runs-dir", default="runs/background", help="Directorio de artefactos runtime")
    runtime_common.add_argument("--mode", default=None, help="observe_only|learn_candidates|execute_missions|full_local")
    runtime_common.add_argument("--interval-seconds", type=int, default=30, help="Intervalo entre ciclos en modo start")
    runtime_common.add_argument("--max-cycles", type=int, default=0, help="Máximo de ciclos en modo start")
    runtime_common.add_argument("--limit", type=int, default=20, help="Cantidad máxima para events/context/report")
    runtime_common.add_argument("--user-input", default="", help="Entrada para construir contexto vivo")
    runtime_parser = subparsers.add_parser("runtime", help="Runtime interno 24/7 y estado vivo", parents=[runtime_common])
    runtime_sub = runtime_parser.add_subparsers(dest="runtime_command")
    runtime_sub.add_parser("status", help="Estado actual del runtime", parents=[runtime_common])
    runtime_sub.add_parser("once", help="Ejecuta un ciclo interno único", parents=[runtime_common])
    runtime_sub.add_parser("start", help="Inicia runtime continuo controlado", parents=[runtime_common])
    runtime_sub.add_parser("stop", help="Detiene runtime continuo", parents=[runtime_common])
    runtime_sub.add_parser("events", help="Muestra eventos internos recientes", parents=[runtime_common])
    runtime_sub.add_parser("heartbeat", help="Muestra heartbeat cognitivo del runtime", parents=[runtime_common])
    runtime_sub.add_parser("blood", help="Muestra estado de sangre cognitiva Ollama", parents=[runtime_common])
    runtime_sub.add_parser("context", help="Muestra contexto vivo resumido", parents=[runtime_common])
    runtime_sub.add_parser("report", help="Muestra reporte vivo resumido", parents=[runtime_common])

    # ── Always-On ────────────────────────────────────────────────────────
    ao_parser = subparsers.add_parser("always-on", help="Controla ALWAYS-ON runtime persistente")
    ao_sub = ao_parser.add_subparsers(dest="always_on_command")
    ao_sub.add_parser("status", help="Estado actual de ALWAYS-ON")
    ao_enable = ao_sub.add_parser("enable", help="Habilita ALWAYS-ON en triade.yml")
    ao_enable.add_argument("--mode", default=None, help="observe_only|execute_missions|balanced_background|full_local_guarded")
    ao_enable.add_argument("--interval", type=int, default=None, help="Intervalo en segundos")
    ao_enable.add_argument("--safe-only", dest="safe_only", type=bool, default=None, help="Solo acciones seguras")
    ao_enable.add_argument("--require-ollama", dest="require_ollama", type=bool, default=None, help="Requerir Ollama")
    ao_enable.add_argument("--self-test-every", dest="self_test_every", type=int, default=None, help="Self-test cada N ciclos")
    ao_enable.add_argument("--config", default="triade.yml", help="Ruta de configuración")
    ao_sub.add_parser("disable", help="Deshabilita ALWAYS-ON en triade.yml").add_argument("--config", default="triade.yml")
    ao_sub.add_parser("start", help="Inicia ALWAYS-ON ahora")
    ao_sub.add_parser("stop", help="Detiene ALWAYS-ON ahora")

    # ── Self-test ────────────────────────────────────────────────────────
    st_parser = subparsers.add_parser("self-test", help="Ejecuta ciclo de autodiagnóstico seguro")
    st_parser.add_argument("--mode", default="safe", help="safe|full")

    relay_parser = subparsers.add_parser("relay", help="Controla un relay publico Triade")
    relay_parser.add_argument("--url", required=True, help="URL publica del relay")
    relay_parser.add_argument("--admin-token", default=None, help="Token admin del relay")
    relay_parser.add_argument("--db", default="triade/memory/triade.db", help="Ruta de base SQLite")
    relay_subparsers = relay_parser.add_subparsers(dest="relay_command")

    relay_subparsers.add_parser("health", help="Consulta salud del relay")
    relay_subparsers.add_parser("nodes", help="Lista nodos conectados")
    relay_subparsers.add_parser("jobs", help="Lista jobs recientes")

    relay_job = relay_subparsers.add_parser("create-job", help="Crea job para un nodo web")
    relay_job.add_argument("node_id", help="Nodo destino")
    relay_job.add_argument("--task", default="browser_benchmark", help="echo|sha256|browser_benchmark")
    relay_job.add_argument("--payload", default="{}", help="JSON de entrada")
    relay_job.add_argument("--seconds", type=float, default=2.0, help="Duracion para benchmark")

    relay_subparsers.add_parser("sync-nodes", help="Sincroniza nodos online del relay a la federacion local")

    relay_benchmark = relay_subparsers.add_parser("benchmark", help="Mide nodos browser y guarda su score en la federacion local")
    relay_benchmark.add_argument("--seconds", type=float, default=2.0, help="Duracion de cada benchmark")
    relay_benchmark.add_argument("--wait-timeout", type=float, default=45.0, help="Tiempo maximo de espera por job")

    relay_feed = relay_subparsers.add_parser("model-feed", help="Resume nodos que alimentan la planificacion local de modelos")
    relay_feed.add_argument("--min-tier", default="low", help="low|medium|high")

    relay_preprocess = relay_subparsers.add_parser("preprocess-text", help="Preprocesa contexto en nodos browser para alimentar modelos locales")
    relay_preprocess.add_argument("text", help="Texto/contexto a preparar")
    relay_preprocess.add_argument("--max-chunk-chars", type=int, default=1200, help="Tamano maximo de chunk")
    relay_preprocess.add_argument("--wait-timeout", type=float, default=45.0, help="Tiempo maximo de espera por job")

    args = parser.parse_args()

    if args.command == "run":
        runner = make_runner(args)
        result = runner.run(args.text)
        print_json(result)
        return

    if args.command == "chat":
        runner = make_runner(args)
        print("Tríade Ω · chat local auditable")
        print("Comandos: /exit, /recall <texto>, /doctor")
        while True:
            try:
                text = input("Tú > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nCerrando Tríade Ω.")
                break

            if not text:
                continue
            if text in {"/exit", "exit", "salir"}:
                print("Cerrando Tríade Ω.")
                break
            if text.startswith("/recall"):
                query = text.replace("/recall", "", 1).strip()
                print_json(runner.recall(query=query))
                continue
            if text == "/doctor":
                print_json(runner.doctor())
                continue

            result = runner.run(text)
            print(f"Tríade Ω > {result['response']}")
            print(f"run: {result['run_id']} | path: {result['run_path']}")
            hyp = result["models"]["hypothalamus"]
            cen = result["models"]["central"]
            print(f"hipotálamo: {hyp['provider']}:{hyp['name']} ok={hyp['ok']} quality={hyp.get('quality_score')}")
            print(f"central: {cen['provider']}:{cen['name']} ok={cen['ok']} quality={cen.get('quality_score')}")
        return

    if args.command == "recall":
        runner = TriadeRunner(db_path=args.db)
        result = runner.recall(query=args.query, limit=args.limit)
        print_json(result)
        return

    if args.command == "doctor":
        runner = make_runner(args)
        result = runner.doctor()
        print_json(result)
        return

    if args.command == "analyze-conversations":
        handle_analyze_conversations(args)
        return

    if args.command == "reflect-core":
        handle_reflect_core(args)
        return

    if args.command == "semantic-continuity":
        handle_semantic_continuity(args)
        return

    if args.command == "align":
        alignment = CoreAlignment()
        payload = alignment.evaluate_static_core()
        if args.artifacts is not None:
            payload["artifacts"] = alignment.evaluate_run_artifacts(args.artifacts)
        print_json(payload)
        return

    if args.command == "api":
        import uvicorn

        uvicorn.run("apps.api_app:app", host=args.host, port=args.port, reload=args.reload)
        return

    if args.command == "models":
        handle_models(args)
        return

    if args.command == "learn":
        handle_learn(args)
        return

    if args.command == "federate":
        handle_federate(args)
        return

    if args.command == "neuron":
        handle_neuron(args)
        return

    if args.command == "neuron-missions":
        handle_neuron_missions(args)
        return

    if args.command == "workers":
        handle_workers(args)
        return

    if args.command == "runtime":
        handle_runtime(args)
        return

    if args.command == "qualia":
        handle_qualia(args)
        return

    if args.command == "relay":
        handle_relay(args)
        return

    if args.command == "always-on":
        handle_always_on(args)
        return

    if args.command == "self-test":
        handle_self_test(args)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
