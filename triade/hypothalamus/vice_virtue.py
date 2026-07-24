"""ViceVirtueState — 14 dimensiones independientes: 7 virtudes y 7 pecados.

Cada virtue y cada sin tiene estado independiente (NO sin = 1 - virtue).
Serialización: pecados guardados con nombres de pecados.
Decaimiento temporal configurable por dimensión.
Tensiones entre virtudes y entre pecados.
Persistencia SQLite con historial por run.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from triade.core.contracts import utc_now

VIRTUE_NAMES: tuple[str, ...] = (
    "humildad", "generosidad", "respeto", "paciencia",
    "templanza", "caridad", "diligencia",
)

SIN_NAMES: tuple[str, ...] = (
    "orgullo", "avaricia", "desprecio", "impaciencia",
    "exceso", "indiferencia", "pereza",
)

ALL_DIMENSIONS: tuple[str, ...] = VIRTUE_NAMES + SIN_NAMES

VIRTUE_SIN_MAP: dict[str, str] = {
    "humildad": "orgullo",
    "generosidad": "avaricia",
    "respeto": "desprecio",
    "paciencia": "impaciencia",
    "templanza": "exceso",
    "caridad": "indiferencia",
    "diligencia": "pereza",
}

SIN_VIRTUE_MAP: dict[str, str] = {v: k for k, v in VIRTUE_SIN_MAP.items()}

TENSION_PAIRS: dict[tuple[str, str], float] = {
    ("humildad", "diligencia"): 0.6,
    ("paciencia", "generosidad"): 0.5,
    ("templanza", "diligencia"): 0.7,
    ("respeto", "caridad"): 0.4,
    ("paciencia", "respeto"): 0.3,
    ("humildad", "templanza"): 0.3,
    ("generosidad", "diligencia"): 0.4,
    ("orgullo", "humildad"): 0.8,
    ("avaricia", "generosidad"): 0.8,
    ("pereza", "diligencia"): 0.8,
    ("impaciencia", "paciencia"): 0.7,
}

DEFAULT_DECAY_RATES: dict[str, float] = {d: 0.01 for d in ALL_DIMENSIONS}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS vice_virtue_state (
    state_id       TEXT PRIMARY KEY,
    run_id         TEXT NOT NULL,
    dimensions_json TEXT NOT NULL,
    decay_config_json TEXT DEFAULT '{}',
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS vvs_run ON vice_virtue_state(run_id);
CREATE TABLE IF NOT EXISTS vice_virtue_history (
    history_id     TEXT PRIMARY KEY,
    state_id       TEXT NOT NULL,
    dimensions_json TEXT NOT NULL,
    trigger_event  TEXT DEFAULT '',
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS vvh_state ON vice_virtue_history(state_id);
"""


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _gen_id(prefix: str) -> str:
    import hashlib
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{hashlib.md5(str(datetime.now(timezone.utc).timestamp()).encode()).hexdigest()[:6]}"


@dataclass
class ViceVirtueState:
    """14 dimensiones independientes con persistencia, decaimiento y tensiones."""

    _virtues: dict[str, float] = field(default_factory=dict)
    _sins: dict[str, float] = field(default_factory=dict)
    _decay_rates: dict[str, float] = field(default_factory=dict)
    _state_id: str = ""
    _run_id: str = ""
    _created_at: str = ""
    _conn: sqlite3.Connection | None = field(default=None, repr=False)

    def __post_init__(self):
        if not self._virtues:
            self._virtues = {v: 0.5 for v in VIRTUE_NAMES}
        if not self._sins:
            self._sins = {s: 0.5 for s in SIN_NAMES}
        if not self._decay_rates:
            self._decay_rates = dict(DEFAULT_DECAY_RATES)

    @classmethod
    def from_dict(cls, d: dict[str, float] | None = None) -> ViceVirtueState:
        virtues = {v: 0.5 for v in VIRTUE_NAMES}
        sins = {s: 0.5 for s in SIN_NAMES}
        if d:
            for k, v in d.items():
                if k in VIRTUE_NAMES:
                    try:
                        virtues[k] = _clamp(float(v))
                    except (TypeError, ValueError):
                        pass
                elif k in SIN_NAMES:
                    try:
                        sins[k] = _clamp(float(v))
                    except (TypeError, ValueError):
                        pass
        return cls(_virtues=virtues, _sins=sins)

    @classmethod
    def default(cls) -> ViceVirtueState:
        return cls.from_dict(None)

    # --- Virtue access ---

    def virtue(self, name: str) -> float:
        return self._virtues.get(name, 0.5)

    def set_virtue(self, name: str, value: float) -> None:
        if name in VIRTUE_NAMES:
            self._virtues[name] = _clamp(value)

    # --- Sin access (INDEPENDENT from virtue) ---

    def sin(self, name: str) -> float:
        if name in SIN_NAMES:
            return self._sins.get(name, 0.5)
        return 0.5

    def set_sin(self, name: str, value: float) -> None:
        if name in SIN_NAMES:
            self._sins[name] = _clamp(value)

    def sin_for_virtue(self, virtue_name: str) -> float:
        """Get sin value for a virtue's opposite. Independent tracking."""
        sin_name = VIRTUE_SIN_MAP.get(virtue_name, "")
        return self.sin(sin_name) if sin_name else 0.5

    # --- Properties ---

    @property
    def humildad(self) -> float:
        return self.virtue("humildad")

    @property
    def generosidad(self) -> float:
        return self.virtue("generosidad")

    @property
    def respeto(self) -> float:
        return self.virtue("respeto")

    @property
    def paciencia(self) -> float:
        return self.virtue("paciencia")

    @property
    def templanza(self) -> float:
        return self.virtue("templanza")

    @property
    def caridad(self) -> float:
        return self.virtue("caridad")

    @property
    def diligencia(self) -> float:
        return self.virtue("diligencia")

    @property
    def orgullo(self) -> float:
        return self.sin("orgullo")

    @property
    def avaricia(self) -> float:
        return self.sin("avaricia")

    @property
    def desprecio(self) -> float:
        return self.sin("desprecio")

    @property
    def impaciencia(self) -> float:
        return self.sin("impaciencia")

    @property
    def exceso(self) -> float:
        return self.sin("exceso")

    @property
    def indiferencia(self) -> float:
        return self.sin("indiferencia")

    @property
    def pereza(self) -> float:
        return self.sin("pereza")

    # --- Tensions ---

    def tension(self, dim_a: str, dim_b: str) -> float:
        a = self._virtues.get(dim_a, self._sins.get(dim_a, 0.5))
        b = self._virtues.get(dim_b, self._sins.get(dim_b, 0.5))
        diff = abs(a - b)
        avg = (a + b) / 2.0
        return round(_clamp(diff * (0.5 + avg * 0.5)), 4)

    def tension_pair(self, pair: tuple[str, str]) -> float:
        base = self.tension(pair[0], pair[1])
        max_factor = TENSION_PAIRS.get(pair, 0.5)
        return round(base * max_factor, 4)

    def all_tensions(self, threshold: float = 0.1) -> dict[str, float]:
        result: dict[str, float] = {}
        for (a, b) in TENSION_PAIRS:
            t = self.tension_pair((a, b))
            if t >= threshold:
                result[f"{a}_vs_{b}"] = t
        return result

    @property
    def dominant_sin(self) -> tuple[str, float]:
        items = [(name, self.sin(name)) for name in SIN_NAMES]
        return max(items, key=lambda x: x[1])

    @property
    def dominant_virtue(self) -> tuple[str, float]:
        items = [(name, self.virtue(name)) for name in VIRTUE_NAMES]
        return max(items, key=lambda x: x[1])

    @property
    def overall_virtue_score(self) -> float:
        vals = [self.virtue(v) for v in VIRTUE_NAMES]
        return round(sum(vals) / max(len(vals), 1), 4)

    @property
    def overall_sin_score(self) -> float:
        vals = [self.sin(s) for s in SIN_NAMES]
        return round(sum(vals) / max(len(vals), 1), 4)

    # --- Temporal decay (configurable per dimension) ---

    def decay(self, seconds: float = 60.0, rate: float | None = None) -> None:
        minutes = seconds / 60.0
        if rate is not None:
            for name in ALL_DIMENSIONS:
                amount = rate * minutes
                current = self._virtues.get(name, self._sins.get(name, 0.5))
                if current > 0.5:
                    new_val = _clamp(current - amount)
                elif current < 0.5:
                    new_val = _clamp(current + amount)
                else:
                    new_val = current
                if name in self._virtues:
                    self._virtues[name] = new_val
                elif name in self._sins:
                    self._sins[name] = new_val
            return
        for name in ALL_DIMENSIONS:
            rate = self._decay_rates.get(name, 0.01)
            amount = rate * minutes
            current = self._virtues.get(name, self._sins.get(name, 0.5))
            if current > 0.5:
                new_val = _clamp(current - amount)
            elif current < 0.5:
                new_val = _clamp(current + amount)
            else:
                new_val = current
            if name in self._virtues:
                self._virtues[name] = new_val
            elif name in self._sins:
                self._sins[name] = new_val

    def set_decay_rate(self, dimension: str, rate: float) -> None:
        if dimension in ALL_DIMENSIONS:
            self._decay_rates[dimension] = max(0.0, rate)

    # --- Serialization (sins with sin names) ---

    def to_dict(self) -> dict[str, float]:
        result = {}
        for v in VIRTUE_NAMES:
            result[v] = self._virtues.get(v, 0.5)
        for s in SIN_NAMES:
            result[s] = self._sins.get(s, 0.5)
        return result

    def to_full_dict(self) -> dict[str, Any]:
        return {
            "virtues": {v: self._virtues.get(v, 0.5) for v in VIRTUE_NAMES},
            "sins": {s: self._sins.get(s, 0.5) for s in SIN_NAMES},
            "tensions": self.all_tensions(threshold=0.05),
            "dominant_virtue": {"name": self.dominant_virtue[0], "value": self.dominant_virtue[1]},
            "dominant_sin": {"name": self.dominant_sin[0], "value": self.dominant_sin[1]},
            "overall_virtue_score": self.overall_virtue_score,
            "overall_sin_score": self.overall_sin_score,
            "decay_rates": dict(self._decay_rates),
        }

    def to_virtues_dict(self) -> dict[str, float]:
        return {v: self._virtues.get(v, 0.5) for v in VIRTUE_NAMES}

    def to_sins_dict(self) -> dict[str, float]:
        return {s: self._sins.get(s, 0.5) for s in SIN_NAMES}

    # --- Persistence ---

    def save(self, run_id: str = "") -> str:
        if not self._conn:
            return ""
        state_id = self._state_id or _gen_id("vvs")
        now = utc_now()
        dims = self.to_dict()
        self._conn.execute(
            """INSERT OR REPLACE INTO vice_virtue_state
               (state_id, run_id, dimensions_json, decay_config_json, created_at)
               VALUES (?,?,?,?,?)""",
            (state_id, run_id or self._run_id, json.dumps(dims, default=str),
             json.dumps(self._decay_rates, default=str), now),
        )
        self._conn.commit()
        self._state_id = state_id
        self._run_id = run_id or self._run_id
        self._created_at = now
        return state_id

    def save_snapshot(self, trigger_event: str = "") -> str:
        if not self._conn or not self._state_id:
            return ""
        history_id = _gen_id("vvsh")
        now = utc_now()
        self._conn.execute(
            """INSERT INTO vice_virtue_history
               (history_id, state_id, dimensions_json, trigger_event, created_at)
               VALUES (?,?,?,?,?)""",
            (history_id, self._state_id, json.dumps(self.to_dict(), default=str),
             trigger_event, now),
        )
        self._conn.commit()
        return history_id

    @classmethod
    def load(cls, state_id: str, conn: sqlite3.Connection) -> ViceVirtueState | None:
        row = conn.execute(
            "SELECT * FROM vice_virtue_state WHERE state_id=?", (state_id,)
        ).fetchone()
        if not row:
            return None
        dims = json.loads(row["dimensions_json"])
        decay = json.loads(row["decay_config_json"]) if row["decay_config_json"] else {}
        virtues = {v: dims.get(v, 0.5) for v in VIRTUE_NAMES}
        sins = {s: dims.get(s, 0.5) for s in SIN_NAMES}
        return cls(
            _virtues=virtues, _sins=sins, _decay_rates=decay or dict(DEFAULT_DECAY_RATES),
            _state_id=row["state_id"], _run_id=row["run_id"],
            _created_at=row["created_at"], _conn=conn,
        )

    def get_history(self, limit: int = 50) -> list[dict]:
        if not self._conn or not self._state_id:
            return []
        rows = self._conn.execute(
            "SELECT * FROM vice_virtue_history WHERE state_id=? ORDER BY created_at DESC LIMIT ?",
            (self._state_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def init_db(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)

    # --- Dict-like interface ---

    def __getitem__(self, key: str) -> float:
        if key in VIRTUE_NAMES:
            return self.virtue(key)
        elif key in SIN_NAMES:
            return self.sin(key)
        return 0.5

    def __setitem__(self, key: str, value: float) -> None:
        if key in VIRTUE_NAMES:
            self.set_virtue(key, value)
        elif key in SIN_NAMES:
            self.set_sin(key, value)

    def __contains__(self, key: str) -> bool:
        return key in ALL_DIMENSIONS

    def __len__(self) -> int:
        return len(ALL_DIMENSIONS)

    def __iter__(self):
        return iter(ALL_DIMENSIONS)

    def get(self, key: str, default: float = 0.5) -> float:
        if key in VIRTUE_NAMES:
            return self.virtue(key)
        elif key in SIN_NAMES:
            return self.sin(key)
        return default
