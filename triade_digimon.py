#!/usr/bin/env python3
"""Launcher CLI para Tríade Ω Digimon."""

from __future__ import annotations

import argparse
import json

from triade.core.neuron_creator import NeuronCreator
from triade.core.neuron_registry import NeuronRegistry
from triade.core.neuron_trainer import NeuronTrainer
from triade.core.runner import TriadeRunner
from triade.models.model_router import ModelRouter
from triade.models.ollama_client import OllamaClient


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
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def handle_neuron(args: argparse.Namespace) -> None:
    registry = NeuronRegistry(db_path=args.db)

    if args.neuron_command == "create":
        creator = NeuronCreator()
        trainer = NeuronTrainer()
        spec = creator.create(
            name=args.name,
            mission=args.mission,
            domain=args.domain,
            rules=args.rule or [],
        )
        result = trainer.evaluate(spec)
        neuron_id = registry.register(spec)
        training_id = registry.store_training(neuron_id, result)
        print_json(
            {
                "status": "ok",
                "neuron_id": neuron_id,
                "training_id": training_id,
                "spec": spec.to_dict(),
                "training": result.to_dict(),
            }
        )
        return

    if args.neuron_command == "list":
        print_json(
            {
                "status": "ok",
                "count": args.limit,
                "neurons": registry.list_neurons(limit=args.limit),
            }
        )
        return

    if args.neuron_command == "show":
        neuron = registry.get_neuron(args.name)
        if neuron is None:
            print_json({"status": "not_found", "name": args.name})
            return
        training = registry.list_training(neuron_id=int(neuron["id"]), limit=args.limit)
        print_json({"status": "ok", "neuron": neuron, "training": training})
        return

    raise SystemExit("Comando neuron inválido")


def handle_models(args: argparse.Namespace) -> None:
    health = OllamaClient(base_url=args.ollama_url).health()
    router = ModelRouter(available_models=health.get("models", []))

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

    api_parser = subparsers.add_parser("api", help="Levanta API local FastAPI")
    api_parser.add_argument("--host", default="127.0.0.1", help="Host de escucha")
    api_parser.add_argument("--port", type=int, default=8000, help="Puerto de escucha")
    api_parser.add_argument("--reload", action="store_true", help="Recarga automática para desarrollo")

    neuron_parser = subparsers.add_parser("neuron", help="Gestiona neuronas internas")
    neuron_parser.add_argument("--db", default="triade/memory/triade.db", help="Ruta de base SQLite")
    neuron_subparsers = neuron_parser.add_subparsers(dest="neuron_command")

    neuron_create = neuron_subparsers.add_parser("create", help="Crea, evalúa y registra una neurona")
    neuron_create.add_argument("--name", required=True, help="Nombre de la neurona")
    neuron_create.add_argument("--mission", required=True, help="Misión de la neurona")
    neuron_create.add_argument("--domain", default="general", help="Dominio de la neurona")
    neuron_create.add_argument("--rule", action="append", help="Regla operativa; se puede repetir")

    neuron_list = neuron_subparsers.add_parser("list", help="Lista neuronas recientes")
    neuron_list.add_argument("--limit", type=int, default=20, help="Cantidad máxima de neuronas")

    neuron_show = neuron_subparsers.add_parser("show", help="Muestra una neurona y su entrenamiento")
    neuron_show.add_argument("name", help="Nombre exacto de la neurona")
    neuron_show.add_argument("--limit", type=int, default=10, help="Cantidad máxima de entrenamientos")

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

    if args.command == "api":
        import uvicorn

        uvicorn.run("apps.api_app:app", host=args.host, port=args.port, reload=args.reload)
        return

    if args.command == "neuron":
        handle_neuron(args)
        return

    if args.command == "models":
        handle_models(args)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
