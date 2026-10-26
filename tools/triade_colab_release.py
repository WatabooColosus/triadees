"""First complete release adapter for the continuous Colab protocol.

The generic client has no knowledge of these internal compatibility steps.
Subsequent releases may replace this installer and all declared components
without changing the notebook or offering a button for each historical patch.
"""

from __future__ import annotations

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


def install(context):
    # A diagnostic-only release can attach to a verified running session.
    # Do not invoke dependency installation, restoration or guardian startup.
    if verify(context):
        context["progress"](
            "Actualizando el auditor del panel; Tríade sigue encendida…"
        )
        auditor = _auditor(context)
        if auditor is not None:
            auditor.install(context["r5"])
        return {
            "status": "ready",
            "dependencies": {"status": "existing_runtime_verified"},
            "runtime": {"state": "already_running_verified"},
        }
    dependencies = ensure_dependencies(context)
    context["progress"]("Instalando código, recuperando memoria e iniciando Tríade…")
    result = _center(context).start()
    if result.get("state") not in (
        "running_version_rehydrated",
        "already_running_verified",
    ):
        raise RuntimeError("El arranque no terminó verificado")
    auditor = _auditor(context)
    if auditor is not None:
        auditor.install(context["r5"])
    return {"status": "ready", "dependencies": dependencies, "runtime": result}


def verify(context):
    observed = _center(context).status()
    ready = bool(
        observed.get("api_http_200") is True
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
    return _center(context).status()


def save(context):
    return _center(context).save()


def audit(context):
    auditor = _auditor(context)
    if auditor is not None:
        return auditor.audit(context["r5"], 30, emit=False)
    return context["r5"].audit_progress(30)
