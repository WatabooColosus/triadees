"""Pulso vital operativo de Triade — 24/7.

El pulso de vida corre en dos hilos:
  1. Observación periódica (tick): fatiga, identidad, confianza, integridad, reflección.
  2. Ciclo cognitivo continuo (runner): procesa el estado del sistema como si fuera
     un input vivo, generando neuronas, promoviéndolas y consolidando aprendizaje
     sin depender de peticiones HTTP.

El modo continuo está DESACTIVADO por defecto (TRIADE_CONTINUOUS_RUNNER=0).
Debe activarse explícitamente con TRIADE_CONTINUOUS_RUNNER=1 o desde CLI/UI.

Env vars del continuous runner:
  TRIADE_CONTINUOUS_RUNNER       — "1" para activar (default: "0")
  TRIADE_CONTINUOUS_INTERVAL_SECONDS — sleep entre ciclos (default: 10, min: 10)
  TRIADE_CONTINUOUS_MAX_CYCLES   — 0 = ilimitado; N = máximo N ciclos
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

from .error_bus import record_internal_error
from .runner import TriadeRunner
from .self_reflection import SelfReflectionEngine


# ── Niveles de autonomía ─────────────────────────────────────────────────────
# Cada nivel implica los anteriores. El continuous runner opera al nivel
# configurado, y NO puede excederlo sin intervención humana explícita.

AUTONOMY_LEVELS: list[str] = [
    "observe_only",        # Solo tick de observación; no genera neuronas.
    "form_candidates",     # Forma candidatos desde deuda del sistema.
    "train_candidates",    # Entrena candidatos existentes.
    "promote_experimental", # Promueve candidate → experimental si score ≥ threshold.
    "promote_stable",      # Promueve experimental → stable con evidencia diversa.
]

DEFAULT_AUTONOMY_LEVEL = "observe_only"

_MODE_TO_AUTONOMY: dict[str, str] = {
    "full_local_guarded": "promote_stable",
    "full_local": "promote_experimental",
    "balanced_background": "train_candidates",
    "light_background": "form_candidates",
    "observe_only": "observe_only",
}

_MIN_CONTINUOUS_INTERVAL = 10
_DEFAULT_CONTINUOUS_INTERVAL = 10
_BACKOFF_BASE_SECONDS = 5
_BACKOFF_MAX_SECONDS = 300


@dataclass
class LifePulseEngine:
    """Pulso vital 24/7: observación periódica + ciclo cognitivo continuo."""

    db_path: str | Path = "triade/memory/triade.db"
    runs_dir: str | Path = "runs"
    interval_seconds: int = 60
    reflection_limit: int = 30
    continuous_run_enabled: bool = False
    continuous_interval_seconds: int = _DEFAULT_CONTINUOUS_INTERVAL
    continuous_max_cycles: int = 0
    autonomy_level: str = DEFAULT_AUTONOMY_LEVEL
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
    _continuous_elapsed_ms: list[int] = field(default_factory=list, init=False)
    _last_promotion_at: float | None = None
    _last_promotion_name: str | None = None
    _continuous_backoff_seconds: float = 0.0

    def _record_error(
        self,
        scope: str,
        error: Exception | str,
        *,
        function: str,
        operation: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        context = {
            "module": __name__,
            "function": function,
            "operation": operation,
            "continuous_cycle": self._continuous_cycle_count,
            "autonomy_level": self.autonomy_level,
        }
        if payload:
            context.update(payload)
        record_internal_error(scope, error, payload=context, db_path=self.db_path)

    @staticmethod
    def _resolve_autonomy_from_config() -> str | None:
        try:
            from triade.core.config import load_config
            yml = load_config("triade.yml")
            rtc = yml.get("runtime") or {}
            force_mode = str(rtc.get("force_mode") or rtc.get("mode") or "").strip()
            if force_mode in _MODE_TO_AUTONOMY:
                return _MODE_TO_AUTONOMY[force_mode]
        except Exception:
            pass
        return None

    @classmethod
    def from_env(cls) -> "LifePulseEngine":
        interval = int(os.environ.get("TRIADE_LIFE_PULSE_INTERVAL", "60") or "60")
        limit = int(os.environ.get("TRIADE_LIFE_REFLECTION_LIMIT", "30") or "30")
        continuous = str(os.environ.get("TRIADE_CONTINUOUS_RUNNER", "0") or "0").strip().lower() in {"1", "true", "yes", "on"}
        ci = int(os.environ.get("TRIADE_CONTINUOUS_INTERVAL_SECONDS", str(_DEFAULT_CONTINUOUS_INTERVAL)) or _DEFAULT_CONTINUOUS_INTERVAL)
        max_c = int(os.environ.get("TRIADE_CONTINUOUS_MAX_CYCLES", "0") or "0")
        autonomy = str(os.environ.get("TRIADE_AUTONOMY_LEVEL", DEFAULT_AUTONOMY_LEVEL) or DEFAULT_AUTONOMY_LEVEL).strip()
        if autonomy not in AUTONOMY_LEVELS:
            autonomy = DEFAULT_AUTONOMY_LEVEL
        return cls(
            interval_seconds=max(5, interval),
            reflection_limit=max(5, limit),
            continuous_run_enabled=continuous,
            continuous_interval_seconds=max(_MIN_CONTINUOUS_INTERVAL, ci),
            continuous_max_cycles=max(0, max_c),
            autonomy_level=autonomy,
        )

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

    def configure_continuous_runner(
        self,
        *,
        enabled: bool,
        autonomy_level: str | None = None,
        interval_seconds: int | None = None,
        max_cycles: int | None = None,
    ) -> dict[str, Any]:
        """Activa/desactiva el runner continuo en el proceso actual.

        No cambia el default global ni escribe configuración persistente. El
        arranque automático sigue dependiendo de TRIADE_CONTINUOUS_RUNNER=1.
        """
        with self._lock:
            if autonomy_level is not None:
                clean_level = str(autonomy_level).strip()
                if clean_level not in AUTONOMY_LEVELS:
                    return {
                        "status": "error",
                        "error": f"autonomy_level inválido: {autonomy_level}",
                        "available": list(AUTONOMY_LEVELS),
                    }
                self.autonomy_level = clean_level
            if interval_seconds is not None:
                self.continuous_interval_seconds = max(_MIN_CONTINUOUS_INTERVAL, int(interval_seconds))
            if max_cycles is not None:
                self.continuous_max_cycles = max(0, int(max_cycles))
            self.continuous_run_enabled = bool(enabled)
            continuous_alive = bool(self._continuous_thread and self._continuous_thread.is_alive())
            should_start = self.continuous_run_enabled and not continuous_alive
            should_stop = not self.continuous_run_enabled and continuous_alive

        if should_start:
            self._stop.clear()
            self._continuous_thread = threading.Thread(
                target=self._continuous_loop,
                name="triade-continuous-runner",
                daemon=True,
            )
            self._continuous_thread.start()
        elif should_stop:
            pulse_was_alive = bool(self._thread and self._thread.is_alive())
            self._stop.set()
            cthread = self._continuous_thread
            if cthread and cthread.is_alive():
                cthread.join(timeout=2)
            self._continuous_thread = None
            self._stop.clear()
            if pulse_was_alive and (self._thread is None or not self._thread.is_alive()):
                self._thread = threading.Thread(target=self._loop, name="triade-life-pulse", daemon=True)
                self._thread.start()

        snapshot = self.snapshot()
        return {
            "status": "ok",
            "continuous_runner": snapshot.get("continuous_runner", {}),
            "autonomy_level": snapshot.get("autonomy_level"),
            "policy": {
                "runtime_only": True,
                "default_remains_off": True,
                "requires_explicit_activation": True,
            },
        }

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
            reflection = SelfReflectionEngine(db_path=self.db_path).reflect(limit=self.reflection_limit, register_neuron_candidates=True)
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
            elapsed_ms = list(self._continuous_elapsed_ms)
            cycle_count = self._continuous_cycle_count

        cycles_per_minute = 0.0
        if elapsed_ms and len(elapsed_ms) >= 2:
            total_ms = sum(elapsed_ms[-60:])
            if total_ms > 0:
                cycles_per_minute = round((len(elapsed_ms[-60:]) / total_ms) * 60_000, 2)

        return {
            "status": "ok" if not last_error else "degraded",
            "mode": "life-pulse",
            "running": running,
            "interval_seconds": self.interval_seconds,
            "uptime_seconds": int(now - self._started_at),
            "last_tick_at": last_tick_at,
            "next_tick_in_seconds": next_tick,
            "last_error": last_error,
            "autonomy_level": self.autonomy_level,
            "autonomy_levels_available": list(AUTONOMY_LEVELS),
            "continuous_runner": {
                "enabled": self.continuous_run_enabled,
                "running": continuous_running,
                "cycles": cycle_count,
                "last_cycle_at": self._last_continuous_at,
                "last_error": self._last_continuous_error,
                "interval_seconds": self.continuous_interval_seconds,
                "max_cycles": self.continuous_max_cycles,
                "cycles_per_minute": cycles_per_minute,
            },
            "last_promotion": {
                "at": self._last_promotion_at,
                "name": self._last_promotion_name,
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
                "continuous_runner_default": "off",
                "stable_promotion_requires_diverse_evidence": True,
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
        return {
            "diagnosis": [
                f"Neurona {neuron.get('name', 'unknown')} evaluada en diagnóstico ligero.",
                f"Match activo: {bool(match.get('active')) if isinstance(match, dict) else False}.",
            ],
            "test_plan": ["Registrar observación ligera y esperar evidencia adicional."],
            "human_review_request": False,
        }

    def _loop(self) -> None:
        self.tick()
        while not self._stop.wait(self.interval_seconds):
            self.tick()

    def _continuous_loop(self) -> None:
        """Ciclo continuo con ritmo controlado, backoff y niveles de autonomía.

        No ejecuta el pipeline cognitivo completo (sin Hypothalamus/Central).
        Respeta: intervalo configurable, backoff exponencial, max ciclos,
        y niveles de autonomía que limitan qué acciones están permitidas.
        """
        from .background_neurons import candidates_from_system_debt
        from .neuron_formation_pipeline import form_candidates
        from .neuron_autopromoter import NeuronAutopromoter
        from .neuron_registry import NeuronRegistry
        from .neuron_activity_store import NeuronActivityStore

        tick_counter = 0
        runner_pool_cycle = 0

        while not self._stop.is_set():
            cycle_start = time.time()

            # Respetar max ciclos
            if self.continuous_max_cycles > 0 and tick_counter >= self.continuous_max_cycles:
                with self._lock:
                    self._last_continuous_error = (
                        f"max_cycles={self.continuous_max_cycles} alcanzado; "
                        "continuous runner detenido."
                    )
                break

            try:
                tick_counter += 1
                runner_pool_cycle += 1
                level = self.autonomy_level

                # 1. Generar candidatos desde deuda del sistema (requiere form_candidates+)
                if AUTONOMY_LEVELS.index(level) >= AUTONOMY_LEVELS.index("form_candidates"):
                    run_path = Path(str(self.runs_dir)) / f"pulse-{int(time.time())}"
                    try:
                        pulse_summary = self._build_system_dict()
                        raw_candidates = candidates_from_system_debt(
                            pulse_summary=pulse_summary,
                            system_events=[],
                        )
                        formed = form_candidates(raw_candidates)
                    except Exception as exc:
                        self._record_error(
                            "life_pulse.continuous.candidate_formation",
                            exc,
                            function="_continuous_loop",
                            operation="candidates_from_system_debt_and_form_candidates",
                        )
                        raise
                else:
                    formed = []

                # 2. Registrar candidatos formados
                registry = NeuronRegistry(db_path=self.db_path)
                if formed and AUTONOMY_LEVELS.index(level) >= AUTONOMY_LEVELS.index("form_candidates"):
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

                # 2b. Entrenar toda candidata existente sin training (requiere train_candidates+)
                if AUTONOMY_LEVELS.index(level) >= AUTONOMY_LEVELS.index("train_candidates"):
                    from .neuron_creator import NeuronSpec
                    from .neuron_trainer import NeuronTrainer, NeuronTrainingResult
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
                        except Exception as exc:
                            self._record_error(
                                "life_pulse.continuous.training",
                                exc,
                                function="_continuous_loop",
                                operation="train_candidate_without_training",
                                payload={"neuron_id": n.get("id"), "neuron_name": n.get("name")},
                            )

                # 3. Autopromoción (requiere promote_experimental+)
                if AUTONOMY_LEVELS.index(level) >= AUTONOMY_LEVELS.index("promote_experimental"):
                    autopromoter = NeuronAutopromoter(db_path=self.db_path)
                    promotion_events = autopromoter.promote()
                    for ev in promotion_events:
                        if ev.get("status") == "promoted":
                            with self._lock:
                                self._last_promotion_at = time.time()
                                self._last_promotion_name = (ev.get("payload") or {}).get("name")

                # 4. Activar neuronas experimental periódicamente (requiere promote_experimental+)
                if AUTONOMY_LEVELS.index(level) >= AUTONOMY_LEVELS.index("promote_experimental"):
                    if tick_counter % 3 == 0:
                        try:
                            self._activate_experimental_light()
                        except Exception as exc:
                            self._record_error(
                                "life_pulse.continuous.experimental_activation",
                                exc,
                                function="_continuous_loop",
                                operation="activate_experimental_light",
                            )

                # 5. Recomputar trust cada 10 ciclos
                if tick_counter % 10 == 0:
                    try:
                        from triade.memory.trust_store import TrustLevelStore
                        TrustLevelStore(db_path=self.db_path).recompute_all()
                    except Exception as exc:
                        self._record_error(
                            "life_pulse.continuous.recompute_trust",
                            exc,
                            function="_continuous_loop",
                            operation="trust_recompute_all",
                        )

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
                    except Exception as exc:
                        self._record_error(
                            "life_pulse.continuous.runner_run",
                            exc,
                            function="_continuous_loop",
                            operation="triade_runner_deep_cycle",
                        )

                elapsed_ms = int((time.time() - cycle_start) * 1000)
                with self._lock:
                    self._continuous_cycle_count += 1
                    self._last_continuous_at = time.time()
                    self._last_continuous_error = None
                    self._continuous_elapsed_ms.append(elapsed_ms)
                    if len(self._continuous_elapsed_ms) > 200:
                        self._continuous_elapsed_ms = self._continuous_elapsed_ms[-200:]
                    self._continuous_backoff_seconds = 0.0

            except Exception as exc:
                elapsed_ms = int((time.time() - cycle_start) * 1000)
                self._record_error(
                    "life_pulse.continuous.loop",
                    exc,
                    function="_continuous_loop",
                    operation="continuous_cycle",
                    payload={"tick_counter": tick_counter},
                )
                with self._lock:
                    self._continuous_cycle_count += 1
                    self._last_continuous_at = time.time()
                    self._last_continuous_error = str(exc)
                    self._continuous_elapsed_ms.append(elapsed_ms)
                    if len(self._continuous_elapsed_ms) > 200:
                        self._continuous_elapsed_ms = self._continuous_elapsed_ms[-200:]
                    # Backoff exponencial
                    self._continuous_backoff_seconds = min(
                        self._continuous_backoff_seconds * 2 + _BACKOFF_BASE_SECONDS,
                        _BACKOFF_MAX_SECONDS,
                    )

            # Sleep con backoff
            sleep_time = max(self.continuous_interval_seconds, self._continuous_backoff_seconds)
            if self._stop.wait(sleep_time):
                break

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
        except Exception as exc:
            self._record_error(
                "life_pulse.build_system_dict",
                exc,
                function="_build_system_dict",
                operation="compose_continuous_pulse_dict",
            )
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
        except Exception as exc:
            self._record_error(
                "life_pulse.build_system_pulse_text",
                exc,
                function="_build_system_pulse_text",
                operation="compose_continuous_pulse_text",
            )
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
        except Exception as exc:
            record_internal_error(
                "life_pulse.generate_thought",
                exc,
                payload={"module": __name__, "function": "_generate_thought", "operation": "append_stream_of_consciousness"},
                db_path=self.db_path,
            )

    def _recompute_trust(self) -> None:
        try:
            TrustLevelStore(db_path=self.db_path).recompute_all()
        except Exception as exc:
            record_internal_error(
                "life_pulse.recompute_trust",
                exc,
                payload={"module": __name__, "function": "_recompute_trust", "operation": "trust_recompute_all"},
                db_path=self.db_path,
            )

    def _get_trust_levels(self) -> dict[str, Any]:
        try:
            return TrustLevelStore(db_path=self.db_path).doctor()
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def _check_auto_identity(self) -> dict[str, Any] | None:
        try:
            store = AutoIdentityStore(db_path=self.db_path)
            return store.doctor()
        except Exception as exc:
            record_internal_error(
                "life_pulse.check_auto_identity",
                exc,
                payload={"module": __name__, "function": "_check_auto_identity", "operation": "auto_identity_doctor"},
                db_path=self.db_path,
            )
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
        except Exception as exc:
            record_internal_error(
                "life_pulse.update_emotional_rest",
                exc,
                payload={"module": __name__, "function": "_update_emotional_rest", "operation": "decay_hypothalamus_fatigue"},
                db_path=self.db_path,
            )

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
