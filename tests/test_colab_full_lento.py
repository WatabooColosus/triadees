"""Contrato Colab: FULL lento progresa sin ignorar alarmas ni bloquearse con load.

No se prueba un kernel real: el modo efectivo depende del governor y el arranque
externo debe limitar concurrencia e intervalos de trabajo.
"""

from triade.core.resource_governor import decide_work_mode


def probe(*, load=4.75, free_ram=10.63, free_disk=181.0, vram=15.0,
          temperature="ok", battery=None, ac=True, cpu_count=2):
    return {
        "limits": {
            "ram_available_gb": free_ram,
            "disk_free_gb": free_disk,
            "tier": "medium",
            "cpu_count": cpu_count,
        },
        "cpu": {"load_1min": load},
        "gpu": {"total_vram_gb": vram},
        "power": {"ac_connected": ac, "battery_percent": battery},
        "thermal": {"thermal_status": temperature},
        "warnings": [],
    }


BLOOD = {"status": "ok", "can_reason": True, "can_embed": True}


def test_colab_slow_full_with_measured_cpu_pressure(monkeypatch):
    monkeypatch.setenv("TRIADE_SLOW_FULL_LOCAL", "1")
    decision = decide_work_mode(probe(), BLOOD, "full_local_guarded")
    assert decision["effective_mode"] == "full_local_guarded"
    assert decision["can_run_workers"] is True
    assert decision["can_nourish_neurons"] is True
    assert decision["can_evaluate_learning"] is True
    assert decision["can_consolidate_stable"] is True
    assert decision["can_write_repo"] is False
    assert decision["can_run_shell"] is False
    assert "FULL lento" in decision["reason"]


def test_high_load_without_opt_in_still_cools_down(monkeypatch):
    monkeypatch.delenv("TRIADE_SLOW_FULL_LOCAL", raising=False)
    decision = decide_work_mode(probe(), BLOOD, "full_local_guarded")
    assert decision["effective_mode"] == "cooldown"
    assert decision["can_run_workers"] is False


def test_slow_full_extreme_cpu_remains_alive_at_reduced_load(monkeypatch):
    monkeypatch.setenv("TRIADE_SLOW_FULL_LOCAL", "1")
    decision = decide_work_mode(probe(load=9.2), BLOOD, "full_local_guarded")
    assert decision["effective_mode"] == "light_background"
    assert decision["can_run_workers"] is True
    assert decision["can_consolidate_stable"] is False


def test_slow_full_never_overrides_critical_thermal(monkeypatch):
    monkeypatch.setenv("TRIADE_SLOW_FULL_LOCAL", "1")
    decision = decide_work_mode(
        probe(temperature="critical"), BLOOD, "full_local_guarded"
    )
    assert decision["effective_mode"] == "cooldown"
    assert decision["can_run_workers"] is False


def test_slow_full_never_overrides_high_thermal(monkeypatch):
    monkeypatch.setenv("TRIADE_SLOW_FULL_LOCAL", "1")
    decision = decide_work_mode(
        probe(temperature="high"), BLOOD, "full_local_guarded"
    )
    assert decision["effective_mode"] == "observe_only"


def test_slow_full_respects_critical_battery(monkeypatch):
    monkeypatch.setenv("TRIADE_SLOW_FULL_LOCAL", "1")
    decision = decide_work_mode(
        probe(battery=10.0, ac=False), BLOOD, "full_local_guarded"
    )
    assert decision["effective_mode"] == "cooldown"


def test_slow_full_respects_critical_ram_and_disk(monkeypatch):
    monkeypatch.setenv("TRIADE_SLOW_FULL_LOCAL", "1")
    ram = decide_work_mode(probe(free_ram=0.9), BLOOD, "full_local_guarded")
    disk = decide_work_mode(probe(free_disk=1.8), BLOOD, "full_local_guarded")
    assert ram["effective_mode"] == "cooldown"
    assert disk["effective_mode"] == "blocked"


def test_slow_full_needs_ollama_reasoner(monkeypatch):
    monkeypatch.setenv("TRIADE_SLOW_FULL_LOCAL", "1")
    not_ready = {"status": "degraded_no_ollama", "can_reason": False, "can_embed": False}
    decision = decide_work_mode(probe(load=1.0), not_ready, "full_local_guarded")
    assert decision["can_nourish_neurons"] is False
    assert decision["can_consolidate_stable"] is False
