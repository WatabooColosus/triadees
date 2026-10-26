"""Cold Colab, next-release discovery and persistent non-regression contracts.

Release modules below are explicit fixtures operating only on tmp_path. They
do not manufacture application health, real Bodega rows or production evidence.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import tarfile
import threading
from types import SimpleNamespace

import pytest

from tools import triade_colab_continuous as updates
from tools import triade_colab_release as adapter

INSTALLER = b"""
def install(context):
    context['r5'].events.append(('install', context['manifest']['version']))
    return {'status': 'ready'}
def verify(context):
    return context['r5'].verified
def recover(context, error):
    context['r5'].events.append(('recover', error))
    return {'status': 'not_activated'}
def status(context):
    return {'fixture': True}
"""


class Catalogue:
    def __init__(self):
        self.code = INSTALLER
        self.manifest = {
            "schema": "triade.colab.release.v1",
            "repository": updates.REPO,
            "protocol": 1,
            "sequence": 1,
            "version": "release-one",
            "commit": "a" * 40,
            "channel": "candidate",
            "auto_update_safe": False,
            "files": {
                "installer": {
                    "path": "tools/release_one.py",
                    "sha256": hashlib.sha256(self.code).hexdigest(),
                }
            },
        }
        self.ci = "success"
        self.extra_runs = []
        self.calls = []

    def __call__(self, url, limit=300_000):
        self.calls.append(url)
        if url == updates.CHANNEL:
            return json.dumps(self.manifest).encode()
        if "/actions/runs?" in url:
            runs = [
                {
                    "id": i,
                    "name": name,
                    "run_number": 1,
                    "run_attempt": 1,
                    "head_sha": self.manifest["commit"],
                    "event": "push",
                    "status": "completed",
                    "conclusion": self.ci,
                }
                for i, name in enumerate(sorted(updates.REQUIRED_CI), 1)
            ]
            return json.dumps({"workflow_runs": runs + self.extra_runs}).encode()
        if url.endswith("/tools/release_one.py"):
            return self.code
        if url.endswith("/tools/controller.py"):
            return b"# deliberately incorrect component\n"
        raise AssertionError("Unexpected URL: " + url)


@pytest.fixture
def runtime(tmp_path):
    catalogue = Catalogue()
    r5 = SimpleNamespace(
        BASE=tmp_path / "drive", WORK=tmp_path / "r5-work", events=[], verified=True
    )
    mounted = {"ready": False}

    def mount():
        mounted["ready"] = True
        r5.BASE.mkdir(exist_ok=True)

    client = updates.Client(
        r5,
        mount_drive=mount,
        drive_ready=lambda: mounted["ready"],
        work=tmp_path / "updater",
        downloader=catalogue,
    )
    return client, catalogue, mounted


def test_one_action_installs_on_an_empty_vm(runtime):
    client, _, mounted = runtime
    assert not client.work.exists()
    assert client.install()["status"] == "ready"
    assert mounted["ready"] is True
    assert client.r5.events == [("install", "release-one")]
    assert client.drive_receipt.is_file()
    assert client.action("status") == {"fixture": True}


def test_same_cell_continues_after_drive_authorization_and_checks_once(runtime):
    client, catalogue, mounted = runtime
    original = client.downloader
    messages = []
    client.notify = messages.append

    def download(url, limit=300_000):
        assert mounted["ready"], "network check before Drive authorization"
        return original(url, limit)

    client.downloader = download
    try:
        assert client.run_cycle()["status"] == "ready"
        assert catalogue.calls.count(updates.CHANNEL) == 1
        assert sum("/actions/runs?" in url for url in catalogue.calls) == 1
        assert client.r5.events == [("install", "release-one")]
        assert any(text.startswith("1/5") for text in messages)
        assert any(text.startswith("5/5") for text in messages)
        assert messages[-1].startswith("Instalación / actualización verificada")
    finally:
        client.stop_watch()
    assert not any(t.name == "triade-install-progress" for t in threading.enumerate())


def test_reexecuting_healthy_cycle_reuses_runtime_without_network(runtime):
    client, catalogue, _ = runtime
    try:
        client.run_cycle()
        calls = list(catalogue.calls)
        events = list(client.r5.events)
        assert client.run_cycle() == {"status": "ready", "reused": True}
        assert catalogue.calls == calls
        assert client.r5.events == events
    finally:
        client.stop_watch()


def test_retry_after_failure_reuses_hash_checked_components(runtime):
    client, catalogue, _ = runtime
    client.r5.verified = False
    try:
        with pytest.raises(RuntimeError, match="No se activó"):
            client.run_cycle()
        assert client.last_error and not client.drive_receipt.exists()
        client.r5.verified = True
        assert client.run_cycle()["status"] == "ready"
        assert catalogue.calls.count(updates.CHANNEL) == 2
        assert (
            sum(url.endswith("/tools/release_one.py") for url in catalogue.calls) == 1
        )
    finally:
        client.stop_watch()


def test_cached_component_tampering_blocks_retry(runtime):
    client, catalogue, _ = runtime
    client.install()
    cached = next((client.work / "packages").rglob("installer.py"))
    cached.write_text("# altered cache\n")
    with pytest.raises(RuntimeError, match="SHA"):
        client.install()
    assert sum(url.endswith("/tools/release_one.py") for url in catalogue.calls) == 1


def test_watcher_does_not_check_on_start_or_hold_initial_install(runtime):
    client, catalogue, _ = runtime
    try:
        client.start_watch(seconds=600)
        assert client.lock.acquire(timeout=1)
        client.lock.release()
        assert catalogue.calls == []
        assert client.install()["status"] == "ready"
        assert catalogue.calls.count(updates.CHANNEL) == 1
    finally:
        client.stop_watch()


def test_next_release_uses_same_client_and_no_named_phase(runtime):
    client, catalogue, _ = runtime
    client.install()
    catalogue.manifest.update(
        sequence=2, version="a-completely-new-version", commit="b" * 40
    )
    assert client.check()["update_available"] is True
    assert client.install()["version"] == "a-completely-new-version"
    assert client.r5.events[-1] == ("install", "a-completely-new-version")
    assert client.installed()["manifest"]["sequence"] == 2


def test_resume_same_release_after_kernel_loss(runtime, tmp_path):
    client, catalogue, _ = runtime
    client.install()
    fresh = updates.Client(
        client.r5,
        mount_drive=lambda: None,
        drive_ready=lambda: True,
        work=tmp_path / "fresh-vm",
        downloader=catalogue,
    )
    assert fresh.check()["update_available"] is False
    assert fresh.install()["status"] == "ready"
    assert len(client.r5.events) == 2


def test_cold_session_reads_drive_before_allowing_downgrade(runtime, tmp_path):
    client, catalogue, _ = runtime
    catalogue.manifest.update(sequence=3, version="third")
    client.install()
    catalogue.manifest.update(sequence=1, version="old")
    ready = {"value": False}
    fresh = updates.Client(
        client.r5,
        mount_drive=lambda: ready.update(value=True),
        drive_ready=lambda: ready["value"],
        work=tmp_path / "fresh",
        downloader=catalogue,
    )
    with pytest.raises(RuntimeError, match="retrocede"):
        fresh.install()
    assert len(client.r5.events) == 1


def test_republished_code_must_increase_sequence(runtime):
    client, catalogue, _ = runtime
    client.install()
    catalogue.manifest["commit"] = "c" * 40
    with pytest.raises(RuntimeError, match="secuencia"):
        client.install()


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", None])
def test_ci_gate_blocks_execution(runtime, conclusion):
    client, catalogue, _ = runtime
    catalogue.ci = conclusion
    with pytest.raises(RuntimeError, match="CI"):
        client.install()
    assert client.r5.events == []
    assert not client.drive_receipt.exists()


def test_newer_ci_attempt_cannot_be_hidden_by_old_success(runtime):
    client, catalogue, _ = runtime
    catalogue.extra_runs = [
        {
            "id": 999,
            "name": "Runtime Truth CI",
            "run_number": 1,
            "run_attempt": 2,
            "head_sha": "a" * 40,
            "event": "push",
            "status": "in_progress",
            "conclusion": None,
        }
    ]
    with pytest.raises(RuntimeError, match="Runtime Truth CI"):
        client.install()


def test_every_hash_is_checked_before_any_module_executes(runtime, tmp_path):
    client, catalogue, _ = runtime
    sentinel = tmp_path / "should-not-be-created"
    catalogue.code = (
        f"from pathlib import Path\nPath({str(sentinel)!r}).touch()\n".encode()
        + INSTALLER
    )
    catalogue.manifest["files"]["installer"]["sha256"] = hashlib.sha256(
        catalogue.code
    ).hexdigest()
    catalogue.manifest["files"]["controller"] = {
        "path": "tools/controller.py",
        "sha256": "0" * 64,
    }
    with pytest.raises(RuntimeError, match="SHA"):
        client.install()
    assert not sentinel.exists()
    assert client.r5.events == []


def test_failed_runtime_verification_preserves_last_receipt(runtime):
    client, catalogue, _ = runtime
    client.install()
    before = client.drive_receipt.read_bytes()
    catalogue.manifest.update(
        sequence=2, version="unhealthy", channel="stable", auto_update_safe=True
    )
    client.r5.verified = False
    with pytest.raises(RuntimeError, match="No se activó"):
        client.install()
    assert client.drive_receipt.read_bytes() == before
    assert client.r5.events[-1][0] == "recover"
    count = len(client.r5.events)
    client.auto_apply = True
    client.watch_once()
    assert len(client.r5.events) == count  # do not retry a failed auto-update forever


def test_status_remains_available_after_failed_first_install(runtime):
    client, _, _ = runtime
    client.r5.verified = False
    with pytest.raises(RuntimeError, match="No se activó"):
        client.install()
    assert client.module is None
    assert not client.drive_receipt.exists()
    assert client.action("status") == {"fixture": True}
    with pytest.raises(RuntimeError, match="Arranque detenido"):
        client.action("open_frontend")


def test_watcher_detects_without_installing_or_creating_memory(runtime):
    client, _, _ = runtime
    client.watch_once()
    assert client.last_check["update_available"] is True
    assert client.r5.events == []
    assert not client.drive_receipt.exists()


def test_auto_update_requires_opt_in_stable_and_published_safety(runtime):
    client, catalogue, _ = runtime
    client.install()
    catalogue.manifest.update(
        sequence=2, version="next", channel="stable", auto_update_safe=True
    )
    client.watch_once()
    assert len(client.r5.events) == 1
    client.auto_apply = True
    catalogue.manifest["channel"] = "candidate"
    client.watch_once()
    assert len(client.r5.events) == 1
    catalogue.manifest["channel"] = "stable"
    catalogue.manifest["auto_update_safe"] = False
    client.watch_once()
    assert len(client.r5.events) == 1
    catalogue.manifest["auto_update_safe"] = True
    client.watch_once()
    assert client.r5.events[-1] == ("install", "next")


@pytest.mark.parametrize(
    "path",
    [
        "../bad.py",
        "/tools/bad.py",
        "tools/../../bad.py",
        "tools/./bad.py",
        "tools\\bad.py",
    ],
)
def test_catalogue_rejects_untrusted_component_paths(runtime, path):
    _, catalogue, _ = runtime
    value = copy.deepcopy(catalogue.manifest)
    value["files"]["installer"]["path"] = path
    with pytest.raises(ValueError):
        updates.validate_manifest(value)


def test_release_adapter_starts_from_empty_without_manual_phase(monkeypatch):
    calls = []
    center = SimpleNamespace(
        start=lambda: (
            calls.append("whole-start") or {"state": "running_version_rehydrated"}
        )
    )
    monkeypatch.setattr(
        adapter, "ensure_dependencies", lambda ctx: calls.append("dependencies") or {}
    )
    monkeypatch.setattr(adapter, "_center", lambda ctx: center)
    context = {"progress": lambda message: None}
    assert adapter.install(context)["status"] == "ready"
    assert calls == ["dependencies", "whole-start"]


def test_missing_system_tools_are_installed_before_boot(runtime, monkeypatch):
    client, _, _ = runtime
    commands = []
    client.r5.run = lambda args, **kwargs: commands.append(args)
    monkeypatch.setattr(
        adapter.shutil,
        "which",
        lambda name: "/bin/apt-get" if name == "apt-get" else None,
    )
    monkeypatch.setattr(adapter.os, "geteuid", lambda: 0)
    monkeypatch.setattr(adapter, "_node_major", lambda: 22)
    monkeypatch.setattr(adapter.importlib.util, "find_spec", lambda name: None)
    adapter.ensure_dependencies({"r5": client.r5, "progress": lambda text: None})
    assert commands[0] == ["apt-get", "update", "-qq"]
    assert "git" in commands[1] and "zstd" in commands[1]
    assert commands[2][-1] == "pytest"


def test_node_is_rejected_before_extraction_if_official_hash_disagrees(
    runtime, monkeypatch
):
    client, _, _ = runtime
    monkeypatch.setattr(adapter.shutil, "which", lambda name: "/bin/" + name)
    monkeypatch.setattr(adapter, "_node_major", lambda: 0)
    monkeypatch.setattr(adapter.platform, "system", lambda: "Linux")
    monkeypatch.setattr(adapter.platform, "machine", lambda: "x86_64")

    def download(url, limit):
        if url.endswith("index.json"):
            return json.dumps(
                [{"version": "v22.1.0", "lts": "fixture", "files": ["linux-x64"]}]
            ).encode()
        if url.endswith("SHASUMS256.txt"):
            return ("0" * 64 + "  node-v22.1.0-linux-x64.tar.xz\n").encode()
        return b"incorrect archive"

    monkeypatch.setattr(adapter, "_download", download)
    with pytest.raises(RuntimeError, match="SHA"):
        adapter.ensure_dependencies({"r5": client.r5, "progress": lambda text: None})
    assert not client.r5.WORK.exists()


def test_protocol_is_not_a_truthy_boolean(runtime):
    _, catalogue, _ = runtime
    catalogue.manifest["protocol"] = True
    with pytest.raises(ValueError, match="protocolo"):
        updates.validate_manifest(catalogue.manifest)


def test_absent_node_is_extracted_only_after_verified_download(runtime, monkeypatch):
    client, _, _ = runtime
    filename = "node-v22.1.0-linux-x64.tar.xz"
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:xz") as stream:
        info = tarfile.TarInfo("node-v22.1.0-linux-x64/bin/node")
        contents = b"fixture executable\n"
        info.size, info.mode = len(contents), 0o755
        stream.addfile(info, io.BytesIO(contents))
    data = archive.getvalue()
    before_path = adapter.os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", before_path)
    monkeypatch.setattr(adapter.shutil, "which", lambda name: "/bin/" + name)
    monkeypatch.setattr(adapter.platform, "system", lambda: "Linux")
    monkeypatch.setattr(adapter.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(adapter.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(
        adapter,
        "_node_major",
        lambda: 22 if "node-v22.1.0-linux-x64" in adapter.os.environ["PATH"] else 0,
    )

    def download(url, limit):
        if url.endswith("index.json"):
            return json.dumps(
                [{"version": "v22.1.0", "lts": "fixture", "files": ["linux-x64"]}]
            ).encode()
        if url.endswith("SHASUMS256.txt"):
            return (hashlib.sha256(data).hexdigest() + "  " + filename + "\n").encode()
        return data

    monkeypatch.setattr(adapter, "_download", download)
    result = adapter.ensure_dependencies(
        {"r5": client.r5, "progress": lambda text: None}
    )
    assert result["node_major"] == 22
    assert (
        client.r5.WORK / "dependencies/node-v22.1.0-linux-x64/bin/node"
    ).read_bytes() == b"fixture executable\n"
