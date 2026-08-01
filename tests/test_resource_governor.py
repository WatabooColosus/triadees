"""Tests para Resource Governor, Permission Governor, Safe Shell y Resource Probe."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.single_port_app import app

client = TestClient(app, raise_server_exceptions=False)


def test_resource_probe_returns_safe_payload():
    """build_resource_probe no debe fallar ni ejecutar shell peligroso."""
    from triade.core.resource_probe import build_resource_probe

    probe = build_resource_probe()
    assert probe.get("status") == "ok"
    assert "cpu" in probe
    assert "memory" in probe
    assert "disk" in probe
    assert "power" in probe
    assert "thermal" in probe
    assert "warnings" in probe
    assert isinstance(probe["warnings"], list)
    # build_resource_probe usa HardwareProfiler que hereda subprocess.run, pero ella misma no lo invoca
    assert probe["status"] == "ok"


def test_work_mode_low_ram_degrades():
    """RAM < 2 GB debe forzar cooldown."""
    from triade.core.resource_governor import decide_work_mode

    probe = {
        "limits": {
            "ram_available_gb": 1.0,
            "disk_free_gb": 100,
            "tier": "high",
            "cpu_count": 8,
        },
        "cpu": {"load_1min": 1.0},
        "power": {"ac_connected": True, "battery_percent": None},
        "thermal": {"thermal_status": "ok"},
        "warnings": [],
    }
    blood = {"status": "ok", "can_reason": True, "can_embed": True}
    decision = decide_work_mode(probe, blood, "full_local")
    assert decision["effective_mode"] == "cooldown"
    assert "RAM disponible muy baja" in decision["reason"]


def test_work_mode_battery_low_observe_only():
    """Batería < 25% sin AC debe forzar observe_only."""
    from triade.core.resource_governor import decide_work_mode

    probe = {
        "limits": {
            "ram_available_gb": 16,
            "disk_free_gb": 100,
            "tier": "high",
            "cpu_count": 8,
        },
        "cpu": {"load_1min": 1.0},
        "power": {"ac_connected": False, "battery_percent": 20},
        "thermal": {"thermal_status": "ok"},
        "warnings": [],
    }
    blood = {"status": "ok", "can_reason": True, "can_embed": True}
    decision = decide_work_mode(probe, blood, "full_local")
    assert decision["effective_mode"] == "observe_only"
    assert "Batería" in decision["reason"]


def test_work_mode_high_hardware_allows_full_local():
    """Hardware tier high + AC + Ollama debe permitir full_local."""
    from triade.core.resource_governor import decide_work_mode

    probe = {
        "limits": {
            "ram_available_gb": 16,
            "disk_free_gb": 100,
            "tier": "high",
            "cpu_count": 8,
        },
        "cpu": {"load_1min": 1.0},
        "power": {"ac_connected": True, "battery_percent": 100},
        "thermal": {"thermal_status": "ok"},
        "warnings": [],
    }
    blood = {"status": "ok", "can_reason": True, "can_embed": True}
    decision = decide_work_mode(probe, blood, "full_local")
    assert decision["effective_mode"] == "full_local"
    assert decision["can_consolidate_stable"] is True
    assert decision["can_evaluate_learning"] is True
    assert decision["can_nourish_neurons"] is True


def test_work_mode_no_ollama_reasoner_limits():
    """Sin can_reason, máximo light_background."""
    from triade.core.resource_governor import decide_work_mode

    probe = {
        "limits": {
            "ram_available_gb": 16,
            "disk_free_gb": 100,
            "tier": "high",
            "cpu_count": 8,
        },
        "cpu": {"load_1min": 1.0},
        "power": {"ac_connected": True, "battery_percent": 100},
        "thermal": {"thermal_status": "ok"},
        "warnings": [],
    }
    blood = {"status": "degraded_no_ollama", "can_reason": False, "can_embed": False}
    decision = decide_work_mode(probe, blood, "full_local")
    assert decision["effective_mode"] == "light_background"
    assert decision["can_consolidate_stable"] is False


def test_permission_profile_identity_core_always_false():
    """identity_core nunca se modifica en ningún modo."""
    from triade.core.permission_governor import build_permission_profile

    for mode in (
        "observe_only",
        "light_background",
        "balanced_background",
        "full_local",
    ):
        p = build_permission_profile(mode)
        assert p["permissions"].get("can_modify_identity_core") is False


def test_safe_shell_rejects_unknown_command():
    """Comando no whitelist debe ser rechazado."""
    from triade.core.safe_shell import run_safe_command

    result = run_safe_command("rm -rf /")
    assert result["status"] == "error"
    assert "whitelist" in result["error"]


def test_safe_shell_git_status_allowed():
    """git_status debe ejecutarse sin error."""
    from triade.core.safe_shell import run_safe_command

    result = run_safe_command("git_status")
    assert result["status"] in ("ok", "error")
    assert result["command_key"] == "git_status"


def test_safe_shell_no_shell_true():
    """run_safe_command usa shell=False."""
    import inspect

    from triade.core.safe_shell import run_safe_command

    src = inspect.getsource(run_safe_command)
    assert "shell=False" in src


def test_system_resources_endpoint():
    """GET /api/system/resources debe responder."""
    resp = client.get("/api/system/resources")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"
    assert "cpu" in data
    assert "memory" in data


def test_system_work_mode_endpoint():
    """GET /api/system/work-mode debe responder."""
    resp = client.get("/api/system/work-mode?requested=observe_only")
    assert resp.status_code == 200
    data = resp.json()
    assert "effective_mode" in data
    assert "allowed_mode" in data


def test_system_permissions_endpoint():
    """GET /api/system/permissions debe responder."""
    resp = client.get("/api/system/permissions?requested=observe_only")
    assert resp.status_code == 200
    data = resp.json()
    assert "permissions" in data
    assert data["permissions"].get("can_modify_identity_core") is False


def test_system_safe_shell_commands_endpoint():
    """GET /api/system/safe-shell/commands debe listar whitelist."""
    resp = client.get("/api/system/safe-shell/commands")
    assert resp.status_code == 200
    data = resp.json()
    assert "commands" in data
    assert "git_status" in data["commands"]
    assert "pytest" in data["commands"]


def test_system_safe_shell_run_rejects_unknown():
    """POST /api/system/safe-shell/run rechaza comandos no whitelist."""
    resp = client.post("/api/system/safe-shell/run", json={"command_key": "rm -rf"})
    assert resp.status_code == 200  # no 500
    data = resp.json()
    assert data["status"] == "error"


def test_react_dashboard_includes_governor():
    """El dashboard React debe incluir bloque governor."""
    resp = client.get("/api/ui/react-dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert "governor" in data
    gov = data["governor"]
    assert "work_mode" in gov
    assert "capabilities" in gov
    assert "resource_probe" in gov


def test_no_shell_true_in_governor():
    """decide_work_mode y build_permission_profile no deben ejecutar shell."""
    import inspect

    from triade.core.permission_governor import build_permission_profile
    from triade.core.resource_governor import decide_work_mode

    for mod in (decide_work_mode, build_permission_profile):
        src = inspect.getsource(mod)
        assert "subprocess" not in src, f"{mod.__name__} contiene subprocess"


def test_high_load_average_forces_cooldown() -> None:
    """La regla que degrada el runtime tras cada reinicio no tenía prueba.

    `load_1min > cpu_count * 2` fuerza `cooldown`. Con 8 CPUs el umbral es 16.
    Los tres únicos casos en 482 decisiones registradas fueron la **primera**
    decisión de un ciclo de arranque (59,83 y 24,24 medidos el 2026-08-01, y
    30,37 el 2026-07-31); dos ciclos después el modo vuelve solo a
    `full_local`. Es un falso positivo autolimitado: `load_1min` es una media
    con inercia de un minuto, y el gobernador la lee dos segundos después de
    arrancar, cuando describe la tormenta de arranque anterior y no la
    capacidad presente.

    Se fija el comportamiento tal cual es hoy. Si algún día se le pone una
    gracia de arranque o se pasa a `load_5min`/PSI, que sea un cambio visible
    y no una deriva.
    """
    from triade.core.resource_governor import decide_work_mode

    probe = {
        "limits": {
            "ram_available_gb": 25.0,
            "disk_free_gb": 100,
            "tier": "high",
            "cpu_count": 8,
        },
        "cpu": {"load_1min": 24.24},
        "power": {"ac_connected": True, "battery_percent": None},
        "thermal": {"thermal_status": "ok"},
        "warnings": [],
    }
    blood = {"status": "ok", "can_reason": True, "can_embed": True}
    decision = decide_work_mode(probe, blood, "full_local")
    assert decision["effective_mode"] == "cooldown"
    assert "Load average (24.24) muy alto para 8 CPUs" in decision["reason"]
    assert "excede permitido 'cooldown'" in decision["reason"]


def test_load_average_just_under_the_threshold_does_not_degrade() -> None:
    """16.0 con 8 CPUs no degrada: la regla es estrictamente mayor."""
    from triade.core.resource_governor import decide_work_mode

    probe = {
        "limits": {
            "ram_available_gb": 25.0,
            "disk_free_gb": 100,
            "tier": "high",
            "cpu_count": 8,
        },
        "cpu": {"load_1min": 16.0},
        "power": {"ac_connected": True, "battery_percent": None},
        "thermal": {"thermal_status": "ok"},
        "warnings": [],
    }
    blood = {"status": "ok", "can_reason": True, "can_embed": True}
    decision = decide_work_mode(probe, blood, "full_local")
    assert decision["effective_mode"] == "full_local"
    assert "Load average" not in decision["reason"]
