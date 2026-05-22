"""Runner del ciclo cognitivo mínimo de Tríade Ω."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from triade.models.hardware_profile import HardwareProfiler
from triade.models.model_router import ModelRouter
from triade.models.ollama_client import OllamaClient

from .bodega import Bodega
from .central import Central
from .config import load_config
from .contracts import InputPacket
from .crystal import Crystal
from .hypothalamus import Hypothalamus
from .safety import Safety
from .verification import Verifier


class TriadeRunner:
    """Ejecuta el ciclo: input → señales → memoria → cristal → plan → safety → output → reporte."""

    def __init__(
        self,
        runs_dir: str | Path = "runs",
        db_path: str | Path = "triade/memory/triade.db",
        config_path: str | Path = "triade.yml",
        use_ollama: bool = True,
        hypothalamus_model: str | None = None,
        central_model: str | None = None,
        auto_select_models: bool = True,
    ) -> None:
        self.runs_dir = Path(runs_dir)
        self.config = load_config(config_path)
        model_cfg = self.config.get("models", {})
        roles = model_cfg.get("roles", {})
        self.model_provider = str(model_cfg.get("provider", "ollama"))
        self.auto_select_models = auto_select_models
        self.model_selection: dict[str, Any] = {"enabled": False, "reason": "manual_or_disabled"}
        self.model_client = None
        if use_ollama and self.model_provider == "ollama":
            self.model_client = OllamaClient(
                base_url=str(model_cfg.get("base_url", "http://127.0.0.1:11434")),
                timeout=int(model_cfg.get("timeout", 60)),
            )
        selected = self._select_models(
            manual_hypothalamus=hypothalamus_model,
            manual_central=central_model,
            fallback_hypothalamus=str(roles.get("hypothalamus", "qwen2.5:3b-instruct")),
            fallback_central=str(roles.get("central", "qwen2.5:3b-instruct")),
        )
        self.hypothalamus_model = selected["hypothalamus"]
        self.central_model = selected["central"]
        self.hypothalamus = Hypothalamus(model_client=self.model_client, model_name=self.hypothalamus_model)
        self.bodega = Bodega(db_path=db_path)
        self.crystal = Crystal()
        self.central = Central(model_client=self.model_client, central_model=self.central_model)
        self.safety = Safety()
        self.verifier = Verifier()

    def _select_models(self, manual_hypothalamus: str | None, manual_central: str | None, fallback_hypothalamus: str, fallback_central: str) -> dict[str, str]:
        if manual_hypothalamus or manual_central or not self.auto_select_models or self.model_client is None:
            self.model_selection = {"enabled": False, "reason": "manual_model_provided_or_ollama_disabled", "hypothalamus": manual_hypothalamus or fallback_hypothalamus, "central": manual_central or fallback_central}
            return {"hypothalamus": manual_hypothalamus or fallback_hypothalamus, "central": manual_central or fallback_central}
        health = self.model_client.health()
        if not health.get("ok"):
            self.model_selection = {"enabled": False, "reason": "ollama_unavailable", "ollama": health, "hypothalamus": fallback_hypothalamus, "central": fallback_central}
            return {"hypothalamus": fallback_hypothalamus, "central": fallback_central}
        hardware = HardwareProfiler().detect()
        router = ModelRouter(available_models=health.get("models", []), hardware=hardware)
        hyp = router.route("hypothalamus")
        cen = router.route("central")
        self.model_selection = {"enabled": True, "reason": "auto_selected_by_hardware_router", "hardware": hardware.to_dict(), "ollama": health, "hypothalamus": hyp.to_dict(), "central": cen.to_dict()}
        return {"hypothalamus": hyp.selected_model, "central": cen.selected_model}

    def run(self, user_input: str, source: str = "console") -> dict[str, Any]:
        input_packet = InputPacket(user_input=user_input, source=source)
        self.bodega.create_run(input_packet)
        run_path = self.runs_dir / input_packet.run_id
        run_path.mkdir(parents=True, exist_ok=True)
        signals = self.hypothalamus.analyze(input_packet)
        hypothalamus_model_result = dict(self.hypothalamus.last_model_result)
        hypothalamus_quality = self._score_hypothalamus(signals, hypothalamus_model_result)
        signal_id = self.bodega.store_signal(signals)
        memory = self.bodega.recall(input_packet)
        crystal_history = self.bodega.list_recent_crystals(limit=5)
        crystal = self.crystal.regulate(signals, memory, history=crystal_history)
        crystal_id = self.bodega.store_crystal(crystal)
        plan = self.central.plan(input_packet, signals, memory, crystal)
        safety = self.safety.review(signals, plan)
        safety_id = self.bodega.store_safety(safety)
        if safety.status == "blocked":
            output = self.central.respond(input_packet, signals, memory, crystal, plan)
            output.response = "La acción fue bloqueada por Safety."
            output.status = "blocked"
        else:
            output = self.central.respond(input_packet, signals, memory, crystal, plan)
        central_quality = self._score_central(output.response, output.model_ok)
        self.bodega.update_run_models(input_packet.run_id, hypothalamus_model_result.get("name", self.hypothalamus_model), output.model_name)
        hypothalamus_event_id = self.bodega.store_model_event(input_packet.run_id, "hypothalamus", str(hypothalamus_model_result.get("provider")), str(hypothalamus_model_result.get("name")), bool(hypothalamus_model_result.get("ok")), hypothalamus_model_result.get("error"), hypothalamus_quality)
        central_event_id = self.bodega.store_model_event(input_packet.run_id, "central", output.model_provider, output.model_name, output.model_ok, output.model_error, central_quality)
        memory_diff = self.bodega.store_episode(input_packet, output)
        temporal_state = {
            "status": crystal.temporal_status,
            "q_delta": crystal.q_delta,
            "stability_delta": crystal.stability_delta,
            "history_window": crystal.history_window,
            "alerts": crystal.temporal_alerts,
        }
        output.memory_diff = {
            **memory_diff, "signal_id": signal_id, "crystal_id": crystal_id, "safety_id": safety_id,
            "crystal_temporal_state": temporal_state,
            "hypothalamus_model_provider": hypothalamus_model_result.get("provider"), "hypothalamus_model_name": hypothalamus_model_result.get("name"), "hypothalamus_model_ok": hypothalamus_model_result.get("ok"), "hypothalamus_model_error": hypothalamus_model_result.get("error"), "hypothalamus_quality_score": hypothalamus_quality, "hypothalamus_model_event_id": hypothalamus_event_id,
            "central_model_provider": output.model_provider, "central_model_name": output.model_name, "central_model_ok": output.model_ok, "central_model_error": output.model_error, "central_quality_score": central_quality, "central_model_event_id": central_event_id,
            "model_provider": output.model_provider, "model_name": output.model_name, "model_ok": output.model_ok, "model_error": output.model_error, "model_selection": self.model_selection,
        }
        report = self.verifier.verify(output, safety)
        verification_id = self.bodega.store_verification_report(report)
        output.memory_diff["verification_report_id"] = verification_id
        artifacts = {"input.json": input_packet.to_dict(), "signals.json": signals.to_dict(), "memory.json": memory.to_dict(), "crystal.json": crystal.to_dict(), "plan.json": plan.to_dict(), "safety.json": safety.to_dict(), "output.json": output.to_dict(), "memory_diff.json": output.memory_diff, "report.json": report.to_dict()}
        for filename, payload in artifacts.items():
            self._write_json(run_path / filename, payload)
        integrity = {
            "run_id": input_packet.run_id, "status": report.status, "artifacts": sorted(artifacts.keys()), "database": memory_diff.get("db_path"), "episode_id": memory_diff.get("episode_id"), "signal_id": signal_id, "crystal_id": crystal_id, "safety_id": safety_id, "verification_report_id": verification_id,
            "crystal_temporal_state": temporal_state,
            "hypothalamus_model_provider": hypothalamus_model_result.get("provider"), "hypothalamus_model_name": hypothalamus_model_result.get("name"), "hypothalamus_model_ok": hypothalamus_model_result.get("ok"), "hypothalamus_quality_score": hypothalamus_quality, "hypothalamus_model_event_id": hypothalamus_event_id,
            "central_model_provider": output.model_provider, "central_model_name": output.model_name, "central_model_ok": output.model_ok, "central_quality_score": central_quality, "central_model_event_id": central_event_id, "model_provider": output.model_provider, "model_name": output.model_name, "model_ok": output.model_ok, "model_selection": self.model_selection, "closed": True,
        }
        self._write_json(run_path / "integrity.json", integrity)
        (run_path / "CLOSED").write_text("closed\n", encoding="utf-8")
        return {"run_id": input_packet.run_id, "response": output.response, "safety": safety.to_dict(), "report": report.to_dict(), "memory_diff": output.memory_diff, "crystal_temporal_state": temporal_state, "models": {"hypothalamus": {**hypothalamus_model_result, "quality_score": hypothalamus_quality, "event_id": hypothalamus_event_id}, "central": {"provider": output.model_provider, "name": output.model_name, "ok": output.model_ok, "error": output.model_error, "quality_score": central_quality, "event_id": central_event_id}}, "model": {"provider": output.model_provider, "name": output.model_name, "ok": output.model_ok, "error": output.model_error}, "model_selection": self.model_selection, "run_path": str(run_path)}

    def recall(self, query: str, limit: int = 10) -> dict[str, Any]:
        episodes = self.bodega.list_recent_episodes(limit=limit)
        if query:
            episodes = [ep for ep in episodes if query.lower() in (ep.get("title") or "").lower() or query.lower() in (ep.get("summary") or "").lower() or query.lower() in (ep.get("tags") or "").lower()]
        return {"query": query, "count": len(episodes), "episodes": episodes}

    def doctor(self) -> dict[str, Any]:
        status = self.bodega.doctor(runs_dir=self.runs_dir)
        status["models"] = {"provider": self.model_provider, "hypothalamus": self.hypothalamus_model, "central": self.central_model, "selection": self.model_selection, "ollama": self.model_client.health() if self.model_client else {"ok": False, "disabled": True}}
        return status

    @staticmethod
    def _score_hypothalamus(signals: Any, model_result: dict[str, Any]) -> float:
        score = 0.35
        if model_result.get("ok"): score += 0.25
        if signals.intent in {"conversation", "build_or_update", "analyze", "memory"}: score += 0.10
        if signals.urgency in {"low", "medium", "high"}: score += 0.10
        if signals.risk in {"low", "medium", "high", "critical"}: score += 0.10
        if len(signals.pv7) >= 7: score += 0.10
        return round(min(score, 1.0), 2)

    @staticmethod
    def _score_central(response: str, model_ok: bool) -> float:
        text = response.strip()
        score = 0.35
        if model_ok: score += 0.25
        if len(text) >= 40: score += 0.15
        if len(text) <= 1800: score += 0.10
        if "Tríade" in text or "Triade" in text: score += 0.05
        if text.endswith((".", "!", "?")): score += 0.10
        return round(min(score, 1.0), 2)

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
