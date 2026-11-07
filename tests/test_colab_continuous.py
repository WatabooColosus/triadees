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


def test_panel_refresh_preserves_legacy_runtime_without_observation(runtime):
    client, _, _ = runtime
    module = object()
    diagnostic_module = object()
    context = {"progress": lambda message: None, "session_id": "existing-session"}
    diagnostic_context = {"progress": lambda message: None}
    old = SimpleNamespace(
        r5=client.r5,
        module=module,
        context=context,
        diagnostic_module=diagnostic_module,
        diagnostic_context=diagnostic_context,
        last_check={"verified": True},
        last_error=None,
        failed_release=None,
        auto_apply=True,
    )  # Pre-observation panel client: no last_observation attribute.
    client.auto_apply = True

    assert updates.transfer_render_state(client, old) is True
    assert client.module is module
    assert client.context is context
    assert client.diagnostic_module is diagnostic_module
    assert client.diagnostic_context is diagnostic_context
    assert client.last_observation is None
    assert client.last_check == {"verified": True}
    assert context["progress"] == client.progress
    assert diagnostic_context["progress"] == client.progress
    assert client.auto_apply is False
    assert old.context is context


def test_panel_refresh_preserves_existing_observation(runtime):
    client, _, _ = runtime
    observation = {"status": "runtime_verified", "version": "old"}
    old = SimpleNamespace(
        r5=client.r5,
        module=object(),
        context={"progress": lambda message: None},
        last_observation=observation,
    )
    assert updates.transfer_render_state(client, old) is True
    assert client.last_observation is observation


def test_panel_refresh_rejects_missing_runtime_context(runtime):
    client, _, _ = runtime
    old = SimpleNamespace(r5=client.r5, module=object())
    with pytest.raises(RuntimeError, match="falta estado de sesión context"):
        updates.transfer_render_state(client, old)
    assert client.module is None and client.context is None


def test_panel_refresh_does_not_import_another_runtime(runtime):
    client, _, _ = runtime
    old = SimpleNamespace(r5=object(), module=object(), context={})
    client.auto_apply = True
    assert updates.transfer_render_state(client, old) is False
    assert client.module is None and client.context is None
    assert client.auto_apply is True


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
        status=dict,
        start=lambda: (
            calls.append("whole-start") or {"state": "running_version_rehydrated"}
        ),
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


def test_running_panel_update_installs_auditor_without_runtime_operations(
    tmp_path, monkeypatch
):
    calls = []
    source = tmp_path / "auditor.py"
    source.write_text("""
def install(r5):
    r5.updated = True
def audit(r5, seconds, *, emit=True):
    return {'audit_version': 'fixture', 'seconds': seconds, 'emit': emit}
""")
    center = SimpleNamespace(
        status=lambda: {
            "api_http_200": True,
            "ollama_http_200": True,
            "bodega": "SQLite ok / fixture",
            "known_regression": None,
            "release": "R6.3.1 candidata / fixture",
            "counts": {"neurons": 16},
        },
        start=lambda: calls.append("forbidden-start"),
    )
    monkeypatch.setattr(adapter, "_center", lambda context: center)
    monkeypatch.setattr(
        adapter,
        "ensure_dependencies",
        lambda context: calls.append("forbidden-dependencies"),
    )
    runtime = SimpleNamespace(updated=False)
    context = {
        "r5": runtime,
        "files": {"auditor": str(source)},
        "progress": lambda text: None,
    }
    assert adapter.install(context)["runtime"]["state"] == "already_running_verified"
    assert runtime.updated is True
    assert calls == []
    assert adapter.audit(context) == {
        "audit_version": "fixture",
        "seconds": 30,
        "emit": False,
    }
    assert context["verified_counts"] == {"neurons": 16}


def test_existing_client_accepts_auditor_component_through_same_update_button(runtime):
    from pathlib import Path

    client, catalogue, _ = runtime
    client.install()
    catalogue.manifest["sequence"] = 2
    catalogue.manifest["version"] = "fixture-panel-audit"
    catalogue.manifest["commit"] = "b" * 40
    catalogue.code = Path(adapter.__file__).read_bytes()
    components = {
        "protection": b"""
def repair(r5):
    r5.protection_repaired_fixture = True
    return {'status': 'encrypted_copy_verified_fixture'}
def start_watch(r5):
    r5.protection_watch_fixture = True
def status(r5):
    return {'status': 'fixture'}
""",
        "controller": b"""
class Center:
    def __init__(self, r5, rehydrator=None):
        pass
    def status(self):
        return {'api_http_200': True, 'ollama_http_200': True,
                'bodega': 'SQLite ok / fixture', 'release': 'R6.3.1 candidata',
                'known_regression': None, 'counts': {'neurons': 16}}
    def start(self):
        raise AssertionError('runtime must not restart')
""",
        "auditor": b"""
def install(r5):
    r5.audit_updated = True
def audit(r5, seconds, *, emit=True):
    return {'fixture': True, 'window_seconds': seconds}
""",
    }
    catalogue.manifest["files"]["installer"]["sha256"] = hashlib.sha256(
        catalogue.code
    ).hexdigest()
    for name, code in components.items():
        catalogue.manifest["files"][name] = {
            "path": f"tools/{name}.py",
            "sha256": hashlib.sha256(code).hexdigest(),
        }
    original = client.downloader

    def download(url, limit=300_000):
        for name, code in components.items():
            if url.endswith(f"/tools/{name}.py"):
                return code
        return original(url, limit)

    client.downloader = download
    assert client.check()["update_available"] is True
    assert client.install()["status"] == "ready"
    assert client.r5.audit_updated is True
    assert client.r5.protection_repaired_fixture is True
    assert client.r5.protection_watch_fixture is True
    assert client.action("audit") == {
        "fixture": True,
        "window_seconds": 30,
        "backup_protection": {"status": "fixture"},
    }
    assert client.r5.events == [("install", "release-one")]
    assert client.installed()["manifest"]["version"] == "fixture-panel-audit"


def test_isolated_recovery_action_is_available_after_failed_install(runtime):
    client, _, _ = runtime
    client.diagnostic_module = SimpleNamespace(
        prepare_isolated_recovery=lambda context: {
            "status": "isolated_fork_prepared",
            "drive_modified": False,
            "api_started": False,
        }
    )
    client.diagnostic_context = {"r5": client.r5}
    client.last_error = "Continuidad educativa: sesión concluida retrocedida"
    assert client.module is None
    result = client.action("prepare_isolated_recovery")
    assert result == {
        "status": "isolated_fork_prepared",
        "drive_modified": False,
        "api_started": False,
    }
    with pytest.raises(RuntimeError, match="Arranque detenido"):
        client.action("save")


def test_passive_observer_reports_status_without_operational_buttons(runtime):
    client, catalogue, _ = runtime
    client.install()
    observations = []
    client.on_observation = observations.append
    client.diagnostic_module = SimpleNamespace(
        status=lambda context: {
            "bodega": "SQLite ok",
            "education_continuity": {"status": "regressed_blocked"},
        }
    )
    client.diagnostic_context = {}
    client.watch_once()
    assert len(client.r5.events) == 1
    assert catalogue.calls
    assert observations == [
        {
            "bodega": "SQLite ok",
            "education_continuity": {"status": "regressed_blocked"},
        }
    ]


def test_educational_recovery_is_automatic_guarded_and_idempotent(monkeypatch):
    calls = []
    center = SimpleNamespace(
        status=lambda: {"bodega": "SQLite ok / propietario validado"},
        prepare_isolated_recovery=lambda: (
            calls.append("fork")
            or {
                "status": "isolated_fork_prepared",
                "drive_modified": False,
                "original_bodega_overwritten": False,
                "learning_authorized": False,
            }
        ),
    )
    monkeypatch.setattr(adapter, "_center", lambda context: center)
    context = {"r5": object()}
    error = "RuntimeError: Continuidad educativa: sesión concluida retrocedida"
    first = adapter.recover(context, error)
    second = adapter.recover(context, error)
    assert calls == ["fork"]
    assert first == second
    assert first["status"] == "not_activated"
    assert first["memory_replaced_by_recovery"] is False
    assert first["isolated_recovery"]["status"] == "isolated_fork_prepared"
    assert first["isolated_recovery"]["learning_authorized"] is False


def test_unrelated_installer_failure_never_starts_recovery(monkeypatch):
    center = SimpleNamespace(
        status=dict,
        prepare_isolated_recovery=lambda: pytest.fail("unsafe fork"),
    )
    monkeypatch.setattr(adapter, "_center", lambda context: center)
    assert "isolated_recovery" not in adapter.recover(
        {"r5": object()}, "RuntimeError: invalid SHA"
    )


def test_educational_fork_failure_keeps_installation_blocked(monkeypatch):
    def fail_fork():
        raise RuntimeError("source backup not authenticated")

    center = SimpleNamespace(status=dict, prepare_isolated_recovery=fail_fork)
    monkeypatch.setattr(adapter, "_center", lambda context: center)
    record = adapter.recover(
        {"r5": object()}, "Continuidad educativa: sesión concluida retrocedida"
    )
    assert record["status"] == "not_activated"
    assert record["memory_replaced_by_recovery"] is False
    assert record["isolated_recovery"]["status"] == "isolated_recovery_blocked"
    assert record["isolated_recovery"]["drive_modified"] is False


def test_installer_preserves_read_only_inspection_without_running_actions():
    calls = []
    controls = [
        SimpleNamespace(description="Estado real"),
        SimpleNamespace(description="ENCENDER / ACTUALIZAR TRÍADE"),
        SimpleNamespace(description="Abrir Tríade"),
        SimpleNamespace(description="Guardar memoria"),
        SimpleNamespace(description="Ver circuito de aprendizaje"),
    ]
    widget_box = SimpleNamespace(children=tuple(controls))
    client = SimpleNamespace(view=(None, None, None, widget_box))

    # A bound method is how the Colab updater identifies its current view.
    class Owner:
        def __init__(self):
            self.view = client.view

        def progress(self, message):
            calls.append(message)

    owner = Owner()
    result = adapter._enforce_observation_panel({"progress": owner.progress})
    assert result == {"status": "lifecycle_and_open_controls", "visible_buttons": 4}
    assert widget_box.children == (
        controls[1],
        controls[2],
        controls[0],
        controls[4],
    )
    assert calls == []


def test_open_requires_a_verifiably_healthy_runtime(runtime):
    client, _, _ = runtime
    client.install()
    opened = []
    client.module = SimpleNamespace(
        verify=lambda context: client.r5.verified,
        open_frontend=lambda context: (
            opened.append("open") or {"status": "frontend_requested"}
        ),
    )
    client.r5.verified = False
    with pytest.raises(RuntimeError, match="Abrir Tríade bloqueado"):
        client.action("open_frontend")
    assert opened == []
    client.r5.verified = True
    assert client.action("open_frontend") == {"status": "frontend_requested"}
    assert opened == ["open"]


def test_legacy_controller_render_has_lifecycle_and_open_buttons():
    import inspect

    from tools import triade_colab_control_r7 as controller

    source = inspect.getsource(controller.render)
    assert 'button("Instalar / encender / actualizar", center.start' in source
    assert 'button("Abrir Tríade", open_verified_frontend' in source
    assert 'button("Guardar copia verificada"' not in source
    assert 'button("Auditar actividad real' not in source


def test_legacy_panel_preserves_safe_inspection_after_widget_refresh():
    callbacks = []

    class LegacyActions:
        def __init__(self):
            self.children = (
                SimpleNamespace(description="Estado real"),
                SimpleNamespace(description="ENCENDER / ACTUALIZAR TRÍADE"),
                SimpleNamespace(description="Abrir Tríade"),
                SimpleNamespace(description="Guardar memoria"),
            )

        def observe(self, fn, names):
            assert names == "children"
            callbacks.append(fn)

        def repaint(self, children):
            self.children = children
            for callback in callbacks:
                callback({"name": "children", "new": children})

    actions = LegacyActions()
    owner = SimpleNamespace(view=(None, None, None, actions))
    context = {"progress": SimpleNamespace(__self__=owner)}
    first = adapter._enforce_observation_panel(context)
    assert first["visible_buttons"] == 3
    assert len(callbacks) == 1
    original_controls = actions.children
    actions.repaint(
        (
            *original_controls,
            SimpleNamespace(description="Guardar memoria"),
            SimpleNamespace(description="Auditar actividad"),
        )
    )
    assert actions.children == original_controls
    # The permanent Colab notebook legitimately replaces the lifecycle button
    # with its verified release-refresh wrapper after installer completion.
    refreshed = SimpleNamespace(description="ENCENDER / ACTUALIZAR TRÍADE")
    actions.repaint(
        (refreshed, original_controls[1], SimpleNamespace(description="Auditar"))
    )
    assert actions.children == (
        refreshed,
        original_controls[1],
        original_controls[2],
    )
    # Reapplying release components must not duplicate the same hook.
    adapter._enforce_observation_panel(context)
    assert len(callbacks) == 1


def test_autonomous_audit_is_one_read_only_observer_and_cpu_bounded(monkeypatch):
    observations = []
    r5 = SimpleNamespace()
    auditor = SimpleNamespace(
        audit=lambda r5_arg, seconds, emit: (
            observations.append((r5_arg, seconds, emit))
            or {"audit_version": "schema-aware-2"}
        )
    )
    monkeypatch.setattr(adapter, "_auditor", lambda context: auditor)
    monkeypatch.setattr(adapter.os, "cpu_count", lambda: 4)
    monkeypatch.setattr(adapter.os, "getloadavg", lambda: (3.5, 1.0, 1.0))
    first = adapter._start_autonomous_monitor({"r5": r5}, interval_seconds=3600)
    try:
        assert first["status"] == "scheduled"
        assert first["cross_session_certified"] is False
        assert first["backup_writer_started"] is False
        second = adapter._start_autonomous_monitor({"r5": r5}, interval_seconds=3600)
        assert second["status"] == "already_running"
        handle = r5._triade_auto_ops
        handle["check"]()
        assert handle["state"]["status"] == "deferred_cpu_pressure"
        assert handle["state"]["cpu_count_observed"] == 4
        assert observations == []
        monkeypatch.setattr(adapter.os, "getloadavg", lambda: (0.8, 0.5, 0.1))
        handle["check"]()
        assert handle["state"]["status"] == "audited_read_only"
        assert handle["state"]["audit_version"] == "schema-aware-2"
        assert observations == [(r5, 15, False)]
        status = adapter._autonomous_monitor_status(r5)
        assert status["observer_alive"] is True
        assert status["cross_session_certified"] is False
    finally:
        r5._triade_auto_ops["stop"].set()
        r5._triade_auto_ops["thread"].join(timeout=2)
    assert adapter._autonomous_monitor_status(r5)["observer_alive"] is False


def test_small_colab_cpu_guard_is_automatic_and_does_not_restart(monkeypatch):
    for variable in (
        "TRIADE_WORKER_CONCURRENCY",
        "OLLAMA_NUM_PARALLEL",
        "OLLAMA_MAX_LOADED_MODELS",
        "OMP_NUM_THREADS",
    ):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(adapter.os, "sched_getaffinity", lambda pid: {0, 1})
    policy = adapter._configure_cpu_bootstrap({})
    assert policy["effective_cpu_count"] == 2
    assert policy["low_cpu_guard"] is True
    assert policy["worker_serialized"] is True
    assert policy["existing_service_restarted"] is False
    assert adapter.os.environ["TRIADE_WORKER_CONCURRENCY"] == "0"
    assert adapter.os.environ["OLLAMA_NUM_PARALLEL"] == "1"


def test_colab_cpu_guard_respects_explicit_override(monkeypatch):
    monkeypatch.setenv("TRIADE_WORKER_CONCURRENCY", "1")
    monkeypatch.setattr(adapter.os, "sched_getaffinity", lambda pid: {0, 1})
    policy = adapter._configure_cpu_bootstrap({})
    assert policy["worker_concurrency"] == "1"
    assert policy["worker_serialized"] is False


def test_colab_panel_has_audit_and_education_verification_buttons():
    """Restore bounded inspection actions without exposing learning_start."""
    import inspect

    source = inspect.getsource(updates.render)
    assert 'button("Estado real", lambda: client.action("status"))' in source
    assert (
        'button("Auditar actividad (30 s)", lambda: client.action("audit"))' in source
    )
    assert (
        'button("Verificar aprendizaje", lambda: client.action("learning_status"))'
        in source
    )
    assert 'button("Iniciar aprendizaje"' not in source
    assert 'button("Promover' not in source


def test_panel_inspection_actions_are_read_only_and_do_not_start_learning(runtime):
    """The three callbacks inspect an existing runtime, never advance a lesson."""
    client, _, _ = runtime
    client.install()
    calls = []
    client.diagnostic_module = None

    def inspect_status(context):
        calls.append("status")
        return {"status": "ready", "bodega": "SQLite ok"}

    def inspect_audit(context):
        calls.append("audit")
        return {"status": "audited_read_only", "seconds": 30}

    def inspect_learning(context):
        calls.append("learning_status")
        return {"status": "learning_observation_only", "certified": False}

    client.module = SimpleNamespace(
        status=inspect_status,
        audit=inspect_audit,
        learning_status=inspect_learning,
        learning_start=lambda context: pytest.fail("no automatic learning on click"),
    )
    assert client.action("status")["bodega"] == "SQLite ok"
    assert client.action("audit")["status"] == "audited_read_only"
    assert client.action("learning_status")["certified"] is False
    assert calls == ["status", "audit", "learning_status"]


def test_updating_live_colab_panel_restores_inspection_buttons_without_rerun(
    monkeypatch,
):
    """The old R7.17.19 observer must not remove newly restored diagnostics."""
    import sys

    class StubButton:
        def __init__(self, description, button_style="", layout=None):
            self.description = description
            self.callback = None

        def on_click(self, callback):
            self.callback = callback

        def click(self):
            assert self.callback is not None
            self.callback(None)

    class StubActions:
        def __init__(self, children):
            self.children = tuple(children)
            self._trait_notifiers = {"children": {"change": []}}

        def observe(self, callback, names):
            assert names == "children"
            self._trait_notifiers["children"]["change"].append(callback)

        def unobserve(self, callback, names):
            assert names == "children"
            self._trait_notifiers["children"]["change"].remove(callback)

        def repaint(self, children):
            self.children = tuple(children)
            for callback in list(self._trait_notifiers["children"]["change"]):
                callback({"name": "children"})

    monkeypatch.setitem(
        sys.modules,
        "ipywidgets",
        SimpleNamespace(
            Button=StubButton,
            Layout=lambda **kwargs: SimpleNamespace(**kwargs),
        ),
    )
    lifecycle = StubButton("ENCENDER / ACTUALIZAR TRÍADE")
    opener = StubButton("Abrir Tríade")
    box = StubActions((lifecycle, opener))
    output = SimpleNamespace(value="")
    calls = []

    class Owner:
        view = (None, None, None, box, None, None, output)

        def progress(self, message):
            raise AssertionError("Only a UI inspection should run")

        def action(self, name):
            calls.append(name)
            return {"action": name, "detail": "<verified>"}

    owner = Owner()

    # Mimic the previous two-button guard left in the same Colab kernel.
    def _enforce_observation_panel():
        def maintain_controls(change):
            if change.get("name") == "children":
                box.children = (lifecycle, opener)

        return maintain_controls

    old_guard = _enforce_observation_panel()
    box.observe(old_guard, names="children")
    box._triade_lifecycle_observer_installed = True
    result = adapter._enforce_observation_panel({"progress": owner.progress})

    assert result["visible_buttons"] == 5
    assert [b.description for b in box.children] == [
        "ENCENDER / ACTUALIZAR TRÍADE",
        "Abrir Tríade",
        "Estado real",
        "Auditar actividad (30 s)",
        "Verificar aprendizaje",
    ]
    assert calls == []
    assert old_guard not in box._trait_notifiers["children"]["change"]
    assert len(box._trait_notifiers["children"]["change"]) == 1

    box.children[2].click()
    box.children[3].click()
    box.children[4].click()
    assert calls == ["status", "audit", "learning_status"]
    assert "&lt;verified&gt;" in output.value
    assert "<verified>" not in output.value

    # Widget refresh may replace the lifecycle callback, not the inspections.
    refreshed = StubButton("ENCENDER / ACTUALIZAR TRÍADE")
    box.repaint((refreshed, *box.children[1:]))
    assert box.children[0] is refreshed
    assert len(box.children) == 5
    # Reinjection is idempotent across repeated installation attempts.
    second = adapter._enforce_observation_panel({"progress": owner.progress})
    assert second["visible_buttons"] == 5
    assert len(box._trait_notifiers["children"]["change"]) == 1


def test_separate_inspection_surface_survives_legacy_two_button_pruning():
    """The notebook can strip view[3] without hiding read-only diagnostics."""
    lifecycle = [
        SimpleNamespace(description="ENCENDER / ACTUALIZAR TRÍADE"),
        SimpleNamespace(description="Abrir Tríade"),
        SimpleNamespace(description="Guardar memoria"),
    ]
    inspections = [
        SimpleNamespace(description="Estado real"),
        SimpleNamespace(description="Auditar actividad (30 s)"),
        SimpleNamespace(description="Verificar aprendizaje"),
    ]
    primary = SimpleNamespace(children=tuple(lifecycle))
    secondary = SimpleNamespace(children=tuple(inspections))
    owner = SimpleNamespace(
        view=(None, None, None, primary, None, None, None),
        inspection_view=secondary,
    )
    context = {"progress": SimpleNamespace(__self__=owner)}

    first = adapter._enforce_observation_panel(context)
    assert first["visible_buttons"] == 5
    assert primary.children == tuple(lifecycle[:2])
    assert secondary.children == tuple(inspections)

    # Model a permanent notebook callback that rewrites only view[3].
    primary.children = tuple(lifecycle[:2])
    again = adapter._enforce_observation_panel(context)
    assert again["visible_buttons"] == 5
    assert secondary.children == tuple(inspections)


def test_separate_inspection_source_is_not_part_of_legacy_action_box():
    import inspect

    source = inspect.getsource(updates.render)
    assert "lifecycle_actions = [" in source
    assert "inspection_actions = [" in source
    assert "widgets.Box(\n            lifecycle_actions," in source
    assert "client.inspection_view = widgets.Box(" in source
    assert (
        "display(*client.view[:4], client.inspection_view, *client.view[4:])"
        in source
    )
