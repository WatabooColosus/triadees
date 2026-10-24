"""Authorized real API crash; observe its existing supervisor, never restart it."""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
import urllib.request
from datetime import UTC, datetime

import psutil

from scripts.run_level8_soak import ROOT, bind_report


def get(path):
    with urllib.request.urlopen("http://127.0.0.1:8010" + path, timeout=5) as r:
        return r.status, json.load(r)


def database():
    with sqlite3.connect(
        (ROOT / "triade/memory/triade.db").as_uri() + "?mode=ro", uri=True
    ) as c:
        return {
            "integrity": c.execute("PRAGMA integrity_check").fetchone()[0],
            "identity": c.execute(
                "SELECT identity_core_hash,manifest_hash FROM identity_manifest_anchor"
            ).fetchall(),
        }


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(
        description="Prueba manual DISRUPTIVA de recuperación: termina la API existente."
    )
    parser.add_argument(
        "--confirm-runtime-pid",
        type=int,
        help="PID exacto de la API autorizado por el operador; obligatorio para terminarla",
    )
    args = parser.parse_args(argv)
    if args.confirm_runtime_pid is None or args.confirm_runtime_pid <= 0:
        parser.error(
            "sin confirmación explícita del PID: no se consulta ni detiene la API"
        )
    _, hb = get("/api/runtime/heartbeat")
    pid = int(hb["runtime_pid"])
    if pid != args.confirm_runtime_pid:
        raise RuntimeError(
            "PID cambió o no coincide con la autorización; no se detiene"
        )

    process = psutil.Process(pid)
    if "scripts.serve_local_api" not in process.cmdline():
        raise RuntimeError("refusing to kill an unrelated process")
    parent = process.parent()
    if parent is None or not any(
        "triade_service_worker.ps1" in arg for arg in parent.cmdline()
    ):
        raise RuntimeError("expected existing supervisor not verified")
    prior = database()
    start = time.monotonic()
    # No destructive action unless both the operator's PID and supervisor checks match.
    process.terminate()
    deadline = start + 120
    after = None
    while time.monotonic() < deadline:
        try:
            status, _deep = get("/health/deep")
            _, hb = get("/api/runtime/heartbeat")
            newpid = int(hb.get("runtime_pid", 0))
            if (
                newpid
                and newpid != pid
                and hb.get("workers_active") is True
                and psutil.Process(newpid).ppid() == parent.pid
            ):
                after = {"status": status, "pid": newpid}
                break
        except (OSError, ValueError, KeyError, psutil.Error):
            pass
        time.sleep(1)
    if after is None:
        raise RuntimeError("automatic API recovery not observed")
    elapsed = time.monotonic() - start
    _, first = get("/api/runtime/metabolism/status")
    cycles = first["metabolism"]["cycle_count"]
    deadline = time.monotonic() + 75
    last = first
    while time.monotonic() < deadline:
        _, last = get("/api/runtime/metabolism/status")
        if last["metabolism"]["cycle_count"] > cycles:
            break
        time.sleep(2)
    state = database()
    metabolism = last["metabolism"]
    api = {
        "pid_before": pid,
        "pid_after": after["pid"],
        "supervisor_pid": parent.pid,
        "automatic_recovery": True,
        "recovery_seconds": elapsed,
        "deep_health_status": after["status"],
        "workers_active": hb["workers_active"],
        "metabolism_progress": metabolism["cycle_count"] > cycles,
        "metabolism_error": metabolism.get("last_tick_error"),
        "db_integrity": state["integrity"],
        "identity_preserved": state["identity"] == prior["identity"]
        and bool(state["identity"]),
    }
    task = json.loads((ROOT / "reports/level8/recovery_task_inflight.json").read_text())
    result = bind_report(
        {
            "git_sha": task["git_sha"],
            "timestamp": datetime.now(UTC).isoformat(),
            "api": api,
            "task": task,
            "truth": task["truth"]
            and api["metabolism_progress"]
            and api["metabolism_error"] is None
            and api["identity_preserved"]
            and api["db_integrity"] == "ok",
            "scope": "Isolated in-flight queue crash plus actual production API supervisor recovery; not a single production-task fault experiment",
        }
    )
    (ROOT / "reports/level8/recovery_end_to_end.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"truth": result["truth"], "api": api}))
    return 0 if result["truth"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
