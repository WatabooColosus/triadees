"""Niveles de confianza para auto-consolidación gradual (Fase F-05).

TrustLevelStore mantiene un nivel numérico [0.0, 1.0] por dominio.
El trust se gana con evidencia: reward alto, verificación exitosa,
baja tasa de error. Cada dominio permite distintas operaciones
según su nivel actual.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TRUST_DOMAINS = ["consolidation", "code_modification", "identity_evolution"]

PERMISSION_THRESHOLDS: dict[str, dict[str, float]] = {
    "consolidation": {
        "auto_consolidate_low_risk": 0.25,
        "auto_consolidate_medium_risk": 0.50,
        "auto_promote_semantic_candidates": 0.40,
        "auto_promote_neurons": 0.65,
        "auto_consolidate_high_risk": 0.80,
    },
    "code_modification": {
        "auto_code_modify_low_risk": 0.70,
        "auto_code_modify_medium_risk": 0.85,
        "auto_code_modify_high_risk": 0.95,
    },
    "identity_evolution": {
        "auto_add_evolved_traits": 0.50,
        "auto_promote_identity_traits": 0.75,
    },
}


def new_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class TrustLevelStore:
    """Niveles de confianza ganados por Tríade en cada dominio."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.schema_path = Path(__file__).resolve().parent / "schemas.sql"
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        if not self.schema_path.exists():
            raise FileNotFoundError(f"No existe el esquema de memoria: {self.schema_path}")
        with self._connect() as conn:
            conn.executescript(self.schema_path.read_text(encoding="utf-8"))

    def get_trust(self, domain: str) -> float:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT trust_level FROM trust_levels WHERE domain = ?", (domain,)
            ).fetchone()
            return float(row["trust_level"]) if row else 0.0

    def get_permissions(self, domain: str) -> dict[str, bool]:
        trust = self.get_trust(domain)
        thresholds = PERMISSION_THRESHOLDS.get(domain, {})
        return {perm: trust >= thr for perm, thr in thresholds.items()}

    def recompute_all(self) -> dict[str, float]:
        levels: dict[str, float] = {}
        for domain in TRUST_DOMAINS:
            levels[domain] = self._recompute(domain)
        return levels

    def _recompute(self, domain: str) -> float:
        now = new_utc()
        with self._connect() as conn:
            run_count = conn.execute("SELECT COUNT(*) AS c FROM runs").fetchone()["c"] or 0
            if run_count == 0:
                return 0.0

            rew_row = conn.execute(
                "SELECT COALESCE(AVG(reward), 0.0) AS ar FROM reinforcement_log"
            ).fetchone()
            avg_reward = float(rew_row["ar"]) if rew_row else 0.0

            ok_row = conn.execute(
                "SELECT COUNT(*) AS c FROM verification_reports WHERE status = 'ok'"
            ).fetchone()
            total_row = conn.execute(
                "SELECT COUNT(*) AS c FROM verification_reports"
            ).fetchone()
            total_v = int(total_row["c"]) if total_row else 0
            ok_v = int(ok_row["c"]) if ok_row else 0
            verif_ok_rate = ok_v / total_v if total_v > 0 else 0.0

            err_row = conn.execute(
                "SELECT COUNT(*) AS c FROM model_events WHERE ok = 0"
            ).fetchone()
            total_m_row = conn.execute(
                "SELECT COUNT(*) AS c FROM model_events"
            ).fetchone()
            total_m = int(total_m_row["c"]) if total_m_row else 0
            err_m = int(err_row["c"]) if err_row else 0
            error_rate = err_m / total_m if total_m > 0 else 0.0

            # Weighted formula: reward (40%) + verif pass (30%) + (1 - error) (20%) + run_count scaled (10%)
            reward_score = max(0.0, min(1.0, avg_reward))
            error_score = 1.0 - min(1.0, error_rate)
            run_score = min(1.0, run_count / 500.0)
            trust = 0.40 * reward_score + 0.30 * verif_ok_rate + 0.20 * error_score + 0.10 * run_score
            trust = round(max(0.0, min(1.0, trust)), 4)

            conn.execute(
                """INSERT OR REPLACE INTO trust_levels
                (domain, trust_level, criteria_avg_reward, criteria_verification_pass_rate,
                 criteria_error_rate, criteria_run_count, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (domain, trust, round(avg_reward, 4), round(verif_ok_rate, 4),
                 round(error_rate, 4), run_count, now),
            )
            return trust

    def doctor(self) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT domain, trust_level, criteria_avg_reward, criteria_verification_pass_rate, "
                "criteria_error_rate, criteria_run_count, last_updated FROM trust_levels ORDER BY domain"
            ).fetchall()
        domains = {}
        for row in rows:
            d = row["domain"]
            domains[d] = {
                "trust_level": float(row["trust_level"]),
                "criteria": {
                    "avg_reward": float(row["criteria_avg_reward"]),
                    "verification_pass_rate": float(row["criteria_verification_pass_rate"]),
                    "error_rate": float(row["criteria_error_rate"]),
                    "run_count": int(row["criteria_run_count"]),
                },
                "permissions": self.get_permissions(d),
            }
        return {"status": "ok", "domains": domains}
