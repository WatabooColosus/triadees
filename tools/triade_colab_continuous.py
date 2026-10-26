"""Version-independent Colab release client; Drive is memory, Git is code.

The channel is a mutable catalogue. Every executable file is fetched from its
immutable commit, hash checked and gated on completed CI for that commit.
Opening the panel only watches the catalogue. Installation is one transaction
from an empty VM or an existing runtime; no numbered update buttons.
"""

from __future__ import annotations

import ast
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path, PurePosixPath

REPO = "WatabooColosus/triadees"
CHANNEL = (
    f"https://raw.githubusercontent.com/{REPO}/colab-releases/"
    "releases/colab-channel.json"
)
REQUIRED_CI = frozenset({"Runtime Truth CI", "Python Tests", "Tríade Tests"})
PROTOCOL = 1
_SHA = re.compile(r"[0-9a-f]{40}")
_HASH = re.compile(r"[0-9a-f]{64}")
_active_client = None


def fetch(url, limit=300_000):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "triade-colab-continuous/1",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError("Respuesta de actualización demasiado grande")
    return data


def validate_manifest(value):
    if not isinstance(value, dict):
        raise TypeError("Catálogo de versiones inválido")
    if (
        value.get("schema") != "triade.colab.release.v1"
        or value.get("repository") != REPO
        or type(value.get("protocol")) is not int
        or value.get("protocol") != PROTOCOL
        or type(value.get("sequence")) is not int
        or value["sequence"] < 1
        or not _SHA.fullmatch(str(value.get("commit", "")))
        or not isinstance(value.get("version"), str)
        or not 0 < len(value["version"]) <= 100
        or value.get("channel") not in ("candidate", "stable")
        or type(value.get("auto_update_safe")) is not bool
    ):
        raise ValueError("La publicación no cumple el protocolo del actualizador")
    files = value.get("files")
    if (
        not isinstance(files, dict)
        or not 1 <= len(files) <= 20
        or "installer" not in files
    ):
        raise ValueError("Publicación sin instalador completo")
    paths = set()
    for name, record in files.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", name) or not isinstance(
            record, dict
        ):
            raise ValueError("Componente inválido")
        path = record.get("path")
        if not isinstance(path, str):
            raise TypeError("Ruta de publicación inválida")
        parts = PurePosixPath(path)
        if (
            parts.is_absolute()
            or not re.fullmatch(r"tools/[A-Za-z0-9_./-]+\.py", path)
            or ".." in parts.parts
            or "\\" in path
            or parts.as_posix() != path
            or not path.startswith("tools/")
            or not path.endswith(".py")
            or path in paths
            or not _HASH.fullmatch(str(record.get("sha256", "")))
        ):
            raise ValueError("Ruta o SHA de publicación inválidos")
        paths.add(path)
    return value


def release_identity(manifest):
    public = {
        key: manifest[key]
        for key in ("protocol", "sequence", "version", "commit", "files")
    }
    return hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest()


def verify_ci(manifest, downloader=fetch):
    url = (
        f"https://api.github.com/repos/{REPO}/actions/runs"
        f"?head_sha={manifest['commit']}&event=push&per_page=100"
    )
    payload = json.loads(downloader(url, 2_000_000))
    latest = {}
    for run in payload.get("workflow_runs", []):
        if run.get("head_sha") != manifest["commit"] or run.get("event") != "push":
            continue
        name = run.get("name")
        rank = (run.get("run_number", 0), run.get("run_attempt", 0), run.get("id", 0))
        if name not in latest or rank > latest[name][0]:
            latest[name] = (rank, run)
    missing = [
        name
        for name in sorted(REQUIRED_CI)
        if name not in latest
        or latest[name][1].get("status") != "completed"
        or latest[name][1].get("conclusion") != "success"
    ]
    if missing:
        raise RuntimeError("Versión aún no aprobada por CI: " + ", ".join(missing))
    return {name: latest[name][1]["id"] for name in sorted(REQUIRED_CI)}


def read_record(path):
    if path.is_symlink():
        raise RuntimeError("Estado de actualización con enlace inesperado")
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("Estado de actualización inválido")
    return value


def write_record(path, value):
    if path.is_symlink() or path.parent.is_symlink():
        raise RuntimeError("Destino de estado inseguro")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=".release-",
        suffix=".partial",
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, ensure_ascii=False, indent=2)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class Client:
    def __init__(
        self, r5, *, mount_drive, drive_ready, work=None, downloader=fetch, notify=None
    ):
        self.r5 = r5
        self.mount_drive = mount_drive
        self.drive_ready = drive_ready
        self.work = Path(work or "/content/triade_actualizador")
        self.downloader = downloader
        self.notify = notify or (lambda message: None)
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None
        self.auto_apply = False
        self.last_check = None
        self.last_error = None
        self.failed_release = None
        self.module = None
        self.context = None

    @property
    def drive_receipt(self):
        return Path(self.r5.BASE) / "operacion_colab_continua" / "installed.json"

    def installed(self):
        local = read_record(self.work / "installed.json")
        remote = read_record(self.drive_receipt) if self.drive_ready() else None
        choices = [record for record in (local, remote) if record]
        for record in choices:
            validate_manifest(record.get("manifest"))
            if record.get("identity") != release_identity(record["manifest"]):
                raise RuntimeError("Recibo de versión inconsistente")
        if (
            len(choices) == 2
            and choices[0]["manifest"]["sequence"] == choices[1]["manifest"]["sequence"]
            and choices[0]["identity"] != choices[1]["identity"]
        ):
            raise RuntimeError("Dos publicaciones distintas usan la misma secuencia")
        return max(choices, key=lambda item: item["manifest"]["sequence"], default=None)

    def check(self):
        with self.lock:
            manifest = validate_manifest(json.loads(self.downloader(CHANNEL)))
            installed = self.installed()
            if installed:
                old = installed["manifest"]
                if manifest["sequence"] < old["sequence"]:
                    raise RuntimeError(
                        "El canal retrocede: se conserva la versión instalada"
                    )
                if (
                    manifest["sequence"] == old["sequence"]
                    and release_identity(manifest) != installed["identity"]
                ):
                    raise RuntimeError("Publicación modificada sin aumentar secuencia")
            ci = verify_ci(manifest, self.downloader)
            result = {
                "checked_at": dt.datetime.now(dt.UTC).isoformat(),
                "manifest": manifest,
                "ci": ci,
                "update_available": not installed
                or installed["identity"] != release_identity(manifest),
                "installed_version": installed["manifest"]["version"]
                if installed
                else None,
            }
            self.last_check = result
            self.last_error = None
            self.notify(
                "Disponible: "
                + manifest["version"]
                + " · CI aprobada · "
                + dt.datetime.now(dt.UTC).strftime("%H:%M:%S UTC")
            )
            return result

    def _stage(self, manifest):
        destination = self.work / "packages" / release_identity(manifest)
        if destination.is_symlink():
            raise RuntimeError("Carpeta de publicación insegura")
        destination.mkdir(parents=True, exist_ok=True)
        files = {}
        # Check every component before importing or executing any of them.
        for name, record in manifest["files"].items():
            data = self.downloader(
                f"https://raw.githubusercontent.com/{REPO}/{manifest['commit']}/{record['path']}"
            )
            if hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise RuntimeError("SHA de componente no coincide: " + name)
            ast.parse(data.decode("utf-8"), filename=record["path"])
            path = destination / (name + ".py")
            if path.is_symlink() or (path.exists() and path.read_bytes() != data):
                raise RuntimeError("Conflicto de código local: " + name)
            if not path.exists():
                with path.open("xb") as stream:
                    stream.write(data)
            files[name] = str(path)
        name = "triade_release_" + release_identity(manifest)
        spec = importlib.util.spec_from_file_location(name, files["installer"])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
            if not all(
                callable(getattr(module, fn, None))
                for fn in ("install", "verify", "recover")
            ):
                raise RuntimeError("Instalador sin contrato install/verify/recover")
        except BaseException:
            sys.modules.pop(name, None)
            raise
        context = {
            "r5": self.r5,
            "files": files,
            "manifest": manifest,
            "progress": self.notify,
        }
        return module, context

    def install(self):
        with self.lock:
            # Mount and read the persistent receipt BEFORE resolving a release:
            # an empty Colab must not silently downgrade the last Drive version.
            self.mount_drive()
            if not self.drive_ready():
                raise RuntimeError("Drive no quedó montado; instalación detenida")
            result = self.check()
            manifest = result["manifest"]
            self.notify("Preparando instalación completa: " + manifest["version"])
            module, context = self._stage(manifest)
            try:
                installed = module.install(context)
                verified = module.verify(context)
                if (
                    not isinstance(installed, dict)
                    or installed.get("status") != "ready"
                    or verified is not True
                ):
                    raise RuntimeError("La versión no acreditó su arranque real")
            except Exception as exc:
                self.failed_release = release_identity(manifest)
                self.last_error = type(exc).__name__ + ": " + str(exc)[:300]
                recovery = module.recover(context, self.last_error)
                self.notify(
                    "Instalación incompleta; se conservaron los registros y la memoria"
                )
                raise RuntimeError(
                    f"No se activó la publicación: {self.last_error}; recuperación: {recovery}"
                ) from exc
            record = {
                "installed_at": dt.datetime.now(dt.UTC).isoformat(),
                "manifest": manifest,
                "identity": release_identity(manifest),
                "ci": result["ci"],
                "installation": installed,
            }
            # Drive first: local success alone must not promise persistence.
            write_record(self.drive_receipt, record)
            write_record(self.work / "installed.json", record)
            self.module, self.context = module, context
            self.last_error = None
            self.failed_release = None
            self.notify(
                "Instalación / actualización verificada: " + manifest["version"]
            )
            return {
                "status": "ready",
                "version": manifest["version"],
                "result": installed,
            }

    def watch_once(self):
        if not self.lock.acquire(blocking=False):
            return
        try:
            result = self.check()
            manifest = result["manifest"]
            if (
                not self.stop_event.is_set()
                and self.auto_apply
                and self.drive_ready()
                and self.installed()
                and result["update_available"]
                and self.failed_release != release_identity(manifest)
                and manifest["channel"] == "stable"
                and manifest["auto_update_safe"] is True
            ):
                self.install()
        except Exception as exc:  # noqa: BLE001 - background boundary reports and survives release failures
            self.last_error = type(exc).__name__ + ": " + str(exc)[:300]
            self.notify("Comprobación pendiente: " + self.last_error)
        finally:
            self.lock.release()

    def start_watch(self, seconds=600):
        if self.thread and self.thread.is_alive():
            return self.thread
        self.stop_event.clear()

        def watch():
            while not self.stop_event.is_set():
                self.watch_once()
                self.stop_event.wait(seconds)

        self.thread = threading.Thread(
            target=watch, name="triade-release-watch", daemon=True
        )
        self.thread.start()
        return self.thread

    def stop_watch(self):
        self.stop_event.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=1)

    def action(self, name):
        if not self.module:
            raise RuntimeError("Pulsa Instalar / encender / actualizar primero")
        callback = getattr(self.module, name, None)
        if not callable(callback):
            raise TypeError("Esta versión no ofrece la acción: " + name)
        with self.lock:
            return callback(self.context)


def render(r5):
    global _active_client
    from html import escape

    import ipywidgets as widgets
    from google.colab import drive
    from IPython.display import clear_output, display

    if _active_client is not None and _active_client.r5 is r5:
        display(*_active_client.view)
        _active_client.start_watch()
        return _active_client
    if _active_client is not None:
        _active_client.stop_watch()
        if not _active_client.lock.acquire(blocking=False):
            raise RuntimeError(
                "Una operación anterior sigue terminando; conserva ese panel hasta que concluya"
            )
        _active_client.lock.release()
    banner = widgets.HTML(
        "<h2>TRÍADE Ω · Centro continuo de Colab</h2>"
        "<p>Una acción instala, enciende o actualiza. Drive conserva tu memoria.</p>"
    )
    status = widgets.HTML("Consultando el canal de versiones…")
    output = widgets.Output(layout=widgets.Layout(max_height="480px", overflow="auto"))

    def mounted():
        return os.path.ismount("/content/drive")

    def mount():
        if not mounted():
            drive.mount("/content/drive")

    client = Client(
        r5,
        mount_drive=mount,
        drive_ready=mounted,
        notify=lambda text: setattr(status, "value", escape(text)),
    )
    _active_client = client
    busy = threading.Lock()
    buttons = []

    def button(label, callback, style=""):
        item = widgets.Button(
            description=label,
            button_style=style,
            layout=widgets.Layout(width="300px", height="44px"),
        )
        buttons.append(item)

        def click(_):
            if not busy.acquire(blocking=False):
                return
            for control in buttons:
                control.disabled = True
            try:
                with output:
                    clear_output(wait=True)
                    try:
                        print(
                            json.dumps(
                                callback(), ensure_ascii=False, indent=2, default=str
                            )
                        )
                    except Exception as exc:  # noqa: BLE001 - UI boundary displays the actual release error
                        print(
                            "Operación detenida:", type(exc).__name__, str(exc)[:1600]
                        )
            finally:
                for control in buttons:
                    control.disabled = False
                busy.release()

        item.on_click(click)
        return item

    actions = [
        button("Instalar / encender / actualizar", client.install, "success"),
        button("Comprobar nuevas versiones", client.check, "info"),
        button("Abrir Tríade", lambda: client.action("open_frontend")),
        button("Estado real", lambda: client.action("status")),
        button("Guardar memoria", lambda: client.action("save")),
        button("Auditar actividad (30 s)", lambda: client.action("audit")),
    ]
    automatic = widgets.Checkbox(
        value=False,
        indent=False,
        description="Aplicar automáticamente futuras versiones estables verificadas",
    )
    automatic.observe(
        lambda change: setattr(client, "auto_apply", change["new"]), names="value"
    )
    client.view = (
        banner,
        status,
        widgets.Box(
            actions, layout=widgets.Layout(display="flex", flex_flow="row wrap")
        ),
        widgets.HTML(
            "<small>Consulta continua cada 10 minutos mientras la sesión esté activa. "
            "Las candidatas se aplican con el botón. No necesitas otra celda por versión.</small>"
        ),
        automatic,
        output,
    )
    display(*client.view)
    client.start_watch()
    return client
