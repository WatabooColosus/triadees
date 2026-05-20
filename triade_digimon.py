#!/usr/bin/env python3
"""Launcher CLI para Tríade Ω Digimon."""

from __future__ import annotations

import argparse
import json

from triade.core.runner import TriadeRunner


def main() -> None:
    parser = argparse.ArgumentParser(description="Tríade Ω · MVP local auditable con memoria SQLite")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Ejecuta un mensaje como run auditable")
    run_parser.add_argument("text", help="Texto de entrada para Tríade")
    run_parser.add_argument("--runs-dir", default="runs", help="Carpeta donde se guardan runs")
    run_parser.add_argument("--db", default="triade/memory/triade.db", help="Ruta de base SQLite")

    chat_parser = subparsers.add_parser("chat", help="Abre consola interactiva")
    chat_parser.add_argument("--runs-dir", default="runs", help="Carpeta donde se guardan runs")
    chat_parser.add_argument("--db", default="triade/memory/triade.db", help="Ruta de base SQLite")

    recall_parser = subparsers.add_parser("recall", help="Consulta memoria episódica reciente")
    recall_parser.add_argument("query", nargs="?", default="", help="Texto a buscar en memoria")
    recall_parser.add_argument("--limit", type=int, default=10, help="Cantidad máxima de episodios")
    recall_parser.add_argument("--db", default="triade/memory/triade.db", help="Ruta de base SQLite")

    doctor_parser = subparsers.add_parser("doctor", help="Diagnostica instalación local de Tríade")
    doctor_parser.add_argument("--runs-dir", default="runs", help="Carpeta donde se guardan runs")
    doctor_parser.add_argument("--db", default="triade/memory/triade.db", help="Ruta de base SQLite")

    args = parser.parse_args()

    if args.command == "run":
        runner = TriadeRunner(runs_dir=args.runs_dir, db_path=args.db)
        result = runner.run(args.text)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "chat":
        runner = TriadeRunner(runs_dir=args.runs_dir, db_path=args.db)
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
        return

    if args.command == "recall":
        runner = TriadeRunner(db_path=args.db)
        result = runner.recall(query=args.query, limit=args.limit)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "doctor":
        runner = TriadeRunner(runs_dir=args.runs_dir, db_path=args.db)
        result = runner.doctor()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
