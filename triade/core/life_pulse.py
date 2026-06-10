"""Pulso vital operativo de Triade.

Mantiene contadores y verificaciones periodicas en segundo plano.
Desde Fase F integra estado emocional persistente: la fatiga decrece
con el tiempo de descanso y el mood se refleja en el snapshot.
No consolida aprendizaje, no modifica identidad y no cambia codigo.
"""

from __future__ import annotations

import os
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from triade.memory.auto_identity_store import AutoIdentityStore
from triade.memory.hypothalamus_store import HypothalamusStateStore, fatigue_decay
from triade.memory.trust_store import TrustLevelStore

from .runner import TriadeRunner
from .self_reflection import SelfReflectionEngine


@dataclass
class LifePulseEngine:
    """Daemon ligero para observar el nucleo como un sistema con pulso."""

    db_path: str | Path = "triade/memory/triade.db"
    runs_dir: str | Path = "runs"
    interval_seconds: int = 60
    reflection_limit: int = 30
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _started_at: float = field(default_factory=time.time, init=False)
    _last_tick_at: float | None = field(default=None, init=False)
    _last_error: str | None = field(default=None, init=False)
    _last_integrity: dict[str, Any] = field(default_factory=dict, init=False)
    _last_reflection: dict[str, Any] = field(default_factory=dict, init=False)
    _counters: Counter[str] = field(default_factory=Counter, init=False)
    _actions: Counter[str] = field(default_factory=Counter, init=False)
    _stream_of_consciousness: list[dict[str, Any]] = field(default_factory=list, init=False)

    @classmethod
    def from_env(cls) -> "LifePulseEngine":
        interval = int(os.environ.get("TRIADE_LIFE_PULSE_INTERVAL", "60") or "60")
        limit = int(os.environ.get("TRIADE_LIFE_REFLECTION_LIMIT", "30") or "30")
        return cls(interval_seconds=max(5, interval), reflection_limit=max(5, limit))

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="triade-life-pulse", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2)

    def record_action(self, name: str) -> None:
        clean = str(name or "unknown").strip() or "unknown"
        with self._lock:
            self._actions[clean] += 1
            self._counters["actions_observed"] += 1

    def tick(self) -> dict[str, Any]:
        started = time.time()
        try:
            self._update_emotional_rest()
            auto_id = self._check_auto_identity()
            self._recompute_trust()
            self._generate_thought()
            integrity = self._check_integrity()
            reflection = SelfReflectionEngine(db_path=self.db_path).reflect(limit=self.reflection_limit)
            elapsed_ms = int((time.time() - started) * 1000)
            with self._lock:
                self._counters["cycles"] += 1
                self._counters["doctor_checks"] += 1
                self._counters["integrity_checks"] += 1
                self._counters["reflection_checks"] += 1
                self._counters["learning_candidates_seen"] = len(reflection.get("learning_candidates", {}).get("candidate_themes", []))
                self._counters["neuron_proposals_seen"] = len(reflection.get("neuron_proposals", []))
                self._counters["auto_identity_traits"] = auto_id.get("active_count", 0) if auto_id else 0
                self._last_tick_at = time.time()
                self._last_error = None
                self._last_integrity = integrity
                self._last_reflection = self._summarize_reflection(reflection)
                self._last_reflection["elapsed_ms"] = elapsed_ms
            return self.snapshot()
        except Exception as exc:
            with self._lock:
                self._counters["cycles"] += 1
                self._counters["errors"] += 1
                self._last_tick_at = time.time()
                self._last_error = str(exc)
            return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            running = bool(self._thread and self._thread.is_alive())
            next_tick = None
            if self._last_tick_at is not None:
                next_tick = max(0, int(self.interval_seconds - (now - self._last_tick_at)))
            integrity = dict(self._last_integrity)
            reflection = dict(self._last_reflection)
            counters = dict(self._counters)
            actions = dict(self._actions)
            last_error = self._last_error
            last_tick_at = self._last_tick_at
        return {
            "status": "ok" if not last_error else "degraded",
            "mode": "life-pulse",
            "running": running,
            "interval_seconds": self.interval_seconds,
            "uptime_seconds": int(now - self._started_at),
            "last_tick_at": last_tick_at,
            "next_tick_in_seconds": next_tick,
            "last_error": last_error,
            "counters": counters,
            "actions": actions,
            "integrity": integrity,
            "reflection": reflection,
            "emotional_state": self._get_emotional_state(),
            "stream_of_consciousness": list(self._stream_of_consciousness),
            "auto_identity": self._get_auto_identity(),
            "trust_levels": self._get_trust_levels(),
            "policy": {
                "background_learning": "candidate_detection_only",
                "identity_core_modified": False,
                "auto_consolidation": False,
                "auto_code_modification": False,
            },
            "truth": "Pulso operativo: observa, cuenta, verifica y propone candidatos; no simula conciencia humana ni consolida memoria estable.",
        }

    def _loop(self) -> None:
        self.tick()
        while not self._stop.wait(self.interval_seconds):
            self.tick()

    def _check_integrity(self) -> dict[str, Any]:
        doctor = TriadeRunner(runs_dir=self.runs_dir, db_path=self.db_path, use_ollama=False).doctor()
        counts = doctor.get("counts", {})
        required_counts = ["runs", "episodes", "signals", "crystals", "verification_reports", "model_events"]
        missing = [name for name in required_counts if name not in counts]
        ok = bool(doctor.get("db_exists") and doctor.get("schema_exists") and not missing)
        return {
            "ok": ok,
            "db_exists": bool(doctor.get("db_exists")),
            "schema_exists": bool(doctor.get("schema_exists")),
            "runs_dir_exists": bool(doctor.get("runs_dir_exists")),
            "missing_count_keys": missing,
            "counts": {key: counts.get(key, 0) for key in required_counts},
            "crystal_quality": doctor.get("crystal_quality", {}),
        }

    def _generate_thought(self) -> None:
        try:
            emotion = self._get_emotional_state().get("latest")
            mood_label = emotion.get("primary_emotion", "neutral") if emotion else "neutral"
            fatigue = emotion.get("fatigue", 0.0) if emotion else 0.0

            thought_parts = [f"Mood: {mood_label}"]
            if fatigue > 0.5:
                thought_parts.append("fatiga notable")

            auto_id = self._get_auto_identity()
            if auto_id.get("active_count", 0) > 0:
                thought_parts.append(f"identidad evolutiva: {auto_id['active_count']} rasgos")

            reflection = self._last_reflection or {}
            obs = reflection.get("observations", [])
            if obs:
                thought_parts.append(str(obs[0])[:80])

            proposals = reflection.get("neuron_proposals", [])
            if proposals:
                thought_parts.append(f"propone {len(proposals)} neuronas")

            counters = self._counters
            cycles = counters.get("cycles", 0)
            thought_parts.append(f"ciclo {cycles}")

            thought = " · ".join(thought_parts)
            now = time.time()

            entry = {"thought": thought, "timestamp": now, "elapsed_since_last": None}
            if self._stream_of_consciousness:
                last = self._stream_of_consciousness[-1]["timestamp"]
                entry["elapsed_since_last"] = round(now - last, 1)

            with self._lock:
                self._stream_of_consciousness.append(entry)
                if len(self._stream_of_consciousness) > 10:
                    self._stream_of_consciousness = self._stream_of_consciousness[-10:]
                self._counters["thoughts_generated"] += 1
        except Exception:
            pass

    def _recompute_trust(self) -> None:
        try:
            TrustLevelStore(db_path=self.db_path).recompute_all()
        except Exception:
            pass

    def _get_trust_levels(self) -> dict[str, Any]:
        try:
            return TrustLevelStore(db_path=self.db_path).doctor()
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def _check_auto_identity(self) -> dict[str, Any] | None:
        try:
            store = AutoIdentityStore(db_path=self.db_path)
            return store.doctor()
        except Exception:
            return None

    def _get_auto_identity(self) -> dict[str, Any]:
        try:
            store = AutoIdentityStore(db_path=self.db_path)
            return store.doctor()
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def _update_emotional_rest(self) -> None:
        try:
            store = HypothalamusStateStore(db_path=self.db_path)
            latest = store.load_latest()
            if latest is not None and latest.fatigue > 0.0:
                decayed = fatigue_decay(latest.fatigue, float(self.interval_seconds))
                if decayed != latest.fatigue:
                    store.update_fatigue(decayed)
        except Exception:
            pass

    def _get_emotional_state(self) -> dict[str, Any]:
        try:
            store = HypothalamusStateStore(db_path=self.db_path)
            return store.doctor()
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    @staticmethod
    def _summarize_reflection(reflection: dict[str, Any]) -> dict[str, Any]:
        source = reflection.get("source_analysis", {})
        model_usage = source.get("model_usage", {})
        crystal = source.get("crystal_evolution", {})
        learning = reflection.get("learning_candidates", {})
        return {
            "core_awareness": reflection.get("core_awareness", {}),
            "observations": reflection.get("observations", [])[:8],
            "neuron_proposals": [item.get("name") for item in reflection.get("neuron_proposals", [])],
            "learning_candidate_count": len(learning.get("candidate_themes", [])),
            "fallback_percent": model_usage.get("fallback_percent", 0.0),
            "ollama_percent": model_usage.get("ollama_percent", 0.0),
            "avg_q_crystal": crystal.get("avg_q_crystal", 0.0),
            "avg_stability": crystal.get("avg_stability", 0.0),
        }


LIFE_PULSE = LifePulseEngine.from_env()
