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


def _attach_panel_components(context):
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
    return result


def install(context):
    # A diagnostic-only release can attach to a verified running session.
    # Do not invoke dependency installation, restoration or guardian startup.
    if verify(context):
        context["progress"](
            "Actualizando el auditor del panel; Tríade sigue encendida…"
        )
        router_patch = _apply_router_patch(context)
        protection = _attach_panel_components(context)
        return {
            "status": "ready",
            "dependencies": {"status": "existing_runtime_verified"},
            "runtime": {"state": "already_running_verified"},
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
    router_patch = _apply_router_patch(context)
    protection = _attach_panel_components(context)
    return {
        "status": "ready",
        "dependencies": dependencies,
        "runtime": result,
        "router_patch": router_patch,
        "backup_protection": protection,
    }


def verify(context):
    router_path = context.get("files", {}).get("router")
    live_router = Path(context["r5"].ROOT) / "triade/models/model_router.py"
    router_ok = not router_path or bool(
        Path(router_path).is_file()
        and live_router.is_file()
        and live_router.read_bytes() == Path(router_path).read_bytes()
    )
    observed = _center(context).status()
    ready = bool(
        router_ok
        and observed.get("api_http_200") is True
        and observed.get("ollama_http_200") is True
        and observed.get("bodega", "").startswith("SQLite ok")
        and observed.get("known_regression") is None
        and observed.get("release", "").startswith("R6.3.1 candidata")
    )
    if ready:
        context["verified_counts"] = dict(observed["counts"])
    return ready


def resume(context):
    return _center(context).resume_verified(context.get("verified_counts"))


def recover(context, error):
    # Existing guarded installers preserve their pre-change backups. Do not
    # manufacture a rollback of user memory or certify a failed installation.
    return {
        "status": "not_activated",
        "memory_replaced_by_recovery": False,
        "reason": error,
        "observed": _center(context).status(),
    }


def open_frontend(context):
    context["r5"].open_frontend()
    return {"status": "frontend_requested"}


def status(context):
    result = _center(context).status()
    protection = _protection(context)
    if protection is not None:
        result["backup_protection"] = protection.status(context["r5"])
    learning = _learning(context)
    if learning is not None:
        result["learning_circuit"] = learning.inspect(context["r5"])
    return result


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
