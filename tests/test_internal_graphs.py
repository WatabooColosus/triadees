from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.observability.file_graph import build_file_graph
from triade.observability.neural_graph import build_neural_graph


def test_file_graph_masks_sensitive_paths(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "main.py").write_text("import json\n\ndef run():\n    return 1\n", encoding="utf-8")
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
