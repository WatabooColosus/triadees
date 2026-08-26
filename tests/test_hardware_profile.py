"""Tests del perfilador de capacidad del sistema."""

from __future__ import annotations

from triade.models.hardware_profile import GPUInfo, HardwareProfiler


def test_hardware_profiler_detects_profile() -> None:
    profile = HardwareProfiler().detect()

    assert profile.cpu_count >= 1
    assert profile.tier in {"low", "medium", "high"}
    assert profile.os_name
    assert profile.architecture
    assert profile.python_version
    assert isinstance(profile.notes, list)
    assert isinstance(profile.compatibility_notes, list)


def test_hardware_tier_low() -> None:
    assert (
        HardwareProfiler._tier(cpu_count=2, ram_total_gb=4, ram_available_gb=1.5)
        == "low"
    )


def test_hardware_tier_medium() -> None:
    assert (
        HardwareProfiler._tier(cpu_count=4, ram_total_gb=16, ram_available_gb=6)
        == "medium"
    )


def test_hardware_tier_high() -> None:
    assert (
        HardwareProfiler._tier(cpu_count=8, ram_total_gb=32, ram_available_gb=16)
        == "high"
    )


def test_gpu_can_raise_tier() -> None:
    gpu = GPUInfo(
        name="Test GPU", vendor="NVIDIA", vram_total_gb=8.0, cuda_available=True
    )
    assert (
        HardwareProfiler._tier(
            cpu_count=8, ram_total_gb=16, ram_available_gb=8, gpus=[gpu]
        )
        == "high"
    )


def test_capability_notes_low_ram() -> None:
    status, notes = HardwareProfiler._capability_status(
        tier="low", ram_available_gb=2.0, gpus=[]
    )

    assert status == "low"
    assert any("RAM" in note for note in notes)


def test_las_sondas_estaticas_no_se_repiten_dentro_del_ttl(monkeypatch):
    """El modelo de GPU no cambia entre dos pulsos; preguntarlo sí cuesta.

    Medido el 2026-08-26: `build_system_pulse()` llama a `detect()` tres veces y
    cada una lanzaba sus `subprocess`. Con `pulse_check` cada 30 s eso era el
    mayor consumidor del presupuesto diario de CPU, y al reventarlo el
    gobernador dejaba fuera a la clase `light` —la cadena de aprendizaje—.

    `nvidia-smi` se consulta por `name,memory.total,driver_version`: los tres
    son estáticos y ninguno es VRAM libre, así que cachearlos no esconde ningún
    dato vivo.
    """
    from triade.models import hardware_profile as hp

    hp.reset_static_probes()
    llamadas: list[list[str]] = []
    monkeypatch.setattr(
        hp.HardwareProfiler,
        "_run_command",
        staticmethod(lambda command: llamadas.append(command) or ""),
    )

    hp.HardwareProfiler._detect_gpus()
    tras_la_primera = len(llamadas)
    hp.HardwareProfiler._detect_gpus()
    hp.HardwareProfiler._detect_gpus()

    assert len(llamadas) == tras_la_primera, "la segunda sonda no debe ejecutarse"

    hp.reset_static_probes()
    hp.HardwareProfiler._detect_gpus()
    assert len(llamadas) > tras_la_primera, "al vaciar la caché se vuelve a sondar"


def test_la_ram_disponible_no_se_cachea():
    """Cachear lo dinámico sería mentir: `_tier` decide con la RAM libre."""
    from triade.models import hardware_profile as hp

    hp.reset_static_probes()
    perfil = hp.HardwareProfiler().detect()
    assert perfil.ram_available_gb >= 0
    # `_memory_kb` no pasa por `_cached_probe`: se lee de /proc en cada llamada.
    assert "memoria" not in hp._SONDAS
    assert not any(clave.startswith("ram") for clave in hp._SONDAS)
