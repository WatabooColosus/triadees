"""Tests del perfilador de hardware."""

from __future__ import annotations

from triade.models.hardware_profile import HardwareProfiler


def test_hardware_profiler_detects_profile() -> None:
    profile = HardwareProfiler().detect()

    assert profile.cpu_count >= 1
    assert profile.tier in {"low", "medium", "high"}
    assert isinstance(profile.notes, list)


def test_hardware_tier_low() -> None:
    assert HardwareProfiler._tier(cpu_count=2, ram_total_gb=4, ram_available_gb=1.5) == "low"


def test_hardware_tier_medium() -> None:
    assert HardwareProfiler._tier(cpu_count=4, ram_total_gb=16, ram_available_gb=6) == "medium"


def test_hardware_tier_high() -> None:
    assert HardwareProfiler._tier(cpu_count=8, ram_total_gb=32, ram_available_gb=16) == "high"
