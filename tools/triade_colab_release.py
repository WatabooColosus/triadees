"""First complete release adapter for the continuous Colab protocol.

The generic client has no knowledge of these internal compatibility steps.
Subsequent releases may replace this installer and all declared components
without changing the notebook or offering a button for each historical patch.
"""

from __future__ import annotations

import ast
import datetime as dt
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
from pathlib import Path


def _download(url, limit):
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError("Descarga de dependencia demasiado grande")
    return data


def _node_major():
    if not shutil.which("node") or not shutil.which("npm"):
        return 0
    value = subprocess.check_output(
        ["node", "--version"], text=True, timeout=15
    ).strip()
    return int(value.lstrip("v").split(".")[0])


def ensure_dependencies(context):
    """Provision a stock Linux Colab, including an absent or old Node runtime."""
    r5, progress = context["r5"], context["progress"]
    progress("Comprobando e instalando dependencias de la sesión nueva…")
    needed = {"git": "git", "curl": "curl", "xz": "xz-utils", "zstd": "zstd"}
    missing = [
        package for command, package in needed.items() if not shutil.which(command)
    ]
    if missing:
        if not shutil.which("apt-get") or os.geteuid() != 0:
            raise RuntimeError(
                "Se necesita el entorno Linux estándar de Google Colab para instalar dependencias"
            )
        r5.run(["apt-get", "update", "-qq"], timeout=600)
        r5.run(["apt-get", "install", "-y", "ca-certificates", *missing], timeout=900)
    if _node_major() < 20:
        arch = {"x86_64": "x64", "aarch64": "arm64"}.get(platform.machine())
        if platform.system() != "Linux" or arch is None:
            raise RuntimeError("Arquitectura Colab no admitida para Node")
        releases = json.loads(
            _download("https://nodejs.org/dist/index.json", 3_000_000)
        )
        versions = [
            row["version"]
            for row in releases
            if re.fullmatch(r"v22\.[0-9]+\.[0-9]+", str(row.get("version", "")))
            and row.get("lts")
            and f"linux-{arch}" in row.get("files", [])
        ]
        if not versions:
            raise RuntimeError(
                "No se encontró una distribución oficial Node LTS compatible"
            )
        version = max(versions, key=lambda value: tuple(map(int, value[1:].split("."))))
        filename = f"node-{version}-linux-{arch}.tar.xz"
        origin = f"https://nodejs.org/dist/{version}/"
        sums = _download(origin + "SHASUMS256.txt", 100_000).decode()
        matches = [
            line.split()[0]
            for line in sums.splitlines()
            if len(line.split()) == 2 and line.split()[1] == filename
        ]
        if len(matches) != 1 or not re.fullmatch(r"[0-9a-f]{64}", matches[0]):
            raise RuntimeError("Node sin checksum oficial inequívoco")
        data = _download(origin + filename, 100_000_000)
        if hashlib.sha256(data).hexdigest() != matches[0]:
            raise RuntimeError("Descarga de Node con SHA divergente")
        parent = Path(r5.WORK) / "dependencies"
        parent.mkdir(parents=True, exist_ok=True)
        destination = parent / filename.removesuffix(".tar.xz")
        if destination.is_symlink():
            raise RuntimeError("Destino Node con enlace inseguro")
        if not destination.exists():
            with tempfile.TemporaryDirectory(dir=parent) as temporary:
                archive = Path(temporary) / filename
                archive.write_bytes(data)
                with tarfile.open(archive, "r:xz") as source:
                    source.extractall(temporary, filter="data")
                staged = Path(temporary) / filename.removesuffix(".tar.xz")
                if not (staged / "bin/node").is_file():
                    raise RuntimeError(
                        "Archivo Node no contiene el ejecutable esperado"
                    )
                os.replace(staged, destination)
        os.environ["PATH"] = (
            str(destination / "bin") + os.pathsep + os.environ.get("PATH", "")
        )
        if _node_major() < 20:
            raise RuntimeError("Node instalado no quedó operativo")
    if importlib.util.find_spec("pytest") is None:
        r5.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "pytest",
            ],
            timeout=600,
        )
    return {
        "git": bool(shutil.which("git")),
        "node_major": _node_major(),
        "zstd": bool(shutil.which("zstd")),
        "python": platform.python_version(),
    }


def _center(context):
    cached = context.get("center")
    if cached is not None:
        return cached
    path = Path(context["files"]["controller"])
    spec = importlib.util.spec_from_file_location(
        "triade_checked_release_controller", path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rehydrator = None
    if "rehydrator" in context["files"]:
        release_spec = importlib.util.spec_from_file_location(
            "triade_checked_rehydrator", context["files"]["rehydrator"]
        )
        release_module = importlib.util.module_from_spec(release_spec)
        release_spec.loader.exec_module(release_module)
        rehydrator = release_module.rehydrate
    center = module.Center(context["r5"], rehydrator=rehydrator)
    context["center"] = center
    return center


def _auditor(context):
    if "auditor" not in context.get("files", {}):
        return None
    if "auditor_module" not in context:
        spec = importlib.util.spec_from_file_location(
            "triade_checked_release_auditor", context["files"]["auditor"]
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        context["auditor_module"] = module
    return context["auditor_module"]


def _protection(context):
    if "protection" not in context.get("files", {}):
        return None
    if "protection_module" not in context:
        spec = importlib.util.spec_from_file_location(
            "triade_checked_backup_protection", context["files"]["protection"]
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        context["protection_module"] = module
    return context["protection_module"]


def _apply_router_patch(context):
    """Apply the verified router module to an already-running R5 session."""
    staged_path = context.get("files", {}).get("router")
    if not staged_path:
        return {"status": "not_declared", "restarted": False}
    r5 = context["r5"]
    root = Path(r5.ROOT).resolve()
    work = Path(r5.WORK).resolve()
    target = (root / "triade/models/model_router.py").resolve()
    staged = Path(staged_path).resolve()
    if (
        not target.is_file()
        or target.is_symlink()
        or not staged.is_file()
        or staged.is_symlink()
    ):
        raise RuntimeError("Ruta del router ausente o insegura")
    source = staged.read_bytes()
    ast.parse(source.decode("utf-8"), filename="triade/models/model_router.py")
    digest = hashlib.sha256(source).hexdigest()
    if target.read_bytes() == source:
        return {"status": "already_installed", "sha256": digest, "restarted": False}
    center = _center(context)
    if not center._origin_verified():
        raise RuntimeError("Checkout R5 no verificado; no sustituir el router")
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup = work / "actualizaciones" / "router_patch" / stamp
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(target, backup / "model_router.py")
    (backup / "before.sha256").write_text(
        hashlib.sha256(target.read_bytes()).hexdigest(), encoding="utf-8"
    )
    sys.path.insert(0, str(root))
    from tools.colab_service_lifecycle import stop_owned

    ownership = work / "api_ownership.json"
    stop_owned(root, ownership, port=8010)
    temporary = target.with_name(".model_router.py.r710tmp")
    if temporary.exists() or temporary.is_symlink():
        raise RuntimeError("Temporal de router existente en conflicto")
    try:
        fd = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(source)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise RuntimeError("SHA del router instalado no coincide")
        r5.start_real_backend()
        with urllib.request.urlopen(
            "http://127.0.0.1:8010/health/live", timeout=15
        ) as response:
            if response.status != 200:
                raise RuntimeError("API sin HTTP 200 después del parche del router")
    except Exception:
        if temporary.exists():
            temporary.unlink()
        shutil.copy2(backup / "model_router.py", target)
        try:
            r5.start_real_backend()
        except (OSError, RuntimeError, ValueError, TypeError) as rollback_error:
            context["progress"](
                "No se pudo reactivar la API tras el rollback: "
                + type(rollback_error).__name__
            )
        raise
    return {"status": "patched_and_restarted", "sha256": digest, "restarted": True}


def _apply_runtime_path_patches(context):
    """Apply immutable package-data path fixes to the verified R5 checkout."""
    components = {
        "worker_state_store": "triade/workers/state_store.py",
        "neuron_activity_schema": "triade/core/neuron_activity_store.py",
        "neuron_registry_schema": "triade/core/neuron_registry.py",
        "learning_pipeline_schema": "triade/learning/pipeline.py",
        "backup_key_resolution": "triade/memory/encrypted_backup.py",
        "mission_planner_backup_readiness": "triade/workers/mission_planner.py",
        "service_health_progress": "triade/runtime/service_health.py",
        "worker_serial_fallback": "triade/workers/background_service.py",
        "vital_chain_causal_introspection": "triade/observability/introspection.py",
        "vital_chain_recent_activity": "triade/observability/runtime_graph.py",
    }
    if "r5" not in context:
        return {"status": "not_applicable", "restarted": False}
    r5 = context["r5"]
    # Lightweight installer fixtures do not expose a real checkout. They
    # exercise the panel contract only and must not enter runtime patching.
    if not hasattr(r5, "ROOT") or not hasattr(r5, "WORK"):
        return {"status": "not_applicable", "restarted": False}
    root = Path(r5.ROOT).resolve()
    work = Path(r5.WORK).resolve()
    staged_files = context.get("files", {})
    prepared = []
    for name, relative in components.items():
        staged_path = staged_files.get(name)
        if not staged_path:
            continue
        target = (root / relative).resolve()
        staged = Path(staged_path).resolve()
        if (
            not target.is_file()
            or target.is_symlink()
            or not staged.is_file()
            or staged.is_symlink()
            or root not in target.parents
        ):
            raise RuntimeError("Componente de runtime ausente o inseguro: " + name)
        source = staged.read_bytes()
        ast.parse(source.decode("utf-8"), filename=relative)
        digest = hashlib.sha256(source).hexdigest()
        if target.read_bytes() != source:
            prepared.append((name, relative, target, source, digest))
    if not prepared:
        return {"status": "already_installed", "restarted": False}
    if not _center(context)._origin_verified():
        raise RuntimeError("Checkout R5 no verificado; no sustituir código de runtime")

    from tools.colab_service_lifecycle import stop_owned

    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup_root = work / "actualizaciones" / "runtime_path_patches" / stamp
    backup_root.mkdir(parents=True, exist_ok=False)
    ownership = work / "api_ownership.json"
    stop_owned(root, ownership, port=8010)
    installed = []
    try:
        for name, relative, target, source, digest in prepared:
            backup = backup_root / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
            temporary = target.with_name("." + target.name + ".triade-path-tmp")
            if temporary.exists() or temporary.is_symlink():
                raise RuntimeError("Temporal de runtime existente: " + name)
            fd = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(source)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise RuntimeError("SHA del runtime instalado no coincide: " + name)
            installed.append({"component": name, "path": relative, "sha256": digest})
        r5.start_real_backend()
        with urllib.request.urlopen(
            "http://127.0.0.1:8010/health/live", timeout=15
        ) as response:
            if response.status != 200:
                raise RuntimeError("API sin HTTP 200 después de parches de runtime")
    except Exception:
        for _, relative, target, _, _ in prepared:
            backup = backup_root / relative
            if backup.is_file():
                shutil.copy2(backup, target)
        try:
            r5.start_real_backend()
        except (OSError, RuntimeError, ValueError, TypeError):
            pass
        raise
    return {
        "status": "patched_and_restarted",
        "restarted": True,
        "components": installed,
    }


def _learning(context):
    if "learning" not in context.get("files", {}):
        return None
    if "learning_module" not in context:
        spec = importlib.util.spec_from_file_location(
            "triade_checked_prospective_learning", context["files"]["learning"]
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        context["learning_module"] = module
    return context["learning_module"]


def _record_learning_launch(context, launch):
    """Record the latest study preflight without persisting model output or keys."""
    status = str(launch.get("status") or "unknown")[:80]
    reason = (
        str(launch.get("reason") or "")[:200]
        if status == "blocked"
        else str(launch.get("error_type") or "")[:80]
    )
    receipt = {
        "status": status,
        "reason": reason,
        "at": dt.datetime.now(dt.UTC).isoformat(),
    }
    probe = context.get("embedding_probe")
    if isinstance(probe, dict):
        # Explicit allowlist: no request text, raw backend errors, model keys,
        # vectors or environment variables can enter this receipt.
        receipt["embedding_probe"] = {
            "status": "passed" if probe.get("status") == "passed" else "failed",
            "failure_code": str(probe.get("failure_code") or "")[:60],
            "dimensions": int(probe.get("dimensions") or 0),
            "vector_count": int(probe.get("vector_count") or 0),
            "attempts": int(probe.get("attempts") or 0),
        }
    try:
        _protection(context)._json(
            Path(context["r5"].WORK) / "prospective_launch.json", receipt
        )
    except (OSError, RuntimeError, ValueError, TypeError):
        # A diagnostic receipt must not make a healthy installation fail.
        context["progress"]("Aviso: estado de inicio educativo no persistido")
    return receipt


def _enforce_observation_panel(context):
    """Keep lifecycle/open and already-wired read-only inspection controls.

    The installer can be loaded by an older Colab bootstrap that still owns
    its previous widgets. Only known inspection labels are kept; legacy
    save, recovery and manual learning-action buttons remain hidden. This
    changes only the displayed controls and never invokes their callbacks.
    """
    client = getattr(context.get("progress"), "__self__", None)
    view = getattr(client, "view", None)
    if not view or len(view) < 4:
        return {"status": "panel_not_available"}
    actions = view[3]
    children = getattr(actions, "children", None)
    if children is None:
        return {"status": "non_widget_panel_unchanged"}

    # R7.17.19 installed an observer which hides all inspection buttons.
    # Unregister ONLY that known callback before upgrading its policy.
    # Never unregister unrelated notebook observers or touch the runtime.
    if (
        getattr(actions, "_triade_lifecycle_observer_installed", False)
        and getattr(actions, "_triade_inspection_guard_version", 0) != 2
    ):
        all_notifiers = getattr(actions, "_trait_notifiers", {}) or {}
        handlers = all_notifiers.get("children", {}).get("change", ())
        removed = 0
        for handler in tuple(handlers):
            if (
                getattr(handler, "__name__", "") == "maintain_controls"
                and "_enforce_observation_panel" in getattr(handler, "__qualname__", "")
                and callable(getattr(actions, "unobserve", None))
            ):
                actions.unobserve(handler, names="children")
                removed += 1
        if not removed:
            return {
                "status": "panel_refresh_required",
                "visible_buttons": len(children),
            }
        actions._triade_lifecycle_observer_installed = False
    chosen = None
    for item in children:
        label = str(getattr(item, "description", "")).lower()
        if (
            "instalar" in label
            or "encender" in label
            or "iniciar última versión" in label
        ):
            chosen = item
            break
    if chosen is None:
        return {"status": "lifecycle_control_not_found"}
    opener = next(
        (
            item
            for item in children
            if "abrir tr" in str(getattr(item, "description", "")).lower()
        ),
        None,
    )
    # Preserve only the already-wired read-only diagnostics. Do not fabricate
    # widget callbacks: the permanent panel supplies the guarded actions.
    safe_inspections = {
        "estado real",
        "auditar actividad (30 s)",
        "verificar aprendizaje",
        "ver circuito de aprendizaje",
    }
    diagnostics = tuple(
        item
        for item in children
        if str(getattr(item, "description", "")).strip().lower() in safe_inspections
    )
    # The new client renders diagnostics in a separate box, outside the
    # legacy lifecycle widget that may be pruned by the permanent notebook.
    # Keep this independent surface rather than reinjecting duplicate buttons
    # into the guarded lifecycle box.
    separate_controls = tuple(
        getattr(getattr(client, "inspection_view", None), "children", ())
    )
    separate_labels = {
        str(getattr(item, "description", "")).strip().lower()
        for item in separate_controls
    }
    separate_inspections = len(separate_controls) == 3 and separate_labels == {
        "estado real",
        "auditar actividad (30 s)",
        "verificar aprendizaje",
    }
    if separate_inspections:
        diagnostics = ()

    # Updating an already-open Colab session must restore the buttons without
    # asking the owner to run a new cell. The verified Client supplies only
    # read-only callbacks and displays escaped JSON in its existing output.
    if (
        not separate_inspections
        and len(view) >= 7
        and callable(getattr(client, "action", None))
        and hasattr(view[-1], "value")
    ):
        try:
            import ipywidgets as widgets
        except ImportError:
            widgets = None
        if widgets is not None:
            current_labels = {
                str(getattr(item, "description", "")).strip().lower()
                for item in diagnostics
            }
            for label, method in (
                ("Estado real", "status"),
                ("Auditar actividad (30 s)", "audit"),
                ("Verificar aprendizaje", "learning_status"),
            ):
                if label.lower() in current_labels:
                    continue
                control = widgets.Button(
                    description=label,
                    layout=widgets.Layout(width="300px", height="44px"),
                )

                def inspect_clicked(_button, action=method):
                    try:
                        result = client.action(action)
                        rendered = json.dumps(
                            result, ensure_ascii=False, indent=2, default=str
                        )
                    except Exception as exc:  # noqa: BLE001 - existing UI diagnostic boundary
                        rendered = (
                            "Inspección no acreditada: "
                            + type(exc).__name__
                            + " "
                            + str(exc)[:1500]
                        )
                    from html import escape

                    view[-1].value = (
                        "<pre style='white-space:pre-wrap;overflow-wrap:anywhere'>"
                        + escape(rendered)
                        + "</pre>"
                    )

                control.on_click(inspect_clicked)
                diagnostics += (control,)
    allowed = ((chosen, opener) if opener is not None else (chosen,)) + diagnostics
    actions.children = allowed
    # Legacy notebooks may repopulate the SAME widget after installation.
    # A single observer keeps lifecycle controls stable without invoking them.
    observer = getattr(actions, "observe", None)
    if callable(observer) and not getattr(
        actions, "_triade_lifecycle_observer_installed", False
    ):

        def maintain_controls(change):
            nonlocal allowed
            if change.get("name") != "children":
                return
            current = tuple(getattr(actions, "children", ()))
            # The trusted notebook may REPLACE the lifecycle button with its
            # release-refresh wrapper. Keep that replacement, not the stale
            # button from before the notebook attached its click handler.
            replacement = next(
                (
                    item
                    for item in current
                    if item is not chosen
                    and (
                        "encender" in str(getattr(item, "description", "")).lower()
                        or "instalar" in str(getattr(item, "description", "")).lower()
                    )
                ),
                None,
            )
            if replacement is not None and current and current[0] is replacement:
                allowed = (
                    (replacement, opener) if opener is not None else (replacement,)
                ) + diagnostics
            if current != allowed:
                actions.children = allowed

        observer(maintain_controls, names="children")
        actions._triade_lifecycle_observer_installed = True
        actions._triade_inspection_guard_version = 2
    return {
        "status": "lifecycle_and_open_controls",
        "visible_buttons": len(actions.children)
        + (len(separate_controls) if separate_inspections else 0),
    }


def _start_autonomous_monitor(context, *, interval_seconds=600):
    """One low-impact read-only audit loop; never restores or promotes memory.

    The canonical guardian and the encrypted-copy watcher are independent
    backend-owned services. This observer must not create a second writer.
    """
    r5 = context["r5"]
    previous = getattr(r5, "_triade_auto_ops", None)
    if previous is not None:
        thread = previous.get("thread")
        if thread is not None and thread.is_alive():
            return {"status": "already_running", "single_observer": True}
    auditor = _auditor(context)
    if auditor is None:
        return {"status": "auditor_unavailable"}
    stop = threading.Event()
    state = {
        "status": "scheduled",
        "single_observer": True,
        "interval_seconds": interval_seconds,
        "audit_read_only": True,
        "backup_writer_started": False,
        "cross_session_certified": False,
    }

    def check():
        cpus = os.cpu_count() or 1
        try:
            load = os.getloadavg()[0]
        except (AttributeError, OSError):
            load = None
        state["cpu_count_observed"] = cpus
        state["loadavg_1m"] = round(load, 2) if load is not None else None
        # OS load average is a run-queue proxy, not a claim of CPU percentage.
        # High pressure defers optional read-only audit, not memory safety.
        if load is not None and load >= cpus * 0.75:
            state["status"] = "deferred_cpu_pressure"
            return
        try:
            result = auditor.audit(r5, 15, emit=False)
            state["status"] = "audited_read_only"
            state["last_audit_at"] = time.time()
            state["audit_version"] = result.get("audit_version")
            state["audit_error"] = None
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            state["status"] = "audit_deferred"
            state["audit_error"] = type(exc).__name__

    def observe():
        # Do not compete with initial model loading, guardian or startup.
        while not stop.wait(interval_seconds):
            check()

    thread = threading.Thread(
        target=observe, name="triade-low-resource-auto-audit", daemon=True
    )
    r5._triade_auto_ops = {
        "stop": stop,
        "thread": thread,
        "state": state,
        "check": check,
    }
    thread.start()
    return dict(state)


def _autonomous_monitor_status(r5):
    handle = getattr(r5, "_triade_auto_ops", None)
    if not handle:
        return {"status": "not_started"}
    state = dict(handle["state"])
    state["observer_alive"] = bool(
        handle["thread"].is_alive() and not handle["stop"].is_set()
    )
    return state


def _attach_panel_components(context):
    context["panel_policy"] = _enforce_observation_panel(context)
    auditor = _auditor(context)
    if auditor is not None:
        auditor.install(context["r5"])
    protection = _protection(context)
    if protection is None:
        return None
    context["progress"](
        "Reparando referencia de clave y verificando copia cifrada en Drive…"
    )
    result = protection.repair(context["r5"])
    protection.start_watch(context["r5"])
    learning = _learning(context)
    if learning is not None:
        context["learning_controls"] = learning.attach(context)
        # El aprendizaje verificado pertenece al ciclo continuo de Tríade.
        # Arrancarlo al montar el runtime evita que una acción manual sea la
        # condición de entrada; las compuertas de evidencia siguen decidiendo
        # si alguna sesión puede avanzar o aplicarse.
        try:
            result["learning"] = learning_start(context)
        except Exception as exc:  # noqa: BLE001 - panel reports a guarded block
            result["learning"] = {
                "status": "automatic_learning_blocked",
                "error_type": type(exc).__name__,
            }
        _record_learning_launch(context, result["learning"])
    result["autonomous_monitor"] = _start_autonomous_monitor(context)
    return result


def _configure_cpu_bootstrap(context):
    """Conservative worker pool on small Colab runtimes; no live service restart."""
    try:
        cores = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        cores = os.cpu_count() or 1
    cores = max(1, cores)
    low_cpu = cores <= 2
    if low_cpu:
        os.environ.setdefault("TRIADE_WORKER_CONCURRENCY", "0")
        os.environ.setdefault("OLLAMA_NUM_PARALLEL", "1")
        os.environ.setdefault("OLLAMA_MAX_LOADED_MODELS", "1")
        os.environ.setdefault("OMP_NUM_THREADS", "1")
    return {
        "effective_cpu_count": cores,
        "low_cpu_guard": low_cpu,
        "worker_concurrency": os.environ.get("TRIADE_WORKER_CONCURRENCY", "1"),
        "worker_serialized": os.environ.get("TRIADE_WORKER_CONCURRENCY") == "0",
        "existing_service_restarted": False,
    }


def install(context):
    context["cpu_policy"] = _configure_cpu_bootstrap(context)
    # A diagnostic-only release can attach to a verified running session.
    # Do not invoke dependency installation, restoration or guardian startup.
    if verify(context):
        context["progress"](
            "Actualizando el auditor del panel; Tríade sigue encendida…"
        )
        runtime_patches = _apply_runtime_path_patches(context)
        context["require_runtime_patch_verification"] = True
        router_patch = _apply_router_patch(context)
        protection = _attach_panel_components(context)
        return {
            "status": "ready",
            "dependencies": {"status": "existing_runtime_verified"},
            "runtime": {"state": "already_running_verified"},
            "runtime_path_patches": runtime_patches,
            "router_patch": router_patch,
            "backup_protection": protection,
        }
    dependencies = ensure_dependencies(context)
    context["progress"]("Instalando código, recuperando memoria e iniciando Tríade…")
    result = _center(context).start()
    if result.get("state") not in (
        "running_version_rehydrated",
        "already_running_verified",
    ):
        raise RuntimeError("El arranque no terminó verificado")
    runtime_patches = _apply_runtime_path_patches(context)
    context["require_runtime_patch_verification"] = True
    router_patch = _apply_router_patch(context)
    protection = _attach_panel_components(context)
    return {
        "status": "ready",
        "dependencies": dependencies,
        "runtime": result,
        "runtime_path_patches": runtime_patches,
        "router_patch": router_patch,
        "backup_protection": protection,
    }


def _runtime_patches_match(context):
    """Verify only the explicitly supplied runtime patches after installation."""
    if not context.get("require_runtime_patch_verification"):
        return True
    r5 = context["r5"]
    mapping = {
        "worker_state_store": "triade/workers/state_store.py",
        "neuron_activity_schema": "triade/core/neuron_activity_store.py",
        "neuron_registry_schema": "triade/core/neuron_registry.py",
        "learning_pipeline_schema": "triade/learning/pipeline.py",
        "backup_key_resolution": "triade/memory/encrypted_backup.py",
        "mission_planner_backup_readiness": "triade/workers/mission_planner.py",
        "service_health_progress": "triade/runtime/service_health.py",
        "worker_serial_fallback": "triade/workers/background_service.py",
        "vital_chain_causal_introspection": "triade/observability/introspection.py",
        "vital_chain_recent_activity": "triade/observability/runtime_graph.py",
    }
    for name, relative in mapping.items():
        staged = context.get("files", {}).get(name)
        if staged is None:
            continue
        installed = Path(r5.ROOT) / relative
        source = Path(staged)
        if (
            not installed.is_file()
            or installed.is_symlink()
            or not source.is_file()
            or source.is_symlink()
            or installed.read_bytes() != source.read_bytes()
        ):
            return False
    return True


def verify(context):
    router_path = context.get("files", {}).get("router")
    router_ok = True
    if router_path:
        live_router = Path(context["r5"].ROOT) / "triade/models/model_router.py"
        router_ok = bool(
            Path(router_path).is_file()
            and live_router.is_file()
            and live_router.read_bytes() == Path(router_path).read_bytes()
        )
    observed = _center(context).status()
    ready = bool(
        router_ok
        and _runtime_patches_match(context)
        and observed.get("api_http_200") is True
        and observed.get("ollama_http_200") is True
        and observed.get("bodega", "").startswith("SQLite ok")
        and observed.get("known_regression") is None
        and (observed.get("education_continuity") or {}).get("status")
        != "regressed_blocked"
        and observed.get("release", "").startswith("R6.3.1 candidata")
    )
    if ready:
        context["verified_counts"] = dict(observed["counts"])
    return ready


def resume(context):
    return _center(context).resume_verified(context.get("verified_counts"))


def recover(context, error):
    """Fail closed; autonomously prepare an offline forensic fork if needed.

    This action is explicitly limited to an educational lineage regression.
    It never starts Tríade, changes Drive, replaces the active DB, or resolves
    a historical study by inference.
    """
    result = {
        "status": "not_activated",
        "memory_replaced_by_recovery": False,
        "reason": error,
        "observed": _center(context).status(),
        "panel_policy": _enforce_observation_panel(context),
    }
    if "Continuidad educativa:" not in error:
        return result
    previous = context.get("isolated_recovery_receipt")
    if previous is not None:
        result["isolated_recovery"] = previous
        return result
    try:
        isolated = prepare_isolated_recovery(context)
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        isolated = {
            "status": "isolated_recovery_blocked",
            "failure_type": type(exc).__name__,
            "reason": str(exc)[:260],
            "original_bodega_overwritten": False,
            "drive_modified": False,
        }
    context["isolated_recovery_receipt"] = isolated
    result["isolated_recovery"] = isolated
    return result


def open_frontend(context):
    if verify(context) is not True:
        raise RuntimeError(
            "Abrir Tríade bloqueado: API, Ollama, identidad y versión "
            "deben estar verificadas"
        )
    context["r5"].open_frontend()
    return {"status": "frontend_requested"}


def status(context):
    result = _center(context).status()
    result["autonomous_monitor"] = _autonomous_monitor_status(context["r5"])
    result["cpu_policy"] = context.get("cpu_policy", {"status": "not_observed"})
    protection = _protection(context)
    if protection is not None:
        result["backup_protection"] = protection.status(context["r5"])
    learning = _learning(context)
    if learning is not None:
        result["learning_circuit"] = learning.inspect(context["r5"])
    return result


def prepare_isolated_recovery(context):
    """Stage an offline local fork even when normal installation is blocked."""
    return _center(context).prepare_isolated_recovery()


def save(context):
    return _center(context).save()


def audit(context):
    auditor = _auditor(context)
    if auditor is not None:
        result = auditor.audit(context["r5"], 30, emit=False)
        protection = _protection(context)
        if protection is not None:
            result["backup_protection"] = protection.status(context["r5"])
        learning = _learning(context)
        if learning is not None:
            result["learning_circuit"] = learning.inspect(context["r5"])
        return result
    return context["r5"].audit_progress(30)


def learning_status(context):
    learning = _learning(context)
    if learning is None:
        raise RuntimeError("Esta publicación no incluye aprendizaje prospectivo")
    return learning.inspect(context["r5"])


def learning_start(context):
    context.pop("embedding_probe", None)
    learning = _learning(context)
    if learning is None:
        raise RuntimeError("Esta publicación no incluye aprendizaje prospectivo")
    r5 = context["r5"]
    r5._owner_account_status(r5.DB)
    _protection(context)._backend_environment(r5)
    previous = getattr(r5, "_prospective_learning_monitor", None)
    if previous and previous["thread"].is_alive():
        return {"status": "study_already_running"}
    try:
        models = learning.prepare_models(context)
    except learning.NotReady as exc:
        return {"status": "blocked", "reason": str(exc), "learned": False}
    return {"models": models, **learning.start(context)}
