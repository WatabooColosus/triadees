from __future__ import annotations

import sqlite3

from scripts.audit_runtime_truth import audit


def test_runtime_truth_lee_los_estados_y_almacen_vivos(tmp_path) -> None:
    db = tmp_path / "triade.db"
    with sqlite3.connect(db) as connection:
        connection.executescript(
            """
            CREATE TABLE runs (source TEXT);
            CREATE TABLE signal_states (id INTEGER);
            CREATE TABLE crystal_states (id INTEGER);
            CREATE TABLE qualia_experiences (id INTEGER, source TEXT);
            CREATE TABLE episodic_memory (id INTEGER);
            CREATE TABLE semantic_documents (id INTEGER, status TEXT);
            CREATE TABLE learning_queue (id INTEGER, status TEXT);
            CREATE TABLE neuron_education_sessions (id INTEGER, result TEXT);
            CREATE TABLE autonomous_research_runs (id INTEGER, status TEXT);
            CREATE TABLE neuron_evidence (id INTEGER, source TEXT);
            CREATE TABLE neuron_activity (id INTEGER, policy TEXT);
            INSERT INTO semantic_documents VALUES (1, 'stable');
            INSERT INTO neuron_education_sessions VALUES (1, 'improved');
            """
        )

    truth = audit(db)

    assert truth["organs"]["stable_semantic_memories"] == 1
    assert truth["learning"]["education_passed"] == 1
