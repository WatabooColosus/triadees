#!/usr/bin/env python3
"""Launcher CLI para Tríade Ω Digimon."""

from __future__ import annotations

import argparse
import json

from triade.core.runner import TriadeRunner


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

    args = parser.parse_args()

    if args.command == "run":
        runner = make_runner(args)
        result = runner.run(args.text)
        print(json.dumps(result, ensure_ascii=False, indent=2))
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
                print(json.dumps(runner.recall(query=query), ensure_ascii=False, indent=2))
                continue
            if text == "/doctor":
                print(json.dumps(runner.doctor(), ensure_ascii=False, indent=2))
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
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "doctor":
        runner = make_runner(args)
        result = runner.doctor()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "api":
        import uvicorn

        uvicorn.run("apps.api_app:app", host=args.host, port=args.port, reload=args.reload)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
