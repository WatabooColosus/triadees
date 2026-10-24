"""Operator consent protects the destructive level-8 recovery diagnostic."""

from __future__ import annotations

import pytest

from scripts import run_level8_api_recovery as recovery


def test_without_explicit_pid_does_not_call_api(monkeypatch):
    monkeypatch.setattr(
        recovery, "get", lambda *_: pytest.fail("API contacted without consent")
    )
    monkeypatch.setattr(
        recovery.psutil, "Process", lambda *_: pytest.fail("process touched without consent")
    )
    with pytest.raises(SystemExit) as err:
        recovery.main([])
    assert err.value.code == 2


@pytest.mark.parametrize("provided", ["0", "-1"])
def test_invalid_pid_fails_without_api(monkeypatch, provided):
    monkeypatch.setattr(
        recovery, "get", lambda *_: pytest.fail("API contacted without positive PID")
    )
    with pytest.raises(SystemExit) as err:
        recovery.main(["--confirm-runtime-pid", provided])
    assert err.value.code == 2


def test_changed_pid_aborts_before_process_access(monkeypatch):
    monkeypatch.setattr(
        recovery, "get", lambda path: (200, {"runtime_pid": 3111})
    )
    monkeypatch.setattr(
        recovery.psutil, "Process", lambda *_: pytest.fail("process accessed after PID mismatch")
    )
    with pytest.raises(RuntimeError, match="PID cambió"):
        recovery.main(["--confirm-runtime-pid", "3112"])


def test_help_is_non_destructive(monkeypatch):
    monkeypatch.setattr(
        recovery, "get", lambda *_: pytest.fail("API contacted for --help")
    )
    with pytest.raises(SystemExit) as err:
        recovery.main(["--help"])
    assert err.value.code == 0
