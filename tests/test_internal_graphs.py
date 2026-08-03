from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from triade.observability.code_graph import (
    build_call_graph,
    build_entrypoint_graph,
    build_import_graph,
    build_module_index,
)
from triade.observability.file_graph import build_file_graph
from triade.observability.neural_graph import build_neural_graph
from triade.observability.runtime_graph import (
    build_organ_graph,
    build_table_graph,
    build_vital_chain_graph,
    build_worker_graph,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILDER = REPO_ROOT / "scripts" / "build_internal_graphs.py"
GRAPH_FILES = (
    "file_graph",
    "import_graph",
    "call_graph",
    "entrypoint_graph",
    "worker_graph",
    "table_graph",
    "organ_graph",
    "vital_chain_graph",
)


def _sample_repo(tmp_path: Path) -> Path:
    """Un repositorio mínimo pero realista: paquete, entrypoint, SQL y huérfano."""
    root = tmp_path / "repo"
    (root / "pkg" / "workers").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "workers" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "store.py").write_text(
        "import sqlite3\n\n\n"
        "def save(connection):\n"
        '    connection.execute("INSERT INTO memories (body) VALUES (?)", ("x",))\n\n\n'
        "def load(connection):\n"
        '    return connection.execute("SELECT body FROM memories").fetchall()\n',
        encoding="utf-8",
    )
    (root / "pkg" / "main.py").write_text(
        "from pkg.store import save\n\n\n"
        "def run(connection):\n"
        "    return save(connection)\n\n\n"
        'if __name__ == "__main__":\n'
        "    run(None)\n",
        encoding="utf-8",
    )
    (root / "pkg" / "orphan.py").write_text(
        "def never_called():\n    return 1\n", encoding="utf-8"
    )
    (root / "Procfile").write_text("web: python -m pkg.main\n", encoding="utf-8")
    (root / ".env").write_text("SECRET=value\n", encoding="utf-8")
    return root


def _sample_db(tmp_path: Path) -> Path:
    db = tmp_path / "triade.db"
    connection = sqlite3.connect(db)
    connection.executescript(
        """
        CREATE TABLE memories (id INTEGER PRIMARY KEY, body TEXT);
        CREATE TABLE worker_tasks (id INTEGER PRIMARY KEY, task_type TEXT, created_at TEXT);
        INSERT INTO memories (body) VALUES ('hola');
        INSERT INTO worker_tasks (task_type, created_at)
        VALUES ('pulse_check', '2020-01-01T00:00:00');
        """
    )
    connection.commit()
    connection.close()
    return db


def _build(
    root: Path, db: Path, output: Path, **kwargs: object
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # argumentos construidos aquí, nunca con shell
        [
            sys.executable,
            str(BUILDER),
            "--root",
            str(root),
            "--db",
            str(db),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
        **kwargs,
    )


# --- El script termina, genera archivos y es determinista ---------------------


def test_script_completes_and_writes_every_graph(tmp_path: Path) -> None:
    root = _sample_repo(tmp_path)
    output = tmp_path / "out"
    result = _build(root, _sample_db(tmp_path), output)
    assert result.returncode == 0, result.stderr
    for stem in GRAPH_FILES:
        for suffix in (".json", ".dot", ".mmd", ".md"):
            assert (output / f"{stem}{suffix}").exists(), f"falta {stem}{suffix}"
    index = json.loads((output / "index.json").read_text(encoding="utf-8"))
    assert set(GRAPH_FILES).issubset(index["graphs"])
    assert index["legend"], "la leyenda de colores debe viajar con los grafos"


def test_output_is_deterministic(tmp_path: Path) -> None:
    root = _sample_repo(tmp_path)
    db = _sample_db(tmp_path)
    first, second = tmp_path / "a", tmp_path / "b"
    for output in (first, second):
        assert _build(root, db, output).returncode == 0
    for stem in GRAPH_FILES:
        name = f"{stem}.json"
        assert (first / name).read_bytes() == (second / name).read_bytes(), name


def test_runs_without_ollama_and_without_database(tmp_path: Path) -> None:
    """Los grafos son estructura, no inferencia: no pueden depender de un modelo."""
    root = _sample_repo(tmp_path)
    output = tmp_path / "out"
    result = _build(
        root,
        tmp_path / "no-existe.db",
        output,
        env={"PATH": "/usr/bin:/bin", "OLLAMA_HOST": "http://127.0.0.1:1"},
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(
        (output / "vital_chain_graph.json").read_text(encoding="utf-8")
    )
    # Sin base viva no hay evidencia de ejecución, y el grafo debe decirlo.
    assert all(node["metadata"]["rows"] == "UNKNOWN" for node in payload["nodes"])
    assert not (output / "neural_graph.json").exists()


# --- Nodos reales, sin invenciones -------------------------------------------


def test_nodes_point_at_real_paths_and_invent_nothing(tmp_path: Path) -> None:
    root = _sample_repo(tmp_path)
    nodes, edges = build_import_graph(root)
    internal = [n for n in nodes if n.metadata.get("internal")]
    assert internal, "debe haber módulos internos"
    for node in internal:
        assert (root / str(node.metadata["path"])).is_file()
    known = {n.node_id for n in nodes}
    for edge in edges:
        assert edge.source in known and edge.target in known
    assert any(
        e.relation == "imports"
        and e.source == "module:pkg/main.py"
        and e.target == "module:pkg/store.py"
        for e in edges
    )
    # `sqlite3` es externo: jamás debe aparecer como módulo del repositorio.
    assert "module:sqlite3.py" not in known
    assert any(n.node_id == "external:sqlite3" for n in nodes)


def test_connected_and_orphan_nodes_are_distinguished(tmp_path: Path) -> None:
    root = _sample_repo(tmp_path)
    nodes, _ = build_import_graph(root)
    by_id = {n.node_id: n for n in nodes}
    assert by_id["module:pkg/store.py"].state == "active"
    assert by_id["module:pkg/orphan.py"].state == "disconnected"

    call_nodes, _ = build_call_graph(root)
    calls = {n.node_id: n for n in call_nodes}
    assert calls["symbol:pkg/store.py:save"].state == "active"
    assert calls["symbol:pkg/orphan.py:never_called"].state == "disconnected"


def test_entrypoints_are_detected_and_linked_to_launchers(tmp_path: Path) -> None:
    root = _sample_repo(tmp_path)
    nodes, edges = build_entrypoint_graph(root)
    by_id = {n.node_id: n for n in nodes}
    assert "entrypoint:pkg/main.py" in by_id
    # El Procfile lo arranca de verdad, así que no es un entrypoint muerto.
    assert by_id["entrypoint:pkg/main.py"].state == "active"
    assert any(e.relation == "launches" for e in edges)


def test_workers_and_task_types_are_identified() -> None:
    """Sobre el repositorio real: los tipos salen del `Literal`, no de una lista."""
    nodes, edges = build_worker_graph(REPO_ROOT, build_module_index(REPO_ROOT))
    task_types = {n.label for n in nodes if n.node_id.startswith("task_type:")}
    assert "pulse_check" in task_types
    assert any(n.node_id.startswith("worker_module:") for n in nodes)
    assert any(e.relation == "handled_by" for e in edges)


def test_tables_separate_readers_from_writers(tmp_path: Path) -> None:
    root = _sample_repo(tmp_path)
    nodes, edges = build_table_graph(root, db_path=_sample_db(tmp_path))
    memories = next(n for n in nodes if n.node_id == "table:memories")
    assert memories.metadata["readers"] == 1
    assert memories.metadata["writers"] == 1
    assert memories.metadata["rows"] == 1
    assert {e.relation for e in edges} == {"reads", "writes"}
    # `from pkg.store import save` no es SQL: `pkg` no puede ser una tabla.
    assert not any(n.node_id == "table:pkg" for n in nodes)


def test_organs_and_vital_chain_come_from_real_paths() -> None:
    organ_nodes, _ = build_organ_graph(REPO_ROOT, build_module_index(REPO_ROOT))
    assert organ_nodes
    for node in organ_nodes:
        for path in node.metadata["paths"]:
            assert (REPO_ROOT / str(path)).is_dir()

    stages, chain_edges = build_vital_chain_graph(REPO_ROOT)
    assert next(n.label for n in stages) == "LIFE_PULSE"
    assert len(chain_edges) == len(stages) - 1


# --- Seguridad ----------------------------------------------------------------


def test_graphs_never_expose_secrets(tmp_path: Path) -> None:
    root = _sample_repo(tmp_path)
    nodes, _ = build_file_graph(root)
    protected = next(n for n in nodes if n.label == ".env")
    assert protected.node_id.startswith("crypt:")
    assert "sha256" not in protected.metadata

    output = tmp_path / "out"
    assert _build(root, _sample_db(tmp_path), output).returncode == 0
    for path in sorted(output.iterdir()):
        assert "SECRET=value" not in path.read_text(encoding="utf-8")


def test_live_database_is_never_modified(tmp_path: Path) -> None:
    root = _sample_repo(tmp_path)
    db = _sample_db(tmp_path)
    index = build_module_index(root)
    before = db.read_bytes()
    build_table_graph(root, index, db)
    build_worker_graph(root, index, db)
    build_vital_chain_graph(root, index, db)
    build_neural_graph(db)
    assert db.read_bytes() == before


def test_file_graph_masks_sensitive_paths(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "main.py").write_text(
        "import json\n\ndef run():\n    return 1\n", encoding="utf-8"
    )
    (tmp_path / ".env").write_text("SECRET=value", encoding="utf-8")
    nodes, edges = build_file_graph(tmp_path)
    regular = next(node for node in nodes if node.label == "main.py")
    protected = next(node for node in nodes if node.label == ".env")
    assert regular.metadata["sha256"]
    assert protected.node_id.startswith("crypt:")
    assert "sha256" not in protected.metadata
    assert any(edge.relation == "imports" for edge in edges)


def test_neural_graph_is_read_only(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    connection = sqlite3.connect(db)
    connection.executescript("""
    CREATE TABLE runs (run_id TEXT PRIMARY KEY, status TEXT, created_at TEXT);
    CREATE TABLE autonomous_tasks (id INTEGER PRIMARY KEY, run_id TEXT, status TEXT, task_type TEXT);
    CREATE TABLE neuron_activity (id INTEGER PRIMARY KEY, neuron_id INTEGER, run_id TEXT, created_at TEXT);
    INSERT INTO runs VALUES ('run-1', 'completed', '2026-08-02T00:00:00Z');
    INSERT INTO autonomous_tasks VALUES (1, 'run-1', 'running', 'observe');
    INSERT INTO neuron_activity VALUES (1, 12, 'run-1', '2026-08-02T00:00:01Z');
    """)
    connection.commit()
    before = db.read_bytes()
    connection.close()
    nodes, edges = build_neural_graph(db)
    assert any(node.node_id == "run:run-1" for node in nodes)
    assert any(node.node_id == "neuron:12" for node in nodes)
    assert any(edge.relation == "uses_neuron" for edge in edges)
    assert db.read_bytes() == before


def test_dynamic_table_access_counts_as_a_reader(tmp_path: Path) -> None:
    """`f"SELECT * FROM {table}"` es un lector real, no un hueco en el grafo.

    Es el patrón de `qualia/store.py`: crea sus tablas y las lee por un helper
    genérico. Sin reconocerlo, esas tablas aparecían con cero lectores y de ahí
    salía la conclusión falsa de que Qualia se escribe y nadie la consume.
    """
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "store.py").write_text(
        "import sqlite3\n\n\n"
        "TABLES = ('signals',)\n\n\n"
        "def init(conn):\n"
        '    conn.execute("CREATE TABLE IF NOT EXISTS signals (id INTEGER)")\n\n\n'
        "def read(conn, table):\n"
        '    return conn.execute(f"SELECT * FROM {table} LIMIT 5").fetchall()\n',
        encoding="utf-8",
    )
    db = tmp_path / "triade.db"
    connection = sqlite3.connect(db)
    connection.executescript(
        "CREATE TABLE signals (id INTEGER);INSERT INTO signals VALUES (1);"
    )
    connection.commit()
    connection.close()

    nodes, edges = build_table_graph(root, db_path=db)

    signals = next(n for n in nodes if n.node_id == "table:signals")
    assert signals.metadata["readers"] == 1, "el acceso interpolado es una lectura"
    assert signals.state == "active", "con filas y lector no puede ser legacy"
    assert any(
        e.target == "table:signals" and "interpolada" in e.evidence for e in edges
    ), "la evidencia debe decir que el nombre de tabla se resolvió en ejecución"
