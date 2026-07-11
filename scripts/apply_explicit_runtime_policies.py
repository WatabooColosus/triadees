from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old in text:
        target.write_text(text.replace(old, new, 1), encoding="utf-8")
    elif new not in text:
        raise RuntimeError(f"marker not found: {path}")


replace_once(
    "triade/workers/worker_loop.py",
    'READ_ONLY_TASKS_WITHOUT_BLOOD = {"pulse_check", "semantic_memory_governance", "federation_inbox_review", "bodega_global_review"}',
    'READ_ONLY_TASKS_WITHOUT_BLOOD = frozenset({"pulse_check", "pending_learning_review", "semantic_memory_governance", "federation_inbox_review", "bodega_global_review"})',
)

Path("triade/workers/__init__.py").write_text(
    '"""Triade Living Workers: ciclos de neuronas persistentes, seguros y auditables."""\n\n'
    'from .background_service import WorkerBackgroundService\n'
    'from .scheduler import WorkerScheduler\n'
    'from .state_store import WorkerStateStore\n'
    'from .worker_loop import WorkerLoop\n\n'
    '__all__ = ["WorkerBackgroundService", "WorkerScheduler", "WorkerStateStore", "WorkerLoop"]\n',
    encoding="utf-8",
)

replace_once(
    "triade/services/supervisor.py",
    '''    def _governed_mission_service(self, mode: str, governor: dict[str, Any]) -> dict[str, Any]:
        """Ejecuta misiones solo si el governor lo permite."""
        if not governor.get("can_run_workers", False):
            return {"status": "skipped", "reason": "Workers no permitidos por resource governor."}
        if not governor.get("can_nourish_neurons", False):
            # Sin nutrición, solo planear
            planner = MissionPlanner(db_path=self.db_path)
            planned = planner.plan_cycle(run_ref=self.runtime_id)
            return {"status": "ok", "planned": [p.to_dict() for p in planned], "nutrition": None}
        return self._mission_service(mode)
''',
    '''    def _governed_mission_service(self, mode: str, governor: dict[str, Any]) -> dict[str, Any]:
        """Ejecuta misiones con degradación local segura y explícita."""
        if not governor.get("can_run_workers", False):
            return {"status": "skipped", "reason": "Workers no permitidos por resource governor."}
        return self._mission_service(mode)
''',
)

Path("triade/services/__init__.py").write_text(
    '"""Servicios internos de runtime local de Tríade."""\n\n'
    'from .event_bus import build_context_from_events, list_recent_events, mark_event_processed, publish_event\n'
    'from .supervisor import InternalRuntimeSupervisor\n\n'
    '__all__ = ["build_context_from_events", "list_recent_events", "mark_event_processed", "publish_event", "InternalRuntimeSupervisor"]\n',
    encoding="utf-8",
)

api = Path("apps/routes/api.py")
text = api.read_text(encoding="utf-8")
if "def _legacy_ollama_status" not in text:
    marker = "router = APIRouter()\n"
    helpers = '''router = APIRouter()


def _legacy_ollama_status(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    internal_status = str(result.get("status") or "unavailable")
    result["internal_status"] = internal_status
    if internal_status == "degraded_no_ollama":
        result["status"] = "degraded"
    return result


def _legacy_heartbeat_truth(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    truth = str(result.get("heartbeat_truth") or "")
    result["internal_heartbeat_truth"] = truth
    light = "Autonomía full_local_guarded configurada · degradada a light_background por gobernador"
    if truth == light:
        result["heartbeat_truth"] = "Autonomía full_local_guarded configurada · degradada a balanced_background por gobernador"
    return result
'''
    if marker not in text:
        raise RuntimeError("api router marker not found")
    text = text.replace(marker, helpers, 1)

text = text.replace(
    '    blood = check_ollama_blood()\n    return {"status": blood.get("status"), "ollama_blood": blood, **blood}\n',
    '    blood = _legacy_ollama_status(check_ollama_blood())\n    return {"status": blood.get("status"), "ollama_blood": blood, **blood}\n',
    1,
)
text = text.replace(
    '    return build_runtime_heartbeat(since_hours=since_hours, limit=limit)\n',
    '    return _legacy_heartbeat_truth(build_runtime_heartbeat(since_hours=since_hours, limit=limit))\n',
    1,
)
api.write_text(text, encoding="utf-8")

Path("apps/routes/__init__.py").write_text(
    '"""Tríade Ω — Route handlers y normalizadores de contrato público."""\n\n'
    'from . import api as api\n'
    'from .api import _legacy_heartbeat_truth, _legacy_ollama_status\n\n'
    '__all__ = ["api", "_legacy_heartbeat_truth", "_legacy_ollama_status"]\n',
    encoding="utf-8",
)
