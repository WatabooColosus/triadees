"""Auditoría del runtime vivo: observa, no supone.

Captura el estado real del sistema en ejecución —procesos, puertos, locks,
heartbeat, tareas, canaries, SQLite— y lo escribe como JSON para poder comparar
snapshots a lo largo del tiempo.

Principio: un servicio no está sano porque diga estarlo. Cada componente tiene
que cumplir una **postcondición observable** (responde, avanza, cambia). Un
heartbeat que no se mueve es un servicio muerto que miente.

Uso:
    python scripts/live_runtime_audit.py --out runs/live-runtime-audit/<ts>/baseline.json
    python scripts/live_runtime_audit.py --watch 600 --interval 10 --out-dir runs/...
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "triade/memory/triade.db"
API = os.getenv("TRIADE_AUDIT_API", "http://127.0.0.1:8010")
OLLAMA = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")


def _sh(cmd: str, timeout: int = 15) -> str:
    try:
        out = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return (out.stdout or out.stderr or "").strip()
    except (subprocess.SubprocessError, OSError) as exc:
        return f"<error: {type(exc).__name__}: {exc}>"


def _http(url: str, timeout: float = 20.0) -> dict[str, Any]:
    """Mide latencia y estado. Un timeout aquí ES el hallazgo, no un error."""
    started = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
            body = response.read()
            return {
                "status": response.status,
                "seconds": round(time.monotonic() - started, 3),
                "bytes": len(body),
            }
    except urllib.error.HTTPError as exc:
        return {
            "status": exc.code,
            "seconds": round(time.monotonic() - started, 3),
            "error": "http_error",
        }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {
            "status": 0,
            "seconds": round(time.monotonic() - started, 3),
            "error": f"{type(exc).__name__}: {exc}"[:120],
            "hung": round(time.monotonic() - started, 3) >= timeout - 0.5,
        }


# ── procesos ────────────────────────────────────────────────────────────
def processes() -> list[dict[str, Any]]:
    """Procesos de Tríade con su coste real, no solo su existencia."""
    patterns = {
        "api": "uvicorn apps.single_port_app",
        "ollama": "ollama serve",
        "worker_supervisor": "worker_supervisor",
        "watchdog": "runtime_watchdog",
    }
    found: list[dict[str, Any]] = []
    for name, pattern in patterns.items():
        pids = _sh(f"pgrep -f '{pattern}'").split()
        for pid in pids:
            if not pid.isdigit():
                continue
            stat = _sh(f"ps -p {pid} -o rss=,pcpu=,etimes=,stat=,nlwp= 2>/dev/null")
            if not stat or stat.startswith("<error"):
                continue
            parts = stat.split()
            if len(parts) < 5:
                continue
            # El wrapper de shell aparece con el mismo patrón; se distingue por
            # tener un solo hilo y RSS ridículo. No es el servidor.
            found.append(
                {
                    "service": name,
                    "pid": int(pid),
                    "rss_mb": round(int(parts[0]) / 1024, 1),
                    "cpu_percent": float(parts[1]),
                    "uptime_seconds": int(parts[2]),
                    "state": parts[3],
                    "threads": int(parts[4]),
                    "zombie": parts[3].startswith("Z"),
                }
            )
    return found


def zombies() -> list[str]:
    out = _sh("ps -eo pid,ppid,stat,comm --no-headers | awk '$3 ~ /^Z/'")
    return [line for line in out.splitlines() if line.strip()]


def listening_ports() -> list[str]:
    out = _sh("ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null")
    return [
        line.strip()
        for line in out.splitlines()
        if re.search(r":(8010|11434|5678|8000)\b", line)
    ]


def systemd_units() -> dict[str, str]:
    units = ["triade.service", "triade-api.service", "ollama.service"]
    result: dict[str, str] = {}
    for unit in units:
        state = _sh(f"systemctl is-active {unit} 2>&1")
        if state and "not-found" not in state and "<error" not in state:
            result[unit] = state
    return result or {"note": "sin unidades systemd activas (arranque manual)"}


def locks() -> dict[str, Any]:
    """Un lock sin dueño vivo es peor que no tener lock."""
    result: dict[str, Any] = {}
    for name in (".triade_workers.lock", ".triade_stop"):
        path = REPO / name
        if not path.exists():
            result[name] = {"present": False}
            continue
        raw = path.read_text(encoding="utf-8", errors="replace")[:400]
        owner_alive = None
        match = re.search(r"\b(\d{2,7})\b", raw)
        if match:
            pid = match.group(1)
            owner_alive = Path(f"/proc/{pid}").exists()
        result[name] = {
            "present": True,
            "age_seconds": round(time.time() - path.stat().st_mtime, 1),
            "content": raw,
            "owner_alive": owner_alive,
            "stale": owner_alive is False,
        }
    return result


# ── base de datos ───────────────────────────────────────────────────────
def _connect_ro() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def database(deep: bool = False) -> dict[str, Any]:
    info: dict[str, Any] = {
        "path": str(DB),
        "size_mb": round(DB.stat().st_size / 1e6, 2) if DB.exists() else None,
    }
    try:
        conn = _connect_ro()
    except sqlite3.Error as exc:
        return {**info, "error": str(exc)}
    try:
        for pragma in ("journal_mode", "busy_timeout", "foreign_keys"):
            info[pragma] = conn.execute(f"PRAGMA {pragma}").fetchone()[0]
        if deep:
            # integrity_check es caro; solo en la línea base.
            info["integrity_check"] = conn.execute("PRAGMA integrity_check").fetchone()[
                0
            ]
        info["tasks_by_status"] = {
            str(row["status"]): int(row["n"])
            for row in conn.execute(
                "SELECT status, COUNT(*) n FROM autonomous_tasks GROUP BY status"
            )
        }
        info["counts"] = {}
        for table in (
            "autonomous_tasks",
            "worker_runs",
            "worker_events",
            "verification_reports",
            "runs",
            "qualia_experiences",
            "learning_queue",
            "improvement_canaries",
            "improvement_proposals",
            "improvement_candidate_links",
        ):
            try:
                info["counts"][table] = conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
            except sqlite3.Error:
                info["counts"][table] = None
        info["stuck_tasks"] = _stuck_tasks(conn)
        info["learning_pipeline"] = _learning_pipeline(conn)
        info["canaries"] = _canaries(conn)
    finally:
        conn.close()
    return info


def _stuck_tasks(conn: sqlite3.Connection) -> dict[str, Any]:
    """Tareas que dicen estar vivas pero no avanzan."""
    out: dict[str, Any] = {}
    try:
        rows = conn.execute(
            """SELECT task_id, task_type, status, worker_id, lease_generation,
                      lease_expires_at, heartbeat_at, updated_at, attempt, max_attempts
               FROM autonomous_tasks
               WHERE status IN ('leased','running','completion_uncertain')
               ORDER BY updated_at ASC"""
        ).fetchall()
        now = time.time()
        live: list[dict[str, Any]] = []
        for row in rows:
            entry = dict(row)
            expires = str(row["lease_expires_at"] or "")
            entry["lease_expired"] = bool(expires) and expires < _iso(now)
            entry["owner_alive"] = _worker_owner_alive(str(row["worker_id"] or ""))
            live.append(entry)
        out["active"] = live
        out["active_count"] = len(live)
        out["expired_leases"] = sum(1 for e in live if e["lease_expired"])
        # Tareas que agotaron intentos sin llegar a terminal.
        out["attempts_exhausted"] = conn.execute(
            """SELECT COUNT(*) FROM autonomous_tasks
               WHERE attempt >= max_attempts
                 AND status NOT IN ('completed','failed','dead_letter','cancelled')"""
        ).fetchone()[0]
        out["dead_letter_recent"] = conn.execute(
            """SELECT COUNT(*) FROM autonomous_tasks
               WHERE status='dead_letter' AND updated_at > ?""",
            (_iso(time.time() - 3600),),
        ).fetchone()[0]
        out["retry_wait"] = conn.execute(
            "SELECT COUNT(*) FROM autonomous_tasks WHERE status='retry_wait'"
        ).fetchone()[0]
        out["deferred"] = conn.execute(
            "SELECT COUNT(*) FROM autonomous_tasks WHERE status='deferred'"
        ).fetchone()[0]
    except sqlite3.Error as exc:
        out["error"] = str(exc)
    return out


def _worker_owner_alive(worker_id: str) -> bool | None:
    """El worker_id es un run_ref, no un PID: no se puede resolver a proceso."""
    return None if not worker_id else None


def _learning_pipeline(conn: sqlite3.Connection) -> dict[str, Any]:
    try:
        return {
            "by_status": {
                str(r["status"]): int(r["n"])
                for r in conn.execute(
                    "SELECT status, COUNT(*) n FROM learning_queue GROUP BY status"
                )
            },
            "with_run_uses": conn.execute(
                "SELECT COUNT(*) FROM learning_queue WHERE run_use_count > 0"
            ).fetchone()[0],
        }
    except sqlite3.Error as exc:
        return {"error": str(exc)}


def _canaries(conn: sqlite3.Connection) -> dict[str, Any]:
    try:
        return {
            "by_status": {
                str(r["status"]): int(r["n"])
                for r in conn.execute(
                    "SELECT status, COUNT(*) n FROM improvement_canaries GROUP BY status"
                )
            }
        }
    except sqlite3.Error:
        return {
            "note": "tabla improvement_canaries inexistente (ciclo nunca ejecutado)"
        }


def _iso(epoch: float) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(epoch, tz=UTC).isoformat()


# ── servicios ───────────────────────────────────────────────────────────
def services() -> dict[str, Any]:
    """Cada servicio con su postcondición, no solo su presencia."""
    health = _http(f"{API}/health/live", timeout=15)
    heartbeat = _http(f"{API}/api/runtime/heartbeat", timeout=30)
    dashboard = _http(f"{API}/api/ui/react-dashboard", timeout=60)
    ollama = _http(f"{OLLAMA}/api/tags", timeout=15)
    beat: dict[str, Any] = {}
    try:
        with urllib.request.urlopen(  # noqa: S310
            f"{API}/api/runtime/heartbeat", timeout=30
        ) as response:
            payload = json.loads(response.read())
        beat = {
            "workers_active": payload.get("workers_active"),
            "mode": payload.get("mode"),
            "last_cycle_at": payload.get("last_cycle_at"),
            "cycles_last_hour": payload.get("cycles_last_hour"),
            "runtime_continuity_score": payload.get("runtime_continuity_score"),
            "latest_action": payload.get("latest_action"),
            "latest_error": payload.get("latest_error"),
            "ollama_ok": (payload.get("ollama_health") or {}).get("ok"),
            "models": (payload.get("ollama_health") or {}).get("models"),
        }
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        beat = {"error": f"{type(exc).__name__}: {exc}"[:120]}
    return {
        "api_health": health,
        "api_heartbeat": heartbeat,
        # La Cabina Viva es donde apareció el deadlock: se mide siempre.
        "cabina_viva": dashboard,
        "ollama_tags": ollama,
        "heartbeat_payload": beat,
    }


def snapshot(deep: bool = False) -> dict[str, Any]:
    return {
        "timestamp": _iso(time.time()),
        "monotonic": round(time.monotonic(), 3),
        "load_average": os.getloadavg(),
        "processes": processes(),
        "zombies": zombies(),
        "listening_ports": listening_ports(),
        "systemd": systemd_units(),
        "locks": locks(),
        "services": services(),
        "database": database(deep=deep),
    }


def baseline() -> dict[str, Any]:
    return {
        "kind": "baseline",
        "branch": _sh("git branch --show-current"),
        "sha": _sh("git rev-parse HEAD"),
        "main_sha": _sh("git rev-parse origin/main"),
        "dirty": bool(_sh("git status --porcelain")),
        "disk_free_gb": round(shutil.disk_usage(REPO).free / 1e9, 1),
        **snapshot(deep=True),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=str, default="")
    parser.add_argument("--out-dir", type=str, default="")
    parser.add_argument("--watch", type=int, default=0, help="segundos a observar")
    parser.add_argument("--interval", type=int, default=10)
    args = parser.parse_args()

    if args.watch:
        out_dir = Path(args.out_dir or "runs/live-runtime-audit/watch")
        out_dir.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + args.watch
        index = 0
        while time.monotonic() < deadline:
            snap = snapshot()
            path = out_dir / f"snapshot-{index:04d}.json"
            path.write_text(
                json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            beat = snap["services"]["heartbeat_payload"]
            cabina = snap["services"]["cabina_viva"]
            tasks = snap["database"].get("tasks_by_status", {})
            print(
                f"[{index:03d}] {snap['timestamp'][11:19]} "
                f"cabina={cabina.get('status')}/{cabina.get('seconds')}s "
                f"cycles_h={beat.get('cycles_last_hour')} "
                f"last_cycle={str(beat.get('last_cycle_at'))[11:19]} "
                f"tasks={tasks} load={snap['load_average'][0]:.2f}",
                flush=True,
            )
            index += 1
            time.sleep(max(1, args.interval))
        print(f"{index} snapshots en {out_dir}")
        return 0

    data = baseline()
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"baseline -> {path}")
    else:
        print(json.dumps(data, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
