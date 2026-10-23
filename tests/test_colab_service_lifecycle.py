"""Ownership and fail-closed Colab runtime lifecycle tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tools import colab_service_lifecycle as service


class FakeProcess:
    def __init__(self, root: Path, created: float = 123.456) -> None:
        self.root = root
        self.created = created

    def is_running(self) -> bool:
        return True

    def status(self) -> str:
        return "running"

    def create_time(self) -> float:
        return self.created

    def cwd(self) -> str:
        return str(self.root)

    def cmdline(self) -> list[str]:
        return [
            "/usr/bin/python",
            "-m",
            "uvicorn",
            "apps.single_port_app:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8010",
        ]

    def uids(self):
        return SimpleNamespace(effective=os.geteuid())

    def wait(self, timeout: int = 50) -> int:
        return 0


def fake_psutil(root: Path, *, port_pid: int = 4321, created: float = 123.456):
    process = FakeProcess(root, created=created)
    return SimpleNamespace(
        Process=lambda pid: process,
        STATUS_ZOMBIE="zombie",
        CONN_LISTEN="LISTEN",
        Error=Exception,
        NoSuchProcess=type("NoSuchProcess", (Exception,), {}),
        TimeoutExpired=type("TimeoutExpired", (Exception,), {}),
        net_connections=lambda kind: [
            SimpleNamespace(
                pid=port_pid,
                status="LISTEN",
                laddr=SimpleNamespace(port=8010),
            )
        ],
    )


def test_restart_survives_reloading_manager(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    owner = tmp_path / "state" / "owner.json"
    fake = fake_psutil(root)
    monkeypatch.setattr(service, "_psutil", lambda: fake)
    handle = Mock()
    handle.pid = 4321
    handle.poll.return_value = None
    assert service.register_process(handle, root, owner)["pid"] == 4321
    assert service.process_owned(root, owner)
    terminated: list[int] = []
    monkeypatch.setattr(service.os, "kill", lambda pid, sig: terminated.append(pid))
    monkeypatch.setattr(
        fake,
        "net_connections",
        lambda kind: (
            [SimpleNamespace(pid=4321, status="LISTEN", laddr=SimpleNamespace(port=8010))]
            if not terminated
            else []
        ),
    )
    assert service.stop_owned(root, owner)
    assert terminated == [4321]
    assert not owner.exists()


def test_unknown_listener_never_killed(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    owner = tmp_path / "owner.json"
    owner.write_text(
        json.dumps(
            {"pid": 4321, "create_time": 123.456, "root": str(root), "port": 8010}
        )
    )
    monkeypatch.setattr(service, "_psutil", lambda: fake_psutil(root, port_pid=7777))
    killer = Mock()
    monkeypatch.setattr(service.os, "kill", killer)
    assert not service.process_owned(root, owner)
    with pytest.raises(PermissionError, match="no se finalizará"):
        service.stop_owned(root, owner)
    killer.assert_not_called()


def test_reused_pid_is_refused(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    owner = tmp_path / "owner.json"
    owner.write_text(
        json.dumps(
            {"pid": 4321, "create_time": 123.456, "root": str(root), "port": 8010}
        )
    )
    monkeypatch.setattr(service, "_psutil", lambda: fake_psutil(root, created=999.0))
    assert not service.process_owned(root, owner)


def test_invalid_owner_file_fails_closed(tmp_path: Path) -> None:
    owner = tmp_path / "owner.json"
    assert not service.process_owned(tmp_path, owner)
    owner.write_text("not-json")
    assert not service.process_owned(tmp_path, owner)
