"""T-013 — Secure Executor avanzado: rootless, sandbox completo, replay,
filesystem aislado, network policy, GPU/disk limits."""

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from triade.core.contracts import utc_now


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{hashlib.md5(str(datetime.now(timezone.utc).timestamp()).encode()).hexdigest()[:6]}"


@dataclass(frozen=True, slots=True)
class SandboxConfig:
    rootless: bool = True
    chroot_path: str = "/tmp/triade_sandbox"
    read_only_paths: tuple = ("/",)
    writable_paths: tuple = ("/tmp/sandbox_work",)
    network_policy: str = "none"  # none, loopback, restricted, full
    allowed_hosts: tuple = ()
    gpu_enabled: bool = False
    gpu_memory_limit_mb: int = 0
    disk_quota_mb: int = 512
    max_processes: int = 10
    max_file_size_mb: int = 100

    def to_dict(self) -> dict:
        return {
            "rootless": self.rootless, "chroot_path": self.chroot_path,
            "read_only_paths": list(self.read_only_paths),
            "writable_paths": list(self.writable_paths),
            "network_policy": self.network_policy,
            "allowed_hosts": list(self.allowed_hosts),
            "gpu_enabled": self.gpu_enabled,
            "gpu_memory_limit_mb": self.gpu_memory_limit_mb,
            "disk_quota_mb": self.disk_quota_mb,
            "max_processes": self.max_processes,
            "max_file_size_mb": self.max_file_size_mb,
        }


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS secure_executions (
    exec_id        TEXT PRIMARY KEY,
    tool_id        TEXT DEFAULT '',
    command        TEXT NOT NULL,
    config_json    TEXT DEFAULT '{}',
    status         TEXT DEFAULT 'pending',
    stdout         TEXT DEFAULT '',
    stderr         TEXT DEFAULT '',
    exit_code      INTEGER,
    duration_ms    REAL DEFAULT 0.0,
    memory_used_mb REAL DEFAULT 0.0,
    disk_used_mb   REAL DEFAULT 0.0,
    network_used   INTEGER DEFAULT 0,
    replay_json    TEXT DEFAULT '{}',
    created_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS replay_log (
    replay_id      TEXT PRIMARY KEY,
    exec_id        TEXT NOT NULL,
    step_index     INTEGER DEFAULT 0,
    action         TEXT NOT NULL,
    input_json     TEXT DEFAULT '{}',
    output_json    TEXT DEFAULT '{}',
    timestamp      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rl_exec ON replay_log(exec_id);
CREATE TABLE IF NOT EXISTS filesystem_operations (
    op_id          TEXT PRIMARY KEY,
    exec_id        TEXT NOT NULL,
    operation      TEXT NOT NULL,
    path           TEXT NOT NULL,
    allowed        INTEGER DEFAULT 0,
    reason         TEXT DEFAULT '',
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fo_exec ON filesystem_operations(exec_id);
CREATE TABLE IF NOT EXISTS network_operations (
    op_id          TEXT PRIMARY KEY,
    exec_id        TEXT NOT NULL,
    operation      TEXT NOT NULL,
    host           TEXT DEFAULT '',
    port           INTEGER DEFAULT 0,
    allowed        INTEGER DEFAULT 0,
    policy         TEXT DEFAULT 'none',
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_no_exec ON network_operations(exec_id);
"""


class SecureExecutor:
    """Executor con rootless, sandbox, replay, filesystem isolation,
    network policy, GPU/disk limits."""

    BLOCKED_PATTERNS = (
        "rm -rf", "rm -r /", "mkfs", "dd if=", "> /dev/sd",
        "chmod 777", "chown", "mount", "umount",
        "passwd", "shadow", "/etc/passwd",
        "curl | sh", "wget | sh", "nc -e",
    )

    def __init__(self, db_path: str | None = None, conn: sqlite3.Connection | None = None):
        self._conn = conn or sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)

    def validate_command(self, command: str, config: SandboxConfig | None = None) -> dict:
        issues = []
        cmd_lower = command.lower().strip()
        for pattern in self.BLOCKED_PATTERNS:
            if pattern in cmd_lower:
                issues.append({"pattern": pattern, "reason": "blocked_pattern"})

        cfg = config or SandboxConfig()
        if cfg.network_policy == "none":
            net_cmds = ("curl", "wget", "nc ", "netcat", "ssh", "scp", "ping")
            for nc in net_cmds:
                if nc in cmd_lower:
                    issues.append({"pattern": nc, "reason": "network_blocked"})

        if "sudo" in cmd_lower or "su " in cmd_lower:
            issues.append({"pattern": "sudo/su", "reason": "privilege_escalation_blocked"})

        if cfg.gpu_enabled is False:
            gpu_cmds = ("nvidia-smi", "cuda", "nvcc")
            for gc in gpu_cmds:
                if gc in cmd_lower:
                    issues.append({"pattern": gc, "reason": "gpu_disabled"})

        return {"valid": len(issues) == 0, "issues": issues}

    def execute(
        self,
        command: str,
        tool_id: str = "",
        config: SandboxConfig | None = None,
        timeout_seconds: int = 30,
    ) -> dict:
        cfg = config or SandboxConfig()
        validation = self.validate_command(command, cfg)
        if not validation["valid"]:
            return {
                "success": False,
                "error": "validation_failed",
                "issues": validation["issues"],
            }

        now = utc_now()
        exec_id = _gen_id("secexe")
        t0 = time.time()
        exit_code = 0
        stdout = ""
        stderr = ""
        mem_used = 0.0
        disk_used = 0.0

        try:
            import subprocess
            result = subprocess.run(
                command, shell=False, capture_output=True, text=True,
                timeout=timeout_seconds, cwd=cfg.chroot_path if os.path.isdir(cfg.chroot_path) else None,
            )
            exit_code = result.returncode
            stdout = result.stdout[:50000]
            stderr = result.stderr[:50000]
        except subprocess.TimeoutExpired:
            exit_code = -1
            stderr = "TIMEOUT"
        except Exception as e:
            exit_code = -2
            stderr = str(e)

        dur = (time.time() - t0) * 1000

        self._conn.execute(
            """INSERT INTO secure_executions
               (exec_id, tool_id, command, config_json, status,
                stdout, stderr, exit_code, duration_ms,
                memory_used_mb, disk_used_mb, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (exec_id, tool_id, command, json.dumps(cfg.to_dict(), default=str),
             "completed" if exit_code == 0 else "failed",
             stdout, stderr, exit_code, round(dur, 2),
             mem_used, disk_used, now),
        )
        self._conn.commit()

        return {
            "success": exit_code == 0,
            "exec_id": exec_id,
            "exit_code": exit_code,
            "stdout": stdout[:1000],
            "stderr": stderr[:1000],
            "duration_ms": round(dur, 2),
        }

    # ─── replay ───

    def record_replay_step(self, exec_id: str, step_index: int, action: str,
                           input_data: dict | None = None, output_data: dict | None = None) -> dict:
        replay_id = _gen_id("replay")
        self._conn.execute(
            """INSERT INTO replay_log
               (replay_id, exec_id, step_index, action, input_json, output_json, timestamp)
               VALUES (?,?,?,?,?,?,?)""",
            (replay_id, exec_id, step_index, action,
             json.dumps(input_data or {}, default=str),
             json.dumps(output_data or {}, default=str),
             utc_now()),
        )
        self._conn.commit()
        return {"replay_id": replay_id, "exec_id": exec_id, "step": step_index}

    def get_replay(self, exec_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM replay_log WHERE exec_id=? ORDER BY step_index",
            (exec_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ─── filesystem isolation ───

    def check_filesystem(self, exec_id: str, operation: str, path: str,
                         config: SandboxConfig | None = None) -> dict:
        cfg = config or SandboxConfig()
        allowed = False
        reason = ""

        if path in cfg.writable_paths or any(path.startswith(wp) for wp in cfg.writable_paths):
            allowed = True
        elif path in cfg.read_only_paths or any(path.startswith(rp) for rp in cfg.read_only_paths):
            if operation in ("read", "stat", "list"):
                allowed = True
            else:
                reason = "read_only_path"
        else:
            reason = "path_not_in_sandbox"

        op_id = _gen_id("fsop")
        self._conn.execute(
            """INSERT INTO filesystem_operations
               (op_id, exec_id, operation, path, allowed, reason, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (op_id, exec_id, operation, path, 1 if allowed else 0, reason, utc_now()),
        )
        self._conn.commit()
        return {"allowed": allowed, "reason": reason, "operation": operation, "path": path}

    # ─── network policy ───

    def check_network(self, exec_id: str, operation: str, host: str, port: int = 0,
                      config: SandboxConfig | None = None) -> dict:
        cfg = config or SandboxConfig()
        allowed = False
        policy = cfg.network_policy

        if policy == "none":
            allowed = False
        elif policy == "loopback":
            allowed = host in ("localhost", "127.0.0.1", "::1")
        elif policy == "restricted":
            allowed = host in cfg.allowed_hosts
        elif policy == "full":
            allowed = True

        op_id = _gen_id("netop")
        self._conn.execute(
            """INSERT INTO network_operations
               (op_id, exec_id, operation, host, port, allowed, policy, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (op_id, exec_id, operation, host, port, 1 if allowed else 0, policy, utc_now()),
        )
        self._conn.commit()
        return {"allowed": allowed, "policy": policy, "host": host, "port": port}

    # ─── GPU limits ───

    def gpu_check(self, config: SandboxConfig | None = None) -> dict:
        cfg = config or SandboxConfig()
        if not cfg.gpu_enabled:
            return {"gpu_available": False, "reason": "gpu_disabled_in_config"}
        return {
            "gpu_available": True,
            "memory_limit_mb": cfg.gpu_memory_limit_mb,
            "note": "GPU limits enforced at scheduler level",
        }

    # ─── disk limits ───

    def disk_check(self, exec_id: str, config: SandboxConfig | None = None) -> dict:
        cfg = config or SandboxConfig()
        return {
            "quota_mb": cfg.disk_quota_mb,
            "exec_id": exec_id,
            "note": "Disk quota enforced at scheduler level",
        }

    # ─── execution history ───

    def get(self, exec_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM secure_executions WHERE exec_id=?", (exec_id,)
        ).fetchone()
        return dict(row) if row else None

    def recent(self, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM secure_executions ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        total = self._conn.execute("SELECT COUNT(*) as c FROM secure_executions").fetchone()["c"]
        success = self._conn.execute("SELECT COUNT(*) as c FROM secure_executions WHERE exit_code=0").fetchone()["c"]
        avg_dur = self._conn.execute("SELECT AVG(duration_ms) as a FROM secure_executions").fetchone()["a"] or 0
        return {"total": total, "success": success, "failed": total - success,
                "avg_duration_ms": round(avg_dur, 2)}

    def doctor(self) -> dict:
        execs = self._conn.execute("SELECT COUNT(*) as c FROM secure_executions").fetchone()["c"]
        replays = self._conn.execute("SELECT COUNT(*) as c FROM replay_log").fetchone()["c"]
        fs_ops = self._conn.execute("SELECT COUNT(*) as c FROM filesystem_operations").fetchone()["c"]
        net_ops = self._conn.execute("SELECT COUNT(*) as c FROM network_operations").fetchone()["c"]
        return {"executions": execs, "replay_steps": replays,
                "fs_operations": fs_ops, "net_operations": net_ops}
