import io
import subprocess

import pytest

from triade.sandbox import code_execution as code

BUDGET = {"max_memory_mb": 128, "max_runtime_seconds": 2, "max_storage_mb": 1}
IMAGE = "sha256:" + "a" * 64


def test_missing_backend_does_not_execute_or_write_source(tmp_path, monkeypatch):
    monkeypatch.setattr(code, "_docker_executable", lambda: None)
    with pytest.raises(code.CodeSandboxUnavailable, match="no está instalado"):
        code.DockerCodeSandbox(tmp_path, image=IMAGE).execute("print('ok')", BUDGET)
    assert list(tmp_path.iterdir()) == []


def test_floating_image_is_rejected(tmp_path):
    with pytest.raises(code.CodeSandboxUnavailable, match="sha256"):
        code.DockerCodeSandbox(tmp_path, image="python:latest").execute("pass", BUDGET)


@pytest.mark.parametrize("outcome", ["ok", "failed", "timeout", "overflow"])
def test_container_limits_failure_and_cleanup(tmp_path, monkeypatch, outcome):
    calls = []
    monkeypatch.setattr(code, "_docker_executable", lambda: "docker")
    monkeypatch.setenv("TRIADE_SECRET_TEST", "must-not-be-inherited")

    def run(args, **kwargs):
        calls.append(args)
        assert "TRIADE_SECRET_TEST" not in kwargs["env"]
        return subprocess.CompletedProcess(args, 0, IMAGE + "\n", "")

    class Process:
        def __init__(self, args, **kwargs):
            calls.append(args)
            self.stdout = io.BytesIO(
                b"x" * (code.DockerCodeSandbox.OUTPUT_LIMIT + 1)
                if outcome == "overflow"
                else b"ok\n"
            )
            self.killed = False

        def wait(self, timeout):
            if outcome == "timeout" and not self.killed:
                raise subprocess.TimeoutExpired("docker", timeout)
            return 1 if outcome == "failed" else 0

        def poll(self):
            return 0 if self.killed or outcome != "timeout" else None

        def kill(self):
            self.killed = True

    monkeypatch.setattr(code.subprocess, "run", run)
    monkeypatch.setattr(code.subprocess, "Popen", Process)
    sandbox = code.DockerCodeSandbox(tmp_path, image=IMAGE)
    if outcome == "ok":
        receipt = sandbox.execute("print('ok')", BUDGET)
        assert receipt["quality_verified"] is False
        assert receipt["exit_code"] == 0
    else:
        with pytest.raises(RuntimeError):
            sandbox.execute("print('ok')", BUDGET)
    create = calls[1]
    assert create[create.index("--network") + 1] == "none"
    assert "--read-only" in create and "no-new-privileges=true" in create
    assert create[create.index("--user") + 1] == "65534:65534"
    assert create[create.index("--memory") + 1] == "128m"
    assert create[create.index("--pull") + 1] == "never"
    assert calls[-1][-3:-1] == ["rm", "--force"]
