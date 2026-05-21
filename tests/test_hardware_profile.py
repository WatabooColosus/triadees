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
    assert HardwareProfiler._tier(cpu_count=2, ram_total_gb=4, ram_available_gb=1.5) == "low"


def test_hardware_tier_medium() -> None:
    assert HardwareProfiler._tier(cpu_count=4, ram_total_gb=16, ram_available_gb=6) == "medium"


def test_hardware_tier_high() -> None:
    assert HardwareProfiler._tier(cpu_count=8, ram_total_gb=32, ram_available_gb=16) == "high"


def test_gpu_can_raise_tier() -> None:
    gpu = GPUInfo(name="Test GPU", vendor="NVIDIA", vram_total_gb=8.0, cuda_available=True)
    assert HardwareProfiler._tier(cpu_count=8, ram_total_gb=16, ram_available_gb=8, gpus=[gpu]) == "high"


def test_capability_notes_low_ram() -> None:
    status, notes = HardwareProfiler._capability_status(tier="low", ram_available_gb=2.0, gpus=[])

    assert status == "low"
    assert any("RAM" in note for note in notes)
