import json
import sqlite3
from pathlib import Path

from triade.federation.observability import FederatedObservability


def seed(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE federated_nodes_v2 (
                node_id TEXT PRIMARY KEY,
                key_fingerprint TEXT,
                state TEXT,
                trust_score REAL,
                payload_json TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE federated_node_events (
                id INTEGER PRIMARY KEY,
                node_id TEXT,
                action TEXT,
                actor TEXT,
                reason TEXT,
                payload_json TEXT,
                created_at TEXT
            );
            CREATE TABLE federated_jobs (
                job_id TEXT PRIMARY KEY,
                remote_node_id TEXT,
                capability TEXT,
                status TEXT,
                request_sha256 TEXT,
                result_sha256 TEXT,
                payload_json TEXT,
                created_at REAL,
                updated_at REAL
            );
            CREATE TABLE federated_job_events (
                id INTEGER PRIMARY KEY,
                job_id TEXT,
                action TEXT,
                payload_json TEXT,
                created_at REAL
            );
            CREATE TABLE federated_evidence_assessments (
                assessment_id TEXT PRIMARY KEY,
                job_id TEXT,
                node_id TEXT,
                capability TEXT,
                evidence_sha256 TEXT,
                regression_report_id TEXT,
                decision TEXT,
                trust_before REAL,
                trust_after REAL,
                payload_json TEXT,
                created_at TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO federated_nodes_v2 VALUES ('node-1','fp','trusted',0.9,'{}','now','now')"
        )
        conn.execute(
            "INSERT INTO federated_node_events VALUES (1,'node-1','registered','system','ok','{}','now')"
        )
        conn.execute(
            "INSERT INTO federated_jobs VALUES ('job-1','node-1','research','completed','a','b','{}',1,2)"
        )
        conn.execute(
            "INSERT INTO federated_jobs VALUES ('job-2','node-1','research','failed','a',NULL,'{}',1,3)"
        )
        conn.execute(
            "INSERT INTO federated_job_events VALUES (1,'job-1','completed','{}',2)"
        )
        conn.execute(
            "INSERT INTO federated_evidence_assessments VALUES ('a1','job-1','node-1','research','e','r','pass',0.8,0.83,'{}','now')"
        )


def test_snapshot_groups_operational_state(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    seed(db_path)

    snapshot = FederatedObservability(db_path).snapshot()

    assert snapshot["nodes"] == {"trusted": 1}
    assert snapshot["jobs"] == {"completed": 1, "failed": 1}
    assert snapshot["assessments"] == {"pass": 1}
    assert snapshot["exchanges"] == {}
    assert snapshot["recent_failures"][0]["job_id"] == "job-2"


def test_export_bundle_is_filtered_and_deterministic(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    seed(db_path)
    observability = FederatedObservability(db_path)

    first = observability.export_bundle(node_id="node-1", job_id="job-1")
    second = observability.export_bundle(node_id="node-1", job_id="job-1")

    assert first["sha256"] == second["sha256"]
    assert len(first["sha256"]) == 64
    assert [row["job_id"] for row in first["bundle"]["jobs"]] == ["job-1"]
    assert [row["node_id"] for row in first["bundle"]["nodes"]] == ["node-1"]
    json.dumps(first, sort_keys=True)


def test_empty_database_returns_safe_empty_snapshot(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.db"
    snapshot = FederatedObservability(db_path).snapshot()

    assert snapshot["nodes"] == {}
    assert snapshot["jobs"] == {}
    assert snapshot["recent_failures"] == []
