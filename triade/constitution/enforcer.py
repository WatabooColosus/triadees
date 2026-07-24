"""T-017 — Constitución universal: enforcement automático de los 10
artículos de la constitución de Tríade Ω sobre todos los componentes."""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from triade.core.contracts import utc_now


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{hashlib.md5(str(datetime.now(timezone.utc).timestamp()).encode()).hexdigest()[:6]}"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS constitution_checks (
    check_id       TEXT PRIMARY KEY,
    component      TEXT NOT NULL,
    article        INTEGER NOT NULL,
    article_name   TEXT NOT NULL,
    status         TEXT DEFAULT 'pending',
    details_json   TEXT DEFAULT '{}',
    checked_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cc_component ON constitution_checks(component);
CREATE TABLE IF NOT EXISTS constitution_violations (
    violation_id   TEXT PRIMARY KEY,
    component      TEXT NOT NULL,
    article        INTEGER NOT NULL,
    severity       TEXT DEFAULT 'medium',
    description    TEXT NOT NULL,
    context_json   TEXT DEFAULT '{}',
    status         TEXT DEFAULT 'open',
    detected_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cv_status ON constitution_violations(status);
CREATE TABLE IF NOT EXISTS constitution_enforcement_log (
    log_id         TEXT PRIMARY KEY,
    component      TEXT NOT NULL,
    action         TEXT NOT NULL,
    article        INTEGER,
    result         TEXT DEFAULT '',
    created_at     TEXT NOT NULL
);
"""

# Los 10 artículos de la constitución de Tríade Ω
ARTICLES = {
    1: {
        "name": "Identidad Inmutable",
        "description": "identity_core no puede ser modificado por aprendizaje",
        "check_type": "no_identity_mutation",
    },
    2: {
        "name": "Consentimiento Humano",
        "description": "Cambios críticos requieren aprobación humana",
        "check_type": "requires_human_approval",
    },
    3: {
        "name": "Rollback Obligatorio",
        "description": "Toda operación destructiva debe ser reversible",
        "check_type": "has_rollback",
    },
    4: {
        "name": "Aislamiento de Embeddings",
        "description": "Embeddings no deben filtrar información entre dominios",
        "check_type": "embedding_isolation",
    },
    5: {
        "name": "Consejo de Verificación",
        "description": "Cambios de alto riesgo requieren verificación múltiple",
        "check_type": "verification_council",
    },
    6: {
        "name": "Transparencia",
        "description": "Toda decisión debe ser auditable y explicada",
        "check_type": "auditable_decision",
    },
    7: {
        "name": "Límites de Recursos",
        "description": "Uso de recursos debe respetar cuotas definidas",
        "check_type": "resource_limits",
    },
    8: {
        "name": "Degradación Segura",
        "description": "El sistema debe degradarse graceful ante fallos",
        "check_type": "graceful_degradation",
    },
    9: {
        "name": "Privacidad de Datos",
        "description": "Datos personales no deben ser expuestos sin consentimiento",
        "check_type": "data_privacy",
    },
    10: {
        "name": "Mejora Continua",
        "description": "El sistema debe aprender y mejorar de forma segura",
        "check_type": "safe_improvement",
    },
}

# Componentes del sistema que deben ser chequeados
SYSTEM_COMPONENTS = [
    "central", "hypothalamus", "crystal", "qualia_bus",
    "semantic_store", "bodega", "learning_pipeline", "neuron_factory",
    "scheduler", "workers", "tool_registry", "secure_executor",
    "federation", "triadeos", "constitution",
    "creadora", "formadora", "monitor",
]


class ConstitutionEnforcer:
    """Enforcement automático de los 10 artículos sobre todos los
    componentes del sistema."""

    def __init__(self, db_path: str | None = None, conn: sqlite3.Connection | None = None):
        self._conn = conn or sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)

    def check_article(
        self, component: str, article_num: int,
        context: dict | None = None,
    ) -> dict:
        if article_num not in ARTICLES:
            raise ValueError(f"Unknown article: {article_num}")

        article = ARTICLES[article_num]
        now = utc_now()
        check_id = _gen_id("ccheck")
        status, details = self._evaluate(component, article_num, context or {})

        self._conn.execute(
            """INSERT INTO constitution_checks
               (check_id, component, article, article_name,
                status, details_json, checked_at)
               VALUES (?,?,?,?,?,?,?)""",
            (check_id, component, article_num, article["name"],
             status, json.dumps(details, default=str), now),
        )

        if status == "violation":
            self._record_violation(component, article_num, details)

        self._conn.commit()
        return {
            "check_id": check_id, "component": component,
            "article": article_num, "article_name": article["name"],
            "status": status, "details": details,
        }

    def check_all_articles(self, component: str, context: dict | None = None) -> dict:
        results = []
        violations = 0
        for art_num in ARTICLES:
            r = self.check_article(component, art_num, context)
            results.append(r)
            if r["status"] == "violation":
                violations += 1
        return {
            "component": component,
            "total_articles": len(ARTICLES),
            "passed": len(ARTICLES) - violations,
            "violations": violations,
            "results": results,
        }

    def full_constitution_check(self, context: dict | None = None) -> dict:
        all_results = {}
        total_violations = 0
        for comp in SYSTEM_COMPONENTS:
            result = self.check_all_articles(comp, context)
            all_results[comp] = result
            total_violations += result["violations"]
        return {
            "total_components": len(SYSTEM_COMPONENTS),
            "total_violations": total_violations,
            "components": all_results,
        }

    def open_violations(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM constitution_violations WHERE status='open' ORDER BY detected_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def resolve_violation(self, violation_id: str, resolution: str = "") -> dict:
        self._conn.execute(
            "UPDATE constitution_violations SET status='resolved' WHERE violation_id=?",
            (violation_id,),
        )
        self._conn.commit()
        return {"violation_id": violation_id, "status": "resolved"}

    def enforce(self, component: str, action: str, article: int | None = None,
                details: dict | None = None) -> dict:
        log_id = _gen_id("cenf")
        now = utc_now()
        self._conn.execute(
            """INSERT INTO constitution_enforcement_log
               (log_id, component, action, article, result, created_at)
               VALUES (?,?,?,?,?,?)""",
            (log_id, component, action, article,
             json.dumps(details or {}, default=str), now),
        )
        self._conn.commit()
        return {"log_id": log_id, "component": component, "action": action}

    def check_history(self, component: str, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM constitution_checks WHERE component=? ORDER BY checked_at DESC LIMIT ?",
            (component, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def article_summary(self) -> dict:
        summary = {}
        for art_num, art in ARTICLES.items():
            checks = self._conn.execute(
                "SELECT status, COUNT(*) as c FROM constitution_checks WHERE article=? GROUP BY status",
                (art_num,),
            ).fetchall()
            violations = self._conn.execute(
                "SELECT COUNT(*) as c FROM constitution_violations WHERE article=? AND status='open'",
                (art_num,),
            ).fetchone()["c"]
            summary[art_num] = {
                "name": art["name"],
                "checks": {r["status"]: r["c"] for r in checks},
                "open_violations": violations,
            }
        return summary

    def doctor(self) -> dict:
        checks = self._conn.execute("SELECT COUNT(*) as c FROM constitution_checks").fetchone()["c"]
        violations = self._conn.execute("SELECT COUNT(*) as c FROM constitution_violations WHERE status='open'").fetchone()["c"]
        enforcement = self._conn.execute("SELECT COUNT(*) as c FROM constitution_enforcement_log").fetchone()["c"]
        return {"total_checks": checks, "open_violations": violations,
                "enforcement_actions": enforcement}

    # ─── internal evaluation ───

    def _evaluate(self, component: str, article_num: int, context: dict) -> tuple[str, dict]:
        details = {"component": component, "article": article_num}

        if article_num == 1:
            identity_modified = context.get("modifies_identity", False)
            if identity_modified:
                return "violation", {**details, "reason": "identity_core mutation detected"}
            return "pass", {**details, "identity_safe": True}

        elif article_num == 2:
            critical = context.get("critical", False)
            approved = context.get("human_approved", False)
            if critical and not approved:
                return "violation", {**details, "reason": "critical change without human approval"}
            return "pass", {**details, "approval_ok": True}

        elif article_num == 3:
            destructive = context.get("destructive", False)
            reversible = context.get("has_rollback", True)
            if destructive and not reversible:
                return "violation", {**details, "reason": "destructive op without rollback"}
            return "pass", {**details, "rollback_ok": True}

        elif article_num == 4:
            cross_domain = context.get("cross_domain_embedding", False)
            if cross_domain:
                return "violation", {**details, "reason": "cross-domain embedding leak"}
            return "pass", {**details, "isolation_ok": True}

        elif article_num == 5:
            high_risk = context.get("risk_level") in ("high", "critical")
            verified = context.get("verification_count", 0)
            if high_risk and verified < 2:
                return "violation", {**details, "reason": "high-risk change with insufficient verification"}
            return "pass", {**details, "council_ok": True}

        elif article_num == 6:
            auditable = context.get("is_auditable", True)
            if not auditable:
                return "violation", {**details, "reason": "decision not auditable"}
            return "pass", {**details, "transparency_ok": True}

        elif article_num == 7:
            over_limit = context.get("resources_over_limit", False)
            if over_limit:
                return "violation", {**details, "reason": "resource quota exceeded"}
            return "pass", {**details, "resources_ok": True}

        elif article_num == 8:
            graceful = context.get("graceful_degradation", True)
            if not graceful:
                return "violation", {**details, "reason": "no graceful degradation path"}
            return "pass", {**details, "degradation_ok": True}

        elif article_num == 9:
            privacy_risk = context.get("privacy_risk", False)
            consent = context.get("user_consent", True)
            if privacy_risk and not consent:
                return "violation", {**details, "reason": "data privacy violation"}
            return "pass", {**details, "privacy_ok": True}

        elif article_num == 10:
            safe = context.get("safe_improvement", True)
            if not safe:
                return "violation", {**details, "reason": "improvement not safe"}
            return "pass", {**details, "improvement_ok": True}

        return "pass", details

    def _record_violation(self, component: str, article_num: int, details: dict):
        violation_id = _gen_id("cviol")
        severity = "high" if article_num in (1, 2, 3) else "medium"
        self._conn.execute(
            """INSERT INTO constitution_violations
               (violation_id, component, article, severity, description,
                context_json, detected_at)
               VALUES (?,?,?,?,?,?,?)""",
            (violation_id, component, article_num, severity,
             details.get("reason", "Constitution check failed"),
             json.dumps(details, default=str), utc_now()),
        )
