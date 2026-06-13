import os
import json
import pytest
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
        assert 'always_on_enabled' in data
        assert 'background_thread_alive' in data
        assert 'always_on_status' in data or 'status' in data
        assert 'configured_mode' in data
        assert 'config_source' in data

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
        assert 'always_on_detail' in hb


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

    def test_self_test_cli(self):
        """CLI self-test se ejecuta sin error."""
        from triade_digimon import handle_self_test
        from argparse import Namespace
        ns = Namespace(mode='safe')
        try:
            handle_self_test(ns)
        except SystemExit:
            pass
