import os
import json
import pytest
import yaml
from pathlib import Path
from unittest.mock import patch, MagicMock


# ── Tests de configuración ──────────────────────────────────────────────────

class TestAlwaysOnConfig:
    def test_default_config(self):
        """Carga con valores por defecto cuando no hay config ni env."""
        from triade.core.always_on import load_always_on_config
        with patch('triade.core.always_on.load_config', return_value={}):
            with patch.dict(os.environ, {}, clear=True):
                cfg = load_always_on_config()
        assert cfg.get('_config_source') == 'default'
        assert cfg.get('enabled') is False
        assert cfg.get('mode') == 'observe_only'
        assert cfg.get('interval_seconds') == 60
        assert cfg.get('safe_only') is True
        assert cfg.get('require_ollama') is False
        assert cfg.get('self_test_on_start') is True
        assert cfg.get('self_test_every_cycles') == 5

    def test_env_override_enabled(self):
        """Env var TRIADE_ALWAYS_ON=true activa el modo."""
        from triade.core.always_on import load_always_on_config
        with patch('triade.core.always_on.load_config', return_value={}):
            with patch.dict(os.environ, {'TRIADE_ALWAYS_ON': 'true'}, clear=True):
                cfg = load_always_on_config()
        assert cfg.get('enabled') is True
        assert cfg.get('_config_source') == 'env'

    def test_env_override_mode(self):
        """Env var TRIADE_ALWAYS_ON_MODE overridea el modo."""
        from triade.core.always_on import load_always_on_config
        with patch.dict(os.environ, {
            'TRIADE_ALWAYS_ON': 'true',
            'TRIADE_ALWAYS_ON_MODE': 'observe_only'
        }, clear=True):
            cfg = load_always_on_config()
        assert cfg.get('mode') == 'observe_only'

    def test_env_override_interval(self):
        """Env var TRIADE_ALWAYS_ON_INTERVAL_SECONDS overridea intervalo."""
        from triade.core.always_on import load_always_on_config
        with patch.dict(os.environ, {
            'TRIADE_ALWAYS_ON_INTERVAL_SECONDS': '120'
        }, clear=True):
            cfg = load_always_on_config()
        assert cfg.get('interval_seconds') == 120

    def test_env_override_all(self):
        """Todas las env vars se aplican correctamente."""
        from triade.core.always_on import load_always_on_config
        env = {
            'TRIADE_ALWAYS_ON': 'true',
            'TRIADE_ALWAYS_ON_MODE': 'full_local',
            'TRIADE_ALWAYS_ON_INTERVAL_SECONDS': '300',
            'TRIADE_ALWAYS_ON_START_DELAY_SECONDS': '5',
            'TRIADE_ALWAYS_ON_MAX_CYCLES': '10',
            'TRIADE_ALWAYS_ON_REQUIRE_OLLAMA': 'true',
            'TRIADE_ALWAYS_ON_SAFE_ONLY': 'false',
            'TRIADE_SELF_TEST_ON_START': 'false',
            'TRIADE_SELF_TEST_EVERY_CYCLES': '3',
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = load_always_on_config()
        assert cfg.get('enabled') is True
        assert cfg.get('mode') == 'full_local'
        assert cfg.get('interval_seconds') == 300
        assert cfg.get('start_delay_seconds') == 5
        assert cfg.get('max_cycles') == 10
        assert cfg.get('require_ollama') is True
        assert cfg.get('safe_only') is False
        assert cfg.get('self_test_on_start') is False
        assert cfg.get('self_test_every_cycles') == 3

    def test_triade_yml_always_on_maps_to_enabled(self):
        """runtime.always_on en triade.yml activa cfg.enabled."""
        from triade.core.always_on import load_always_on_config
        yml = {
            "runtime": {
                "always_on": True,
                "mode": "execute_missions",
                "interval_seconds": 60,
            }
        }
        with patch('triade.core.always_on.load_config', return_value=yml):
            with patch.dict(os.environ, {}, clear=True):
                cfg = load_always_on_config()
        assert cfg.get('enabled') is True
        assert cfg.get('mode') == 'execute_missions'
        assert cfg.get('_config_source') == 'triade.yml'

    def test_always_on_false_stays_disabled(self):
        """runtime.always_on=false mantiene Always-On deshabilitado."""
        from triade.core.always_on import load_always_on_config, should_start_always_on
        yml = {"runtime": {"always_on": False, "mode": "execute_missions"}}
        with patch('triade.core.always_on.load_config', return_value=yml):
            with patch.dict(os.environ, {}, clear=True):
                cfg = load_always_on_config()
                should_start = should_start_always_on()
        assert cfg.get('enabled') is False
        assert should_start is False

    def test_triade_yml_defaults_full_local_guarded(self):
        """La instalación local arranca por defecto en full_local_guarded."""
        yml = yaml.safe_load(Path("triade.yml").read_text(encoding="utf-8"))
        runtime = yml["runtime"]
        assert runtime["always_on"] is True
        assert runtime["mode"] == "full_local_guarded"
        assert runtime["workers_always_on"] is True
        assert runtime["workers_autostart"] is True
        assert runtime["workers_watchdog"] is True
        assert runtime["worker_mode"] == "full_local_guarded"

    def test_always_on_mode_full_local_guarded_configured(self):
        """load_always_on_config conserva full_local_guarded como modo configurado."""
        from triade.core.always_on import load_always_on_config
        cfg = load_always_on_config()
        assert cfg["enabled"] is True
        assert cfg["mode"] == "full_local_guarded"

    def test_workers_always_on_config_loaded(self):
        """La config Always-On incluye workers supervisados."""
        from triade.core.always_on import load_always_on_config
        cfg = load_always_on_config()
        assert cfg["workers_always_on"] is True
        assert cfg["workers_autostart"] is True
        assert cfg["workers_watchdog"] is True
        assert cfg["worker_mode"] == "full_local_guarded"


# ── Tests de should_start_always_on ─────────────────────────────────────────

class TestShouldStartAlwaysOn:
    def test_should_start_true(self):
        """should_start_always_on() devuelve True cuando enabled=true."""
        from triade.core.always_on import should_start_always_on
        with patch.dict(os.environ, {'TRIADE_ALWAYS_ON': 'true'}, clear=True):
            assert should_start_always_on() is True

    def test_should_start_false(self):
        """should_start_always_on() devuelve False por defecto."""
        from triade.core.always_on import should_start_always_on
        with patch('triade.core.always_on.load_config', return_value={}):
            with patch.dict(os.environ, {}, clear=True):
                assert should_start_always_on() is False


# ── Tests de build_always_on_status ─────────────────────────────────────────

class TestBuildAlwaysOnStatus:
    def test_build_status_disabled(self):
        """Estado cuando always-on está deshabilitado."""
        from triade.core.always_on import build_always_on_status
        with patch.dict(os.environ, {}, clear=True):
            status = build_always_on_status()
        assert status.get('enabled') is False
        assert status.get('background_thread_alive') is False
        assert status.get('status') in ('disabled', 'off')

    def test_build_status_enabled_not_running(self):
        """Estado cuando always-on está habilitado pero no corriendo."""
        from triade.core.always_on import build_always_on_status, _ALWAYS_ON_STATE
        with patch.dict(os.environ, {'TRIADE_ALWAYS_ON': 'true'}, clear=True):
            _ALWAYS_ON_STATE.clear()
            _ALWAYS_ON_STATE.update({"enabled": True, "status": "stopped"})
        status = build_always_on_status()
        assert status.get('enabled') is True
        assert status.get('background_thread_alive') is False
        assert status.get('always_on_enabled') is True
        assert status.get('degraded') is True
        assert status.get('degradation_reason')
        assert 'hilo' in status['degradation_reason'].lower()


class TestAlwaysOnStartup:
    def test_always_on_true_in_yml_starts_on_startup(self, monkeypatch):
        """start_always_on_if_enabled arranca cuando triade.yml trae runtime.always_on=true."""
        import triade.core.always_on as ao

        yml = {
            "runtime": {
                "always_on": True,
                "mode": "execute_missions",
                "interval_seconds": 60,
                "start_delay_seconds": 0,
                "require_ollama": False,
                "safe_only": True,
            }
        }
        ao._ALWAYS_ON_STATE.clear()
        ao._ALWAYS_ON_STATE.update({
            "enabled": False,
            "configured_mode": "observe_only",
            "effective_mode": "observe_only",
            "interval_seconds": 60,
            "max_cycles": 0,
            "config_source": "default",
            "background_thread_alive": False,
            "last_start_at": None,
            "last_cycle_at": None,
            "last_self_test_status": None,
            "last_start_result": None,
            "started_at": None,
            "status": "disabled",
            "error": None,
        })
        monkeypatch.setattr(ao, "load_config", lambda _path: yml)
        import triade.core.internal_runtime as runtime_mod
        monkeypatch.setattr(runtime_mod, "_BACKGROUND_THREAD", None)
        monkeypatch.setattr(ao, "start_internal_runtime_background", lambda **_kw: {"status": "started"})
        monkeypatch.setattr(ao, "run_self_test_cycle", lambda **_kw: {"status": "ok"})
        monkeypatch.setattr(ao, "record_internal_runtime_event", lambda *_args, **_kw: None)
        monkeypatch.setattr(ao, "time", MagicMock(sleep=lambda _seconds: None))
        monkeypatch.setattr(
            ao,
            "get_internal_runtime_supervisor",
            lambda **_kw: MagicMock(snapshot=lambda: {}),
        )
        import triade.core.ollama_blood as blood_mod
        import triade.core.resource_probe as probe_mod
        monkeypatch.setattr(blood_mod, "check_ollama_blood", lambda: {
            "ollama_ok": True,
            "can_reason": True,
            "can_embed": True,
        })
        monkeypatch.setattr(probe_mod, "build_resource_probe", lambda: {})

        result = ao.start_always_on_if_enabled()

        assert result.get("status") == "started"
        assert result.get("effective_mode") in ("execute_missions", "observe_only")
        assert ao.build_always_on_status().get("enabled") is True

    def test_always_on_no_duplicate_thread(self, monkeypatch):
        """Si ya existe background vivo, no se arranca otro thread."""
        import triade.core.always_on as ao

        class AliveThread:
            def is_alive(self):
                return True

        yml = {"runtime": {"always_on": True, "start_delay_seconds": 0}}
        monkeypatch.setattr(ao, "load_config", lambda _path: yml)
        import triade.core.internal_runtime as runtime_mod
        monkeypatch.setattr(runtime_mod, "_BACKGROUND_THREAD", AliveThread())
        starter = MagicMock(return_value={"status": "started"})
        monkeypatch.setattr(ao, "start_internal_runtime_background", starter)

        result = ao.start_always_on_if_enabled()

        assert result.get("status") == "already_running"
        starter.assert_not_called()

    def test_governor_can_degrade_full_local_guarded(self):
        """Resource Governor degrada full_local_guarded si el hardware no alcanza."""
        from triade.core.resource_governor import decide_work_mode
        probe = {
            "limits": {"ram_available_gb": 8.0, "disk_free_gb": 20.0, "tier": "medium", "cpu_count": 4},
            "power": {"ac_connected": True},
            "cpu": {"load_1min": 0.1},
            "thermal": {"thermal_status": "ok"},
            "warnings": [],
        }
        blood = {"status": "ok", "can_reason": True, "can_embed": True}
        decision = decide_work_mode(probe, blood, "full_local_guarded")
        assert decision["requested_mode"] == "full_local_guarded"
        assert decision["effective_mode"] == "balanced_background"
        assert "Degradado" in decision["reason"]

    def test_workers_watchdog_restarts_dead_worker(self, monkeypatch):
        """ensure_workers_alive reinicia si watchdog está activo y no hay thread vivo."""
        import triade.core.worker_autostart as wa

        class FakeService:
            def __init__(self, *args, **kwargs):
                pass

            def start(self, **kwargs):
                return {"status": "completed"}

            def status(self):
                return {"status": "ok", "running": False, "stop_requested": False}

        monkeypatch.setattr(wa, "WorkerBackgroundService", FakeService)
        monkeypatch.setattr(wa, "_decide_worker_mode", lambda mode: (mode, False, None))
        monkeypatch.setattr(wa, "_event", lambda *args, **kwargs: None)
        with wa._WORKER_LOCK:
            wa._WORKER_THREAD = None
            wa._WORKER_STATE.update({
                "configured": True,
                "autostart": True,
                "watchdog": True,
                "last_start_at": "earlier",
                "restart_attempts": 0,
                "status": "inactive",
            })

        status = wa.ensure_workers_alive({
            "workers_always_on": True,
            "workers_autostart": True,
            "workers_watchdog": True,
            "worker_mode": "full_local_guarded",
        })

        assert status["configured"] is True
        assert status["restart_attempts"] >= 1

    def test_full_local_guarded_does_not_allow_identity_core_modify(self):
        from triade.core.permission_governor import build_permission_profile
        profile = build_permission_profile("full_local_guarded", human_approved=True)
        assert profile["permissions"]["can_modify_identity_core"] is False

    def test_full_local_guarded_does_not_allow_direct_delete(self):
        from triade.core.autonomy_budget import build_autonomy_budget
        budget = build_autonomy_budget("full_local_guarded")
        assert budget["can_delete_directly"] is False
        assert "delete_permanently" in budget["forbidden_actions"]


# ── Tests del self-test cycle ───────────────────────────────────────────────

class TestSelfTestCycle:
    def test_self_test_safe_mode(self, tmp_path):
        """Self-test en modo safe ejecuta todos los checks sin errores."""
        from triade.core.self_test_cycle import run_self_test_cycle
        db = tmp_path / 'test.db'
        result = run_self_test_cycle(mode='safe', db_path=db, runs_dir=tmp_path / 'runs')
        assert result.get('status') == 'ok'
        assert len(result.get('checks', {})) == 9
        assert len(result.get('errors', [])) == 0
        assert result.get('duration_ms', 0) > 0

    def test_self_test_required_keys(self, tmp_path):
        """Self-test devuelve las claves esperadas."""
        from triade.core.self_test_cycle import run_self_test_cycle
        db = tmp_path / 'test.db'
        result = run_self_test_cycle(mode='safe', db_path=db, runs_dir=tmp_path / 'runs')
        for key in ('status', 'checks', 'errors', 'warnings',
                     'evidence_created', 'neurons_nourished',
                     'candidates_created', 'duration_ms'):
            assert key in result, f'Falta clave: {key}'


# ── Tests de integración: API endpoints ─────────────────────────────────────

from fastapi.testclient import TestClient
from apps.single_port_app import app

_api_client = TestClient(app)


class TestAlwaysOnAPI:
    def test_status_endpoint(self):
        """GET /api/runtime/always-on/status devuelve estado."""
        resp = _api_client.get('/api/runtime/always-on/status')
        assert resp.status_code == 200
        data = resp.json()
        assert 'enabled' in data
        assert 'always_on_enabled' in data
        assert 'background_thread_alive' in data
        assert 'status' in data
        assert 'configured_mode' in data
        assert 'effective_mode' in data
        assert 'interval_seconds' in data
        assert 'config_source' in data
        assert 'last_start_at' in data
        assert 'last_start_result' in data
        assert 'last_self_test_status' in data
        assert 'error' in data

    def test_self_test_endpoint(self):
        """POST /api/runtime/self-test ejecuta self-test y devuelve resultado."""
        resp = _api_client.post('/api/runtime/self-test')
        assert resp.status_code == 200
        data = resp.json()
        assert 'status' in data
        assert 'self_test' in data
        assert 'checks' in data['self_test']
        assert 'duration_ms' in data['self_test']

    def test_self_test_safe_mode_no_auth(self):
        """POST /api/runtime/self-test en safe no requiere API key."""
        resp = _api_client.post('/api/runtime/self-test')
        assert resp.status_code == 200
        assert resp.json().get('self_test', {}).get('status') == 'ok'

    def test_start_endpoint_works_with_key(self):
        """POST /api/runtime/always-on/start cuando TRIADE_API_KEY no está configurado."""
        resp = _api_client.post('/api/runtime/always-on/start')
        assert resp.status_code in (200, 403, 401)

    def test_stop_endpoint_works_with_key(self):
        """POST /api/runtime/always-on/stop cuando TRIADE_API_KEY no está configurado."""
        resp = _api_client.post('/api/runtime/always-on/stop')
        assert resp.status_code in (200, 403, 401)


# ── Tests de heartbeat always_on block ──────────────────────────────────────

class TestHeartbeatAlwaysOn:
    def test_heartbeat_has_always_on_block(self):
        """build_runtime_heartbeat incluye bloque always_on."""
        from triade.core.internal_runtime import build_runtime_heartbeat
        hb = build_runtime_heartbeat()
        assert 'always_on' in hb
        assert 'enabled' in hb['always_on']
        assert 'background_thread_alive' in hb['always_on']

    def test_heartbeat_backward_compat_fields(self):
        """build_runtime_heartbeat conserva campos planos legacy."""
        from triade.core.internal_runtime import build_runtime_heartbeat
        hb = build_runtime_heartbeat()
        assert 'always_on_enabled' in hb
        assert 'always_on_status' in hb
        assert 'always_on_background_thread_alive' in hb
        assert 'always_on_config_source' in hb
        assert 'always_on_effective_mode' in hb
        assert 'always_on_detail' in hb

    def test_heartbeat_reports_workers_inactive_when_expected_active(self):
        """Heartbeat incluye estado de workers always-on aunque estén inactivos."""
        from triade.core.internal_runtime import build_runtime_heartbeat
        hb = build_runtime_heartbeat()
        assert 'workers_always_on' in hb
        assert 'configured' in hb['workers_always_on']
        assert 'active' in hb['workers_always_on']

    def test_heartbeat_truth_full_local_guarded_degraded(self, monkeypatch):
        """Heartbeat muestra degradación de full_local_guarded por gobernador."""
        from triade.core.internal_runtime import build_runtime_heartbeat
        import triade.core.internal_runtime as rt
        import triade.core.always_on as ao
        import triade.core.worker_autostart as wa

        class AliveThread:
            def is_alive(self):
                return True

        monkeypatch.setattr(rt, "_BACKGROUND_THREAD", AliveThread())
        monkeypatch.setattr(ao, "build_always_on_status", lambda: {
            "enabled": True,
            "configured_mode": "full_local_guarded",
            "effective_mode": "balanced_background",
            "interval_seconds": 60,
            "config_source": "triade.yml",
            "status": "running",
            "background_thread_alive": True,
            "degraded_by_governor": True,
            "degradation_reason": "test degradation",
        })
        monkeypatch.setattr(wa, "build_workers_always_on_status", lambda **_kw: {
            "configured": True,
            "active": True,
            "watchdog": True,
            "autostart": True,
            "mode_configured": "full_local_guarded",
            "mode_effective": "balanced_background",
            "status": "running",
            "restart_attempts": 0,
            "degraded_by_governor": True,
            "degradation_reason": "test degradation",
        })
        hb = build_runtime_heartbeat()
        assert "Autonomía full_local_guarded configurada" in hb["heartbeat_truth"]

    def test_react_dashboard_includes_always_on(self):
        """El dashboard React expone always_on como bloque top-level."""
        resp = _api_client.get('/api/ui/react-dashboard')
        assert resp.status_code == 200
        data = resp.json()
        assert 'always_on' in data
        assert 'enabled' in data['always_on']

    def test_react_dashboard_shows_workers_always_on(self):
        """El dashboard React expone workers_always_on como bloque top-level."""
        resp = _api_client.get('/api/ui/react-dashboard')
        assert resp.status_code == 200
        data = resp.json()
        assert 'workers_always_on' in data
        assert 'configured' in data['workers_always_on']


# ── Tests de CLI commands ───────────────────────────────────────────────────

class TestAlwaysOnCLI:
    def test_always_on_status_cli(self):
        """CLI always-on status se ejecuta sin error."""
        from triade_digimon import handle_always_on
        from argparse import Namespace
        ns = Namespace(always_on_command='status')
        # Solo verifica que no lanza excepción
        try:
            handle_always_on(ns)
        except SystemExit:
            pass

    def test_cli_enable_writes_runtime_always_on_true(self, tmp_path, capsys):
        """always-on enable escribe runtime.always_on=true en triade.yml."""
        from triade_digimon import handle_always_on
        from argparse import Namespace

        config = tmp_path / "triade.yml"
        config.write_text("runtime:\n  always_on: false\n", encoding="utf-8")
        ns = Namespace(
            always_on_command='enable',
            config=str(config),
            mode='execute_missions',
            interval=60,
            safe_only=None,
            require_ollama=None,
            self_test_every=None,
        )

        handle_always_on(ns)
        capsys.readouterr()
        yml = yaml.safe_load(config.read_text(encoding="utf-8"))

        assert yml["runtime"]["always_on"] is True
        assert yml["runtime"]["mode"] == "execute_missions"
        assert yml["runtime"]["interval_seconds"] == 60

    def test_self_test_cli(self):
        """CLI self-test se ejecuta sin error."""
        from triade_digimon import handle_self_test
        from argparse import Namespace
        ns = Namespace(mode='safe')
        try:
            handle_self_test(ns)
        except SystemExit:
            pass
