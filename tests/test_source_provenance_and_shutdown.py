import subprocess
import threading

import pytest
import uvicorn

from scripts.serve_local_api import serve, watch_shutdown
from triade.runtime.source_provenance import bind_loaded_source, capture_source


def test_bootstrap_binding_rejects_dirty_or_changed_source(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    source = tmp_path / "triade/example.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@localhost",
                    "commit", "-qm", "initial"], cwd=tmp_path, check=True)
    before = capture_source(tmp_path)
    assert bind_loaded_source(before, capture_source(tmp_path))["verified"] is True
    source.write_text("VALUE = 2\n")
    after = capture_source(tmp_path)
    assert after["source_dirty"] is True
    assert before["source_hash"] != after["source_hash"]
    assert bind_loaded_source(before, after)["verified"] is False


def test_shutdown_control_preserves_request_and_sets_server_exit(tmp_path):
    server = uvicorn.Server(uvicorn.Config("apps.single_port_app:app"))
    flag = tmp_path / "api.shutdown"
    flag.write_text('{"reason":"test graceful shutdown control"}')
    stop = threading.Event()
    thread = threading.Thread(target=watch_shutdown, args=(server, flag, stop))
    thread.start()
    thread.join(timeout=3)
    stop.set()
    thread.join(timeout=2)
    assert server.should_exit is True
    assert not flag.exists()
    receipts = list(tmp_path.glob("api-shutdown-handled-*.json"))
    assert len(receipts) == 1
    assert "test graceful shutdown control" in receipts[0].read_text()


def test_shutdown_control_rejects_external_path_before_binding(tmp_path):
    with pytest.raises(ValueError, match="outside_service_scope"):
        serve(shutdown_file=tmp_path / "api.shutdown")
