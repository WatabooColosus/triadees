#!/usr/bin/env python
"""Inventario del sistema por AST, reproducible.

Un inventario escrito a mano envejece en cuanto alguien toca el código. Este se
regenera:

    python scripts/build_system_inventory.py

Cuenta como **productor** de una tarea cualquier construcción real
(`PlannedTask(task_type=…)`, `enqueue("x", …)`, `{"task_type": "x"}`), no la
mera aparición del literal. Un análisis que solo mire `enqueue()` reporta veinte
tipos huérfanos que no lo son: en Tríade el productor real de casi todo es
`PlannedTask` en `mission_planner.py`.
"""

from __future__ import annotations

import ast
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SKIP = {
    ".git",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    ".triade_trash",
    "runs",
    "artifacts",
    "audit",
}
ENQUEUE_FUNCS = {"enqueue", "enqueue_task", "_create_task"}
DISPATCH_FILE = "triade/workers/worker_loop.py"


def iter_py():
    for p in ROOT.rglob("*.py"):
        if any(part in SKIP for part in p.parts):
            continue
        yield p


def bucket(rel: str) -> str:
    if rel.startswith("tests/"):
        return "test"
    if rel.startswith("scripts/"):
        return "script"
    return "prod"


def task_types() -> list[str]:
    from triade.workers.contracts import WORKER_TASK_TYPES

    return list(WORKER_TASK_TYPES)


class Inventario(ast.NodeVisitor):
    def __init__(self, rel: str, tipos: set[str]) -> None:
        self.rel = rel
        self.tipos = tipos
        self.producers: list[tuple[str, int, str]] = []
        self.classes: list[str] = []
        self.functions: list[str] = []
        self.env_vars: set[str] = set()
        self.endpoints: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.classes.append(node.name)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.functions.append(node.name)
        for deco in node.decorator_list:
            texto = ast.unparse(deco)
            if any(m in texto for m in (".get(", ".post(", ".put(", ".delete(")):
                self.endpoints.append(texto)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        fname = (
            node.func.attr
            if isinstance(node.func, ast.Attribute)
            else (node.func.id if isinstance(node.func, ast.Name) else None)
        )
        for kw in node.keywords:
            if (
                kw.arg == "task_type"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value in self.tipos
            ):
                self.producers.append(
                    (kw.value.value, node.lineno, f"{fname}(task_type=)")
                )
        if fname in ENQUEUE_FUNCS and node.args:
            a = node.args[0]
            if isinstance(a, ast.Constant) and a.value in self.tipos:
                self.producers.append((a.value, node.lineno, f"{fname}(pos)"))
        # os.getenv("TRIADE_X") / os.environ.get("TRIADE_X")
        if fname in {"getenv", "get"} and node.args:
            a = node.args[0]
            if (
                isinstance(a, ast.Constant)
                and isinstance(a.value, str)
                and a.value.startswith("TRIADE_")
            ):
                self.env_vars.add(a.value)
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        for k, v in zip(node.keys, node.values):
            if (
                isinstance(k, ast.Constant)
                and k.value == "task_type"
                and isinstance(v, ast.Constant)
                and v.value in self.tipos
            ):
                self.producers.append((v.value, node.lineno, "dict"))
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        texto = ast.unparse(node)
        if "environ[" in texto and "TRIADE_" in texto:
            for parte in texto.split("'"):
                if parte.startswith("TRIADE_"):
                    self.env_vars.add(parte)
        self.generic_visit(node)


def recolectar() -> dict[str, Any]:
    tipos = set(task_types())
    productores: dict[str, list[dict[str, Any]]] = defaultdict(list)
    env: set[str] = set()
    modulos = 0
    clases = 0
    funciones = 0
    endpoints: list[str] = []

    for p in iter_py():
        rel = p.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        v = Inventario(rel, tipos)
        v.visit(tree)
        modulos += 1
        clases += len(v.classes)
        funciones += len(v.functions)
        env |= v.env_vars
        endpoints.extend(v.endpoints)
        for tt, line, how in v.producers:
            productores[tt].append(
                {"file": rel, "line": line, "how": how, "bucket": bucket(rel)}
            )

    return {
        "modules": modulos,
        "classes": clases,
        "functions": funciones,
        "endpoints": len(endpoints),
        "env_vars": sorted(env),
        "producers": {k: v for k, v in productores.items()},
        "task_types": sorted(tipos),
    }


def ejecuciones(db: Path) -> dict[str, int]:
    if not db.exists():
        return {}
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error:
        return {}
    try:
        return {
            str(r[0]): int(r[1])
            for r in conn.execute(
                "SELECT task_type, COUNT(*) FROM autonomous_tasks GROUP BY 1"
            )
        }
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def main() -> None:
    datos = recolectar()
    corridas = ejecuciones(ROOT / "triade/memory/triade.db")
    salida = ROOT / "audit"
    salida.mkdir(exist_ok=True)

    lineas = [
        "# TRIADE · Cableado de tareas (generado)",
        "",
        "Regenerar: `python scripts/build_system_inventory.py`",
        "",
        f"- módulos analizados: **{datos['modules']}**",
        f"- clases: **{datos['classes']}** · funciones: **{datos['functions']}**",
        f"- tipos de tarea declarados: **{len(datos['task_types'])}**",
        "",
        "| task_type | productor en producción | scripts | pruebas | ejecuciones |",
        "|---|---|---|---|---|",
    ]
    huerfanas = []
    for tt in datos["task_types"]:
        sitios = datos["producers"].get(tt, [])
        prod = [
            f"`{s['file']}:{s['line']}`"
            for s in sitios
            if s["bucket"] == "prod" and s["file"] != DISPATCH_FILE
        ]
        scr = sum(1 for s in sitios if s["bucket"] == "script")
        tst = sum(1 for s in sitios if s["bucket"] == "test")
        n = corridas.get(tt, 0)
        if not prod:
            huerfanas.append(tt)
        lineas.append(
            f"| `{tt}` | {', '.join(prod) if prod else '**NINGUNO**'} | {scr} | {tst} | {n} |"
        )

    lineas += [
        "",
        "## Tipos sin productor **literal** en producción",
        "",
        "> Cuidado al leer esta lista: el análisis solo ve literales. Un tipo",
        "> encolado con `task_type` en variable no aparece como producido aunque",
        "> lo esté. Casos conocidos y **no** rotos:",
        ">",
        "> - `goal_research`, `goal_safe_command`, `write_governed_text_artifact`:",
        ">   los produce `capability_resolver` → `goal_orchestrator`, que encola",
        ">   `resolution.worker_task_type`. Son a petición del usuario, no",
        ">   autónomos.",
        "> - `bodega_global_review`: lo produce `os/event_engine.py` desde el",
        ">   campo `action` de una regla, no desde un literal de tarea.",
        ">",
        "> `memory_consolidation_review` era el único huérfano real confirmado —",
        "> `_plan_memory_consolidation()` encola `stable_consolidation_review`, no",
        "> éste: dos nombres cercanos, uno muerto—. Se retiró el 2026-08-03 tras",
        "> comprobar que su handler no avanzaba ningún candidato y que la vía de",
        "> evidencia lo sustituye por completo. Sus 208 ejecuciones históricas",
        "> siguen en la cola.",
        "",
        (
            "\n".join(f"- `{t}`" for t in huerfanas)
            if huerfanas
            else "Ninguno: todos los tipos declarados tienen productor."
        ),
        "",
        "## Variables `TRIADE_*` leídas por el código",
        "",
        "\n".join(f"- `{v}`" for v in datos["env_vars"]),
        "",
    ]
    (salida / "TRIADE_TASK_WIRING.md").write_text(
        "\n".join(lineas) + "\n", encoding="utf-8"
    )
    print(json.dumps({"huerfanas": huerfanas, "env": len(datos["env_vars"])}, indent=1))


if __name__ == "__main__":
    sys.exit(main())
