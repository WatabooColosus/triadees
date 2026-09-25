"""A rejected local launch must never import the stateful application."""

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import serve_local_api


@pytest.mark.parametrize("fail", [False, True])
def test_reserved_socket_is_passed_to_server_and_closed(monkeypatch, fail):
    observed = []

    class Server:
        def __init__(self, config):
            assert config.app == "apps.single_port_app:app"

        def run(self, *, sockets):
            listener = sockets[0]
            observed.append(listener)
            assert listener.fileno() != -1
            assert listener.getsockname()[1] != 0
            if fail:
                raise RuntimeError("startup failed")

    monkeypatch.setattr(serve_local_api.uvicorn, "Server", Server)
    if fail:
        with pytest.raises(RuntimeError, match="startup failed"):
            serve_local_api.serve("127.0.0.1", 0)
    else:
        serve_local_api.serve("127.0.0.1", 0)
    assert observed[0].fileno() == -1


@pytest.mark.parametrize("reuse", [False, True])
def test_occupied_port_rejects_launch_before_application_import(tmp_path, reuse):
    # A poison app makes importing (not just running lifespan) observable.
    apps = tmp_path / "apps"
    apps.mkdir()
    (apps / "__init__.py").write_text("", encoding="utf-8")
    marker = tmp_path / "imported"
    (apps / "single_port_app.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('unexpected startup')\n"
        "raise RuntimeError('application must not load')\n",
        encoding="utf-8",
    )
    launcher = Path(__file__).resolve().parents[1] / "scripts" / "serve_local_api.py"
    env = dict(os.environ, PYTHONPATH=str(tmp_path))
    with socket.socket() as occupied:
        if reuse:
            occupied.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        result = subprocess.run(
            [
                sys.executable,
                str(launcher),
                "--host",
                "127.0.0.1",
                "--port",
                str(occupied.getsockname()[1]),
            ],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        assert result.returncode != 0
        assert not marker.exists(), result.stderr
        assert "ERROR" in result.stderr, result.stderr
