"""Regression: Colab workers honor serial fallback without touching SQLite."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from tools import triade_colab_release as installer
from triade.workers import background_service as background

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = "tools/colab_patch_sources/worker_serial_fallback.py"


def test_colab_overlay_is_identical_to_runtime_worker_and_installer_checks_it():
    source = (ROOT / OVERLAY).read_text(encoding="utf-8")
    ast.parse(source, filename=OVERLAY)
    assert source == (ROOT / "triade/workers/background_service.py").read_text(
        encoding="utf-8"
    )
    for function in (
        installer._apply_runtime_path_patches,
        installer._runtime_patches_match,
    ):
        assert (
            '"worker_serial_fallback": "triade/workers/background_service.py"'
            in inspect.getsource(function)
        )


@pytest.fixture
def service(monkeypatch, tmp_path):
    """A fake worker records config without starting a worker or opening a DB."""

    class FakeWorkerLoop:
        def __init__(self, **kwargs):
            pass

        def clear_stop(self):
            pass

        def run(self, config):
            return {"config": config}

    monkeypatch.setattr(background, "WorkerStateStore", lambda **kwargs: object())
    monkeypatch.setattr(background, "WorkerTaskQueue", lambda **kwargs: object())
    monkeypatch.setattr(background, "WorkerLoop", FakeWorkerLoop)
    return background.WorkerBackgroundService(
        db_path=tmp_path / "test.sqlite3",
        runs_dir=tmp_path / "runs",
    )


@pytest.mark.parametrize("method", ["run_once", "start"])
@pytest.mark.parametrize(
    ("flag", "expected"),
    [("0", False), ("1", True)],
)
def test_serial_fallback_is_respected_by_background_service(
    service, monkeypatch, method, flag, expected
):
    monkeypatch.setenv("TRIADE_WORKER_CONCURRENCY", flag)
    monkeypatch.setenv("TRIADE_SLOW_FULL_LOCAL", "1")
    config = getattr(service, method)()["config"]
    assert config.concurrency_enabled is expected
    assert config.max_concurrent_tasks == 1


@pytest.mark.parametrize("method", ["run_once", "start"])
def test_dry_run_remains_serial_even_with_concurrency_enabled(
    service, monkeypatch, method
):
    monkeypatch.setenv("TRIADE_WORKER_CONCURRENCY", "1")
    config = getattr(service, method)(dry_run=True)["config"]
    assert config.concurrency_enabled is False
