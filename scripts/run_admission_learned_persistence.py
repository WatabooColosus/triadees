"""Use consolidated learning in two independent, cleanly exiting runtime processes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from triade.db import sqlite3

ROOT = Path(__file__).resolve().parents[1]
TRIADE_ENTRYPOINT_KIND = "manual_diagnostic"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child-input", type=int)
    args = parser.parse_args()
    prior = json.loads(
        (ROOT / "reports/evolution/productive_learning_chain_v3.json").read_text(
            encoding="utf-8"
        )
    )
    work = Path(prior["artifact_ref"]).resolve()
    if not work.is_relative_to(ROOT / "artifacts/evolution"):
        raise ValueError("experiment_outside_authorized_scope")
    from triade.learning.pipeline import LearningPipeline
    from triade.memory.semantic_store import SemanticMemoryStore

    candidate = LearningPipeline(work / "learning.db").get_candidate(
        prior["candidate_id"]
    )
    document_id = candidate["verification_notes"]["consolidated"][
        "semantic_document_id"
    ]
    document = SemanticMemoryStore(work / "learning.db").get_document(document_id)
    if (
        candidate["status"] != "consolidated"
        or not document
        or document["status"] != "stable"
    ):
        raise RuntimeError("consolidated_learning_required")
    if args.child_input is not None:
        from triade.core.ollama_blood import check_ollama_blood
        from triade.core.runner import TriadeRunner
        from triade.learning.knowledge_probe import build_transfer_probe

        os.environ.setdefault("TRIADE_NEURAL_LEARNING_ROUTING", "1")
        probe = build_transfer_probe(
            work / "learning.db", prior["candidate_id"], args.child_input
        )
        if probe is None:
            raise RuntimeError("independent_application_probe_unavailable")
        model = check_ollama_blood()["reasoning_model"]
        run = TriadeRunner(
            db_path=work / "learning.db",
            runs_dir=work / "runs",
            use_ollama=True,
            auto_select_models=False,
            central_model=model,
            hypothalamus_model=model,
        ).run(
            probe.question,
            source="learning_persistence_verification",
            propose_neurons=False,
            context={
                "learning_candidate_ids": [prior["candidate_id"]],
                "correlation_id": prior["correlation_id"],
                "declared_output_schema": probe.response_format,
            },
        )
        output = json.loads(
            (Path(run["run_path"]) / "output.json").read_text(encoding="utf-8")
        )
        confirmed = (
            output.get("memory_diff", {})
            .get("knowledge_causal_use", {})
            .get("confirmed", [])
        )
        result = {
            "pid": os.getpid(),
            "run_id": run["run_id"],
            "stable_knowledge_id": document_id,
            "objective_pass": probe.evaluator(output["response"]),
            "response": output["response"],
            "knowledge_used": any(
                x["candidate_id"] == prior["candidate_id"] for x in confirmed
            ),
            "run_closed": (Path(run["run_path"]) / "CLOSED").exists(),
        }
        print("PERSISTENCE_RESULT=" + json.dumps(result))
        return (
            0
            if result["objective_pass"]
            and result["knowledge_used"]
            and result["run_closed"]
            else 1
        )

    def anchor():
        with sqlite3.connect(
            (work / "learning.db").as_uri() + "?mode=ro", uri=True
        ) as conn:
            rows = conn.execute(
                "SELECT key,value FROM identity_core ORDER BY key"
            ).fetchall()
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        return {
            "identity_hash": hashlib.sha256(json.dumps(rows).encode()).hexdigest(),
            "integrity": integrity,
        }

    before = anchor()
    processes = []
    for value in (263, 307):
        command = [
            sys.executable,
            "-m",
            "scripts.run_admission_learned_persistence",
            "--child-input",
            str(value),
        ]
        process = subprocess.run(
            command, cwd=ROOT, text=True, capture_output=True, timeout=300, check=False
        )
        lines = [
            line
            for line in process.stdout.splitlines()
            if line.startswith("PERSISTENCE_RESULT=")
        ]
        processes.append(
            {
                "command": command,
                "exit_code": process.returncode,
                "result": json.loads(lines[-1].split("=", 1)[1]) if lines else None,
                "stderr": process.stderr[-1200:],
            }
        )
        if process.returncode:
            break
    after = anchor()
    result = {
        "timestamp": datetime.now(UTC).isoformat(),
        "tested_source_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "correlation_id": prior["correlation_id"],
        "candidate_id": prior["candidate_id"],
        "stable_knowledge_id_before": document_id,
        "before": before,
        "after": after,
        "processes": processes,
        "scope": "Two independent normal TriadeRunner processes using existing experiment DB; not an API restart or crash-recovery claim",
        "truth": len(processes) == 2
        and all(
            x["exit_code"] == 0 and x["result"]["stable_knowledge_id"] == document_id
            for x in processes
        )
        and processes[0]["result"]["pid"] != processes[1]["result"]["pid"]
        and before == after,
    }
    (ROOT / "reports/evolution/admission_learned_persistence_latest.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "truth": result["truth"],
                "stable_knowledge_id": document_id,
                "exit_codes": [x["exit_code"] for x in processes],
            }
        )
    )
    return 0 if result["truth"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
