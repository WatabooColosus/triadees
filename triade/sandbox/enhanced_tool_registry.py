"""T-012 — Tool Registry avanzado: contratos formales, riesgo, timeouts,
permisos, recursos, auditoría, versionado."""

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from triade.core.contracts import utc_now


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{hashlib.md5(str(datetime.now(timezone.utc).timestamp()).encode()).hexdigest()[:6]}"


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


@dataclass(frozen=True, slots=True)
class ToolContract:
    tool_id: str
    name: str
    version: str = "1.0.0"
    category: str = "system"
    description: str = ""
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)
    risk_level: str = "low"  # low, medium, high, critical
    timeout_seconds: int = 30
    max_memory_mb: int = 256
    permissions: tuple = ("read",)
    requires_sandbox: bool = False
    requires_network: bool = False
    requires_gpu: bool = False
    max_concurrent: int = 1
    tags: tuple = ()

    def to_dict(self) -> dict:
        return {
            "tool_id": self.tool_id, "name": self.name, "version": self.version,
            "category": self.category, "description": self.description,
            "risk_level": self.risk_level, "timeout_seconds": self.timeout_seconds,
            "max_memory_mb": self.max_memory_mb, "permissions": list(self.permissions),
            "requires_sandbox": self.requires_sandbox,
            "requires_network": self.requires_network,
            "requires_gpu": self.requires_gpu,
            "max_concurrent": self.max_concurrent, "tags": list(self.tags),
        }


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tool_contracts (
    tool_id        TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    version        TEXT DEFAULT '1.0.0',
    category       TEXT DEFAULT 'system',
    description    TEXT DEFAULT '',
    input_schema_json  TEXT DEFAULT '{}',
    output_schema_json TEXT DEFAULT '{}',
    risk_level     TEXT DEFAULT 'low',
    timeout_seconds INTEGER DEFAULT 30,
    max_memory_mb  INTEGER DEFAULT 256,
    permissions_json TEXT DEFAULT '[]',
    requires_sandbox INTEGER DEFAULT 0,
    requires_network INTEGER DEFAULT 0,
    requires_gpu   INTEGER DEFAULT 0,
    max_concurrent INTEGER DEFAULT 1,
    tags_json      TEXT DEFAULT '[]',
    status         TEXT DEFAULT 'active',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tool_versions (
    version_id     TEXT PRIMARY KEY,
    tool_id        TEXT NOT NULL,
    version        TEXT NOT NULL,
    contract_json  TEXT DEFAULT '{}',
    changelog      TEXT DEFAULT '',
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tv_tool ON tool_versions(tool_id);
CREATE TABLE IF NOT EXISTS tool_audit_log (
    audit_id       TEXT PRIMARY KEY,
    tool_id        TEXT NOT NULL,
    action         TEXT NOT NULL,
    actor          TEXT DEFAULT 'system',
    details_json   TEXT DEFAULT '{}',
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ta_tool ON tool_audit_log(tool_id);
CREATE TABLE IF NOT EXISTS tool_executions_ext (
    exec_id        TEXT PRIMARY KEY,
    tool_id        TEXT NOT NULL,
    status         TEXT DEFAULT 'pending',
    input_json     TEXT DEFAULT '{}',
    output_json    TEXT DEFAULT '{}',
    error          TEXT DEFAULT '',
    duration_ms    REAL DEFAULT 0.0,
    memory_used_mb REAL DEFAULT 0.0,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_te_tool ON tool_executions_ext(tool_id);
"""


class EnhancedToolRegistry:
    """Tool registry con contratos formales, gestión de riesgo, versionado,
    auditoría y ejecución controlada."""

    RISK_WEIGHTS = {"low": 0.1, "medium": 0.3, "high": 0.7, "critical": 1.0}

    def __init__(self, db_path: str | None = None, conn: sqlite3.Connection | None = None):
        self._conn = conn or sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)
        self._handlers: dict[str, Callable] = {}

    # ─── registration ───

    def register(self, contract: ToolContract) -> dict:
        now = utc_now()
        self._conn.execute(
            """INSERT INTO tool_contracts
               (tool_id, name, version, category, description,
                input_schema_json, output_schema_json, risk_level,
                timeout_seconds, max_memory_mb, permissions_json,
                requires_sandbox, requires_network, requires_gpu,
                max_concurrent, tags_json, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (contract.tool_id, contract.name, contract.version, contract.category,
             contract.description, json.dumps(contract.input_schema, default=str),
             json.dumps(contract.output_schema, default=str), contract.risk_level,
             contract.timeout_seconds, contract.max_memory_mb,
             json.dumps(list(contract.permissions), default=str),
             1 if contract.requires_sandbox else 0,
             1 if contract.requires_network else 0,
             1 if contract.requires_gpu else 0,
             contract.max_concurrent, json.dumps(list(contract.tags), default=str),
             "active", now, now),
        )
        self._conn.execute(
            """INSERT INTO tool_versions (version_id, tool_id, version, contract_json, created_at)
               VALUES (?,?,?,?,?)""",
            (_gen_id("tver"), contract.tool_id, contract.version,
             json.dumps(contract.to_dict(), default=str), now),
        )
        self._audit(contract.tool_id, "registered", {"version": contract.version})
        self._conn.commit()
        return contract.to_dict()

    def register_handler(self, tool_id: str, handler: Callable):
        self._handlers[tool_id] = handler

    def get(self, tool_id: str) -> ToolContract | None:
        row = self._conn.execute(
            "SELECT * FROM tool_contracts WHERE tool_id=? AND status='active'",
            (tool_id,),
        ).fetchone()
        if not row:
            return None
        return _row_to_contract(row)

    def list_tools(self, category: str | None = None) -> list[dict]:
        if category:
            rows = self._conn.execute(
                "SELECT * FROM tool_contracts WHERE category=? AND status='active' ORDER BY name",
                (category,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM tool_contracts WHERE status='active' ORDER BY category, name"
            ).fetchall()
        return [_row_to_contract(r).to_dict() for r in rows]

    # ─── versioning ───

    def new_version(self, tool_id: str, contract: ToolContract, changelog: str = "") -> dict:
        now = utc_now()
        old = self.get(tool_id)
        if old:
            self._conn.execute(
                "UPDATE tool_contracts SET status='deprecated' WHERE tool_id=?",
                (tool_id,),
            )
        new_contract = ToolContract(
            tool_id=tool_id, name=contract.name, version=contract.version,
            category=contract.category, description=contract.description,
            input_schema=contract.input_schema, output_schema=contract.output_schema,
            risk_level=contract.risk_level, timeout_seconds=contract.timeout_seconds,
            max_memory_mb=contract.max_memory_mb, permissions=contract.permissions,
            requires_sandbox=contract.requires_sandbox,
            requires_network=contract.requires_network,
            requires_gpu=contract.requires_gpu,
            max_concurrent=contract.max_concurrent, tags=contract.tags,
        )
        result = self.register(new_contract)
        self._conn.execute(
            """INSERT INTO tool_versions (version_id, tool_id, version, contract_json, changelog, created_at)
               VALUES (?,?,?,?,?,?)""",
            (_gen_id("tver"), tool_id, contract.version,
             json.dumps(new_contract.to_dict(), default=str), changelog, now),
        )
        self._audit(tool_id, "new_version", {"version": contract.version, "changelog": changelog})
        self._conn.commit()
        return result

    def version_history(self, tool_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM tool_versions WHERE tool_id=? ORDER BY created_at DESC",
            (tool_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ─── risk & permissions ───

    def risk_score(self, tool_id: str) -> dict:
        c = self.get(tool_id)
        if not c:
            return {"tool_id": tool_id, "risk_score": 0, "level": "unknown"}
        base = self.RISK_WEIGHTS.get(c.risk_level, 0.5)
        sandbox_boost = 0.1 if c.requires_sandbox else 0.0
        network_boost = 0.15 if c.requires_network else 0.0
        gpu_boost = 0.1 if c.requires_gpu else 0.0
        score = _clamp(base + sandbox_boost + network_boost + gpu_boost)
        return {"tool_id": tool_id, "risk_score": round(score, 3), "level": c.risk_level}

    def check_permission(self, tool_id: str, required: str) -> dict:
        c = self.get(tool_id)
        if not c:
            return {"allowed": False, "reason": "tool not found"}
        allowed = required in c.permissions
        return {"allowed": allowed, "tool_id": tool_id, "required": required,
                "available": list(c.permissions)}

    def can_execute(self, tool_id: str) -> dict:
        c = self.get(tool_id)
        if not c:
            return {"allowed": False, "reason": "tool not found"}
        issues = []
        if c.risk_level == "critical":
            issues.append("critical_risk_requires_approval")
        return {"allowed": len(issues) == 0, "tool_id": tool_id, "issues": issues}

    # ─── execution ───

    def execute(self, tool_id: str, payload: dict) -> dict:
        contract = self.get(tool_id)
        if not contract:
            return {"success": False, "error": f"Tool {tool_id} not found"}

        can = self.can_execute(tool_id)
        if not can["allowed"]:
            return {"success": False, "error": "execution blocked", "issues": can["issues"]}

        handler = self._handlers.get(tool_id)
        if not handler:
            return {"success": False, "error": "no handler registered"}

        now = utc_now()
        exec_id = _gen_id("texe")
        import time
        import concurrent.futures
        t0 = time.time()
        timeout = contract.timeout_seconds if hasattr(contract, 'timeout_seconds') else 30
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(handler, payload)
                result = future.result(timeout=timeout)
            dur = (time.time() - t0) * 1000
            self._conn.execute(
                """INSERT INTO tool_executions_ext
                   (exec_id, tool_id, status, input_json, output_json,
                    duration_ms, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (exec_id, tool_id, "success", json.dumps(payload, default=str),
                 json.dumps(result, default=str), round(dur, 2), now),
            )
            self._audit(tool_id, "executed", {"exec_id": exec_id, "duration_ms": round(dur, 2)})
            self._conn.commit()
            return {"success": True, "output": result, "exec_id": exec_id, "duration_ms": round(dur, 2)}
        except Exception as e:
            dur = (time.time() - t0) * 1000
            self._conn.execute(
                """INSERT INTO tool_executions_ext
                   (exec_id, tool_id, status, input_json, error,
                    duration_ms, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (exec_id, tool_id, "error", json.dumps(payload, default=str),
                 str(e), round(dur, 2), now),
            )
            self._audit(tool_id, "execution_failed", {"exec_id": exec_id, "error": str(e)})
            self._conn.commit()
            return {"success": False, "error": str(e), "exec_id": exec_id}

    # ─── audit ───

    def _audit(self, tool_id: str, action: str, details: dict | None = None):
        self._conn.execute(
            """INSERT INTO tool_audit_log (audit_id, tool_id, action, details_json, created_at)
               VALUES (?,?,?,?,?)""",
            (_gen_id("taudit"), tool_id, action,
             json.dumps(details or {}, default=str), utc_now()),
        )

    def audit_log(self, tool_id: str, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM tool_audit_log WHERE tool_id=? ORDER BY created_at DESC LIMIT ?",
            (tool_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def execution_stats(self, tool_id: str) -> dict:
        rows = self._conn.execute(
            "SELECT * FROM tool_executions_ext WHERE tool_id=?", (tool_id,)
        ).fetchall()
        total = len(rows)
        success = sum(1 for r in rows if r["status"] == "success")
        avg_dur = sum(r["duration_ms"] for r in rows) / max(total, 1)
        return {
            "tool_id": tool_id, "total": total, "success": success,
            "failed": total - success, "avg_duration_ms": round(avg_dur, 2),
        }

    def deactivate(self, tool_id: str, reason: str = "") -> dict:
        self._conn.execute(
            "UPDATE tool_contracts SET status='deprecated' WHERE tool_id=?",
            (tool_id,),
        )
        self._audit(tool_id, "deactivated", {"reason": reason})
        self._conn.commit()
        return {"tool_id": tool_id, "status": "deprecated"}

    def doctor(self) -> dict:
        total = self._conn.execute("SELECT COUNT(*) as c FROM tool_contracts WHERE status='active'").fetchone()["c"]
        versions = self._conn.execute("SELECT COUNT(*) as c FROM tool_versions").fetchone()["c"]
        audits = self._conn.execute("SELECT COUNT(*) as c FROM tool_audit_log").fetchone()["c"]
        execs = self._conn.execute("SELECT COUNT(*) as c FROM tool_executions_ext").fetchone()["c"]
        return {"active_tools": total, "versions": versions, "audit_entries": audits, "executions": execs}


def _row_to_contract(row) -> ToolContract:
    d = dict(row)
    return ToolContract(
        tool_id=d["tool_id"], name=d["name"], version=d["version"],
        category=d["category"], description=d["description"],
        input_schema=json.loads(d["input_schema_json"]) if d.get("input_schema_json") else {},
        output_schema=json.loads(d["output_schema_json"]) if d.get("output_schema_json") else {},
        risk_level=d["risk_level"], timeout_seconds=d["timeout_seconds"],
        max_memory_mb=d["max_memory_mb"],
        permissions=tuple(json.loads(d["permissions_json"])) if d.get("permissions_json") else ("read",),
        requires_sandbox=bool(d["requires_sandbox"]),
        requires_network=bool(d["requires_network"]),
        requires_gpu=bool(d["requires_gpu"]),
        max_concurrent=d["max_concurrent"],
        tags=tuple(json.loads(d["tags_json"])) if d.get("tags_json") else (),
    )
