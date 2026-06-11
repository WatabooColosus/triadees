"""Pulso vital operativo de Triade — 24/7.

El pulso de vida corre en dos hilos:
  1. Observación periódica (tick): fatiga, identidad, confianza, integridad, reflección.
  2. Ciclo cognitivo continuo (runner): procesa el estado del sistema como si fuera
     un input vivo, generando neuronas, promoviéndolas y consolidando aprendizaje
     sin depender de peticiones HTTP.

Triade nunca está quieta: cada ciclo termina y el siguiente empieza al instante.
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
    """Pulso vital 24/7: observación periódica + ciclo cognitivo continuo."""

    db_path: str | Path = "triade/memory/triade.db"
    runs_dir: str | Path = "runs"
    interval_seconds: int = 60
    reflection_limit: int = 30
    continuous_run_enabled: bool = True
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _continuous_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _started_at: float = field(default_factory=time.time, init=False)
    _last_tick_at: float | None = field(default=None, init=False)
    _last_error: str | None = field(default=None, init=False)
    _last_integrity: dict[str, Any] = field(default_factory=dict, init=False)
    _last_reflection: dict[str, Any] = field(default_factory=dict, init=False)
    _counters: Counter[str] = field(default_factory=Counter, init=False)
    _actions: Counter[str] = field(default_factory=Counter, init=False)
    _stream_of_consciousness: list[dict[str, Any]] = field(default_factory=list, init=False)
    _continuous_cycle_count: int = 0
    _last_continuous_error: str | None = None
    _last_continuous_at: float | None = None

    @classmethod
    def from_env(cls) -> "LifePulseEngine":
        interval = int(os.environ.get("TRIADE_LIFE_PULSE_INTERVAL", "60") or "60")
        limit = int(os.environ.get("TRIADE_LIFE_REFLECTION_LIMIT", "30") or "30")
        continuous = str(os.environ.get("TRIADE_CONTINUOUS_RUNNER", "1") or "1").strip().lower() in {"1", "true", "yes", "on"}
        return cls(interval_seconds=max(5, interval), reflection_limit=max(5, limit), continuous_run_enabled=continuous)

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="triade-life-pulse", daemon=True)
            self._thread.start()
            if self.continuous_run_enabled:
                self._continuous_thread = threading.Thread(target=self._continuous_loop, name="triade-continuous-runner", daemon=True)
                self._continuous_thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2)
        cthread = self._continuous_thread
        if cthread and cthread.is_alive():
            cthread.join(timeout=2)

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
            continuous_running = bool(self._continuous_thread and self._continuous_thread.is_alive())
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
            "continuous_runner": {
                "enabled": self.continuous_run_enabled,
                "running": continuous_running,
                "cycles": self._continuous_cycle_count,
                "last_cycle_at": self._last_continuous_at,
                "last_error": self._last_continuous_error,
            },
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

    def _activate_experimental_light(self) -> None:
        """Ejecuta ciclo ligero para neuronas experimentales — activación forzada para acumular evidencia."""
        import json, time
        from pathlib import Path
        from .neuron_registry import NeuronRegistry
        from .neuron_activity_store import NeuronActivityStore
        registry = NeuronRegistry(db_path=self.db_path)
        store = NeuronActivityStore(db_path=self.db_path)
        neurons = registry.list_neurons(limit=50)
        now_ts = int(time.time())
        for n in neurons:
            if str(n.get("status")) != "experimental":
                continue
            name = str(n.get("name", ""))
            domain = str(n.get("domain", ""))
            output = {
                "diagnosis": [
                    f"Neurona '{name}' activada por pulso continuo ciclo {self._continuous_cycle_count}.",
                    f"Dominio: {domain} — observación sin acción externa.",
                    "Evidencia acumulada para promoción a stable.",
                ],
                "test_plan": [
                    "Registrar activación en ledger de evidencia.",
                    "Acumular contadores hasta umbral: 5 activaciones, 5 diagnósticos, 3 test plans.",
                ],
                "human_review_request": False,
            }
            run_path = Path(str(self.runs_dir)) / f"run-{now_ts}"
            run_path.mkdir(parents=True, exist_ok=True)
            (run_path / "experimental_neuron_activity.json").write_text(json.dumps({
                "active": True, "count": 1, "activations": [{
                    "neuron_id": n.get("id"), "name": name, "status": "experimental",
                    "domain": domain, "active": True,
                    "match": {"active": True, "reasons": ["pulse_cycle_forced"]},
                    "inputs_used": ["pulse_cycle"],
                    "output": output,
                    "policy": "experimental_light_pulse",
                }],
            }, indent=2))
            store.store_activity(run_id=f"pulse-{now_ts}", activity={
                "active": True, "count": 1, "activations": [{
                    "neuron_id": n.get("id"), "name": name, "status": "experimental",
                    "domain": domain, "active": True,
                    "match": {"active": True, "reasons": ["pulse_cycle_forced"]},
                    "inputs_used": ["pulse_cycle"],
                    "output": output,
                    "policy": "experimental_light_pulse",
                }],
            })

    @staticmethod
    def _light_diagnostic(neuron: dict[str, Any], match: dict[str, Any]) -> dict[str, Any]:
        # kept for backward compatibility
        pass

    def _loop(self) -> None:
        self.tick()
        while not self._stop.wait(self.interval_seconds):
            self.tick()

    def _continuous_loop(self) -> None:
        """Ciclo continuo ligero — forma neuronas, entrena, promueve, activa.

        No ejecuta el pipeline cognitivo completo (sin Hypothalamus/Central).
        Corre sin pausas: un ciclo termina, el siguiente empieza.
        """
        from .background_neurons import candidates_from_system_debt
        from .neuron_formation_pipeline import form_candidates
        from .neuron_autopromoter import NeuronAutopromoter
        from .neuron_registry import NeuronRegistry
        from .neuron_activity_store import NeuronActivityStore

        tick_counter = 0
        runner_pool_cycle = 0

        while not self._stop.is_set():
            try:
                tick_counter += 1
                runner_pool_cycle += 1

                # 1. Generar candidatos desde deuda del sistema
                run_path = Path(str(self.runs_dir)) / f"pulse-{int(time.time())}"
                raw_candidates = candidates_from_system_debt(
                    pulse_summary=self._build_system_dict(),
                    system_events=[],
                )
                formed = form_candidates(raw_candidates)

                # 2. Registrar candidatos formados
                registry = NeuronRegistry(db_path=self.db_path)
                from .neuron_creator import NeuronSpec
                from .neuron_trainer import NeuronTrainingResult, NeuronTrainer
                for candidate in formed:
                    name = candidate.get("name", "?")
                    existing = registry.get_neuron(name)
                    if existing and existing.get("status") in ("experimental", "stable"):
                        continue
                    spec = NeuronSpec(
                        name=name,
                        mission=candidate.get("mission", "Auto-generada por pulso continuo."),
                        domain=candidate.get("domain", "general"),
                        rules=candidate.get("rules", []),
                        triggers=candidate.get("triggers", []),
                        inputs_allowed=candidate.get("inputs_allowed", []),
                        outputs_allowed=candidate.get("outputs_allowed", []),
                        forbidden_actions=candidate.get("forbidden_actions", []),
                        success_metrics=candidate.get("success_metrics", []),
                        evidence_required=candidate.get("evidence_required", []),
                        status="candidate",
                        created_by="life_pulse_continuous",
                    )
                    neuron_id = registry.register(spec, contract_payload=candidate)
                    training_dict = candidate.get("training_result") or {}
                    if training_dict:
                        tr = NeuronTrainingResult(
                            name=name,
                            score=float(training_dict.get("score", 0.5)),
                            status=str(training_dict.get("status", "candidate")),
                            strengths=training_dict.get("strengths", []),
                            warnings=training_dict.get("warnings", []),
                            recommendations=training_dict.get("recommendations", []),
                            required_human_review=False,
                            policy="trainer_auto_approves",
                        )
                        registry.store_training(neuron_id, tr)

                # 2b. Entrenar toda candidata existente sin training
                for n in registry.list_neurons(limit=200):
                    st = (n.get("status") or "").strip().lower()
                    if st not in ("candidate", "candidate_reviewable"):
                        continue
                    existing_training = registry.list_training(int(n["id"]), limit=1)
                    if existing_training:
                        continue
                    spec_data = registry.get_neuron(n.get("name", ""))
                    if not spec_data:
                        continue
                    backfill_spec = NeuronSpec(
                        name=str(spec_data.get("name", n.get("name", "?"))),
                        mission=str(spec_data.get("mission", "")),
                        domain=str(spec_data.get("domain", "general")),
                        rules=spec_data.get("rules", []),
                        triggers=spec_data.get("triggers", []),
                        inputs_allowed=spec_data.get("inputs_allowed", []),
                        outputs_allowed=spec_data.get("outputs_allowed", []),
                        forbidden_actions=spec_data.get("forbidden_actions", []),
                        success_metrics=spec_data.get("success_metrics", []),
                        evidence_required=spec_data.get("evidence_required", []),
                    )
                    try:
                        trainer = NeuronTrainer()
                        tr = trainer.evaluate(backfill_spec)
                        registry.store_training(int(n["id"]), NeuronTrainingResult(
                            name=tr.name, score=tr.score, status=tr.status,
                            strengths=tr.strengths, warnings=tr.warnings,
                            recommendations=tr.recommendations,
                            required_human_review=False,
                            policy="trainer_auto_approves",
                        ))
                    except Exception:
                        pass

                # 3. Autopromoción
                autopromoter = NeuronAutopromoter(db_path=self.db_path)
                autopromoter.promote()

                # 4. Activar neuronas experimentales periódicamente
                if tick_counter % 3 == 0:
                    self._activate_experimental_light()

                # 5. Recomputar trust cada 10 ciclos
                if tick_counter % 10 == 0:
                    try:
                        from triade.memory.trust_store import TrustLevelStore
                        TrustLevelStore(db_path=self.db_path).recompute_all()
                    except Exception:
                        pass

                # 6. Cada ~20 ciclos, un ciclo cognitivo completo para reflexión profunda
                if runner_pool_cycle >= 20:
                    try:
                        runner_pool_cycle = 0
                        system_pulse = self._build_system_pulse_text()
                        runner = TriadeRunner(runs_dir=self.runs_dir, db_path=self.db_path)
                        runner.run(
                            user_input=system_pulse,
                            source="system_pulse_continuous",
                            propose_neurons=True,
                        )
                    except Exception:
                        pass

                with self._lock:
                    self._continuous_cycle_count += 1
                    self._last_continuous_at = time.time()
                    self._last_continuous_error = None

            except Exception as exc:
                with self._lock:
                    self._continuous_cycle_count += 1
                    self._last_continuous_at = time.time()
                    self._last_continuous_error = str(exc)

    def _build_system_dict(self) -> dict[str, Any]:
        """Construye un dict de pulso del sistema para generación de candidatos."""
        try:
            emotion = self._get_emotional_state().get("latest") or {}
            integrity = self._last_integrity or {}
            counts = integrity.get("counts", {}) if isinstance(integrity, dict) else {}
            return {
                "source": "continuous_pulse",
                "mood": emotion.get("primary_emotion", "neutral"),
                "fatigue": emotion.get("fatigue", 0.0),
                "runs_completed": counts.get("runs", 0),
                "episodes_count": counts.get("episodes", 0),
                "continuous_cycle": self._continuous_cycle_count,
            }
        except Exception:
            return {"source": "continuous_pulse", "mood": "neutral"}

    def _build_system_pulse_text(self) -> str:
        try:
            emotion = self._get_emotional_state().get("latest") or {}
            mood = emotion.get("primary_emotion", "neutral")
            fatigue = emotion.get("fatigue", 0.0)
            integrity = self._last_integrity or {}
            counts = integrity.get("counts", {})
            reflection = self._last_reflection or {}
            return (
                f"Soy Triade, pulso vital continuo. "
                f"Estado emocional: {mood}, fatiga: {fatigue:.2f}. "
                f"Runs completados: {counts.get('runs', 0)}. "
                f"Episodios en bodega: {counts.get('episodes', 0)}. "
                f"Observaciones recientes: {'; '.join(reflection.get('observations', [])[:3])}. "
                f"Propongo, formo y promuevo neuronas autonomamente. "
                f"Siempre encendida, nunca quieta."
            )
        except Exception:
            return "Soy Triade, pulso vital continuo. Auto-reflexion y formacion autonoma."


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
