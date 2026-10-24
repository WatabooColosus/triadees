"""Regression: process-wide RUSAGE_CHILDREN must not poison per-thread CPU."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from triade.runtime import resource_ledger as ledger


def test_process_global_child_cpu_cannot_be_billed_to_worker_thread(monkeypatch):
    """Another worker's subprocess must not move this task's CPU receipts."""
    cpu_samples = iter([(1.0, 0.2, "thread"), (1.05, 0.21, "thread")])
    monkeypatch.setattr(ledger, "_cpu_propio", lambda: next(cpu_samples))
    monkeypatch.setattr(
        ledger, "resource", SimpleNamespace(RUSAGE_CHILDREN=42)
    )
    # A process-wide child-CPU spike is deliberately unrelated to this thread.
    calls = 0

    def shared_rusage(which=None):
        nonlocal calls
        if which == 42:
            calls += 1
            return ledger._Usage(
                user=float(calls * 100),
                system=float(calls * 50),
                rss=2048.0,
            )
        return ledger._Usage(rss=2048.0)

    monkeypatch.setattr(ledger, "_rusage", shared_rusage)
    receipt = ledger.ResourceMeasurementCollector().finish()
    assert receipt.value("cpu_user") == pytest.approx(0.05)
    assert receipt.value("cpu_system") == pytest.approx(0.01)
    assert calls >= 1
    assert receipt.value("cpu_user") + receipt.value("cpu_system") < 0.1
