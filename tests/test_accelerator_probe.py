import subprocess
from types import SimpleNamespace

from triade.core import accelerator_probe as probe


def test_gpu_reading_keeps_unknown_sensor_unknown(monkeypatch):
    monkeypatch.setattr(probe.shutil, "which", lambda _: "nvidia-smi")

    def run(command, **kwargs):
        assert kwargs["timeout"] == 2
        assert not kwargs.get("shell")
        return SimpleNamespace(stdout="GPU-a, 6144, 5593, 0, [N/A]\n")

    monkeypatch.setattr(probe.subprocess, "run", run)
    result = probe.probe_nvidia()
    assert result["devices"][0]["free_mib"] == 5593
    assert result["devices"][0]["temperature_celsius"] is None


def test_gpu_timeout_does_not_break_probe(monkeypatch):
    monkeypatch.setattr(probe.shutil, "which", lambda _: "nvidia-smi")

    def run(*args, **kwargs):
        raise subprocess.TimeoutExpired("nvidia-smi", 2)

    monkeypatch.setattr(probe.subprocess, "run", run)
    assert probe.probe_nvidia()["status"] == "unavailable"


def test_battery_reports_discharge(monkeypatch):
    import psutil

    monkeypatch.setattr(
        psutil,
        "sensors_battery",
        lambda: SimpleNamespace(power_plugged=False, percent=12),
    )
    assert probe.probe_battery() == {
        "ac_connected": False,
        "battery_percent": 12,
        "power_source": "battery",
    }
