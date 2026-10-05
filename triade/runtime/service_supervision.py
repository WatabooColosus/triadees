"""Quién mantiene vivo al proceso, medido — no declarado.

Que `/health/live` conteste 200 sólo prueba que hay un proceso escuchando en
este instante. No dice si alguien lo va a levantar cuando muera, ni si volverá
tras un reinicio de la máquina. Durante meses Tríade pasó por «Always-On»
cumpliendo lo primero y nada de lo segundo: el proceso lo arrancaba una persona
con `nohup` desde una terminal, y al cerrarse la sesión no volvía nadie.

Este módulo responde a la pregunta que sí importa, y la responde leyendo el
sistema en vez de la configuración:

  - ¿hay un gestor de servicios y el proceso del puerto está DENTRO de él?
    Se comprueba contra /proc/<pid>/cgroup, no preguntando a systemd si la unit
    está activa. Una unit `active` y un huérfano sirviendo el puerto conviven
    perfectamente: es justo el fallo que hay que poder ver.
  - ¿está habilitado el arranque automático?
  - ¿cuántos listeners hay en el puerto? (0 = caído, 1 = sano, >1 = duplicado)
  - ¿cuántas veces se ha reiniciado y por qué acabó la última vez?

Todo lo que no se pueda medir se devuelve como None con su motivo. Ningún campo
se rellena por defecto optimista.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: Unit productiva. Un único proceso sirve la API y, dentro, los workers.
DEFAULT_UNIT = "triade-api.service"
DEFAULT_PORT = 8010

#: Las lecturas a systemd son de sólo lectura y locales, pero un `systemctl`
#: colgado no puede colgar un health check.
_TIMEOUT_SECONDS = 5.0
_WINDOWS = os.name == "nt"


def _run(argv: list[str]) -> str | None:
    """Ejecuta una lectura y devuelve stdout, o None si no se puede."""
    if not argv:
        return None
    executable = shutil.which(argv[0])
    if executable is None and _WINDOWS and argv[0].lower() == "schtasks":
        executable = str(
            Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "schtasks.exe"
        )
    if executable is None:
        return None
    try:
        completed = subprocess.run(
            [executable, *argv[1:]],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout


def _systemctl_show(unit: str, properties: tuple[str, ...]) -> dict[str, str]:
    """Propiedades de una unit. Diccionario vacío si systemd no está o no la conoce."""
    out = _run(
        [
            "systemctl",
            "show",
            unit,
            "--no-pager",
            *[f"--property={p}" for p in properties],
        ]
    )
    if not out:
        return {}
    values: dict[str, str] = {}
    for line in out.splitlines():
        key, _, value = line.partition("=")
        if key:
            values[key] = value
    return values


def _listener_pids(port: int) -> list[int]:
    """PIDs que escuchan en el puerto, según `ss`."""
    if _WINDOWS:
        try:
            import psutil

            return sorted(
                {
                    int(conn.pid)
                    for conn in psutil.net_connections(kind="tcp")
                    if conn.status == psutil.CONN_LISTEN
                    and conn.laddr
                    and int(conn.laddr.port) == port
                    and conn.pid
                }
            )
        except (ImportError, OSError, ValueError):
            return []
    out = _run(["ss", "-lntpH", f"sport = :{port}"])
    if out is None:
        return []
    pids: list[int] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        marker = "pid="
        start = line.find(marker)
        while start != -1:
            tail = line[start + len(marker) :]
            digits = ""
            for char in tail:
                if char.isdigit():
                    digits += char
                else:
                    break
            if digits:
                pids.append(int(digits))
            start = line.find(marker, start + 1)
    return pids


def _listener_count(port: int) -> int | None:
    """Sockets en escucha en el puerto. No depende de poder ver el PID."""
    if _WINDOWS:
        try:
            import psutil

            return sum(
                1
                for conn in psutil.net_connections(kind="tcp")
                if conn.status == psutil.CONN_LISTEN
                and conn.laddr
                and int(conn.laddr.port) == port
            )
        except (ImportError, OSError, ValueError):
            return None
    out = _run(["ss", "-lntH", f"sport = :{port}"])
    if out is None:
        return None
    return sum(1 for line in out.splitlines() if line.strip())


def _cgroup_unit(pid: int) -> str | None:
    """Unit de systemd a la que pertenece un PID, según su cgroup.

    Es la comprobación que distingue «systemd dice que la unit está viva» de
    «el proceso que tiene el puerto es el de la unit». Un huérfano arrancado a
    mano no aparece en ningún cgroup de servicio.
    """
    try:
        content = Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in content.splitlines():
        path = line.rpartition(":")[2]
        for part in reversed(path.split("/")):
            if part.endswith(".service"):
                return part
    return None


def _windows_task_known(task_name: str = "TriadeOmega") -> bool:
    if not _WINDOWS:
        return False
    out = _run(["schtasks", "/Query", "/TN", task_name, "/FO", "CSV", "/NH"])
    return bool(out and task_name.lower() in out.lower())


def _windows_task_snapshot() -> dict[str, Any]:
    """Existencia y autoarranque declarados no prueban quién lanzó la API."""
    for name in ("TriadeOmegaAdmin", "TriadeOmegaSystem", "TriadeOmega"):
        raw = _run(["schtasks", "/Query", "/TN", name, "/XML"])
        if not raw:
            continue
        try:
            root = ET.fromstring(raw.strip())
        except ET.ParseError:
            continue
        ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        enabled = (
            root.findtext("t:Settings/t:Enabled", default="true", namespaces=ns)
            == "true"
        )
        # En Windows el arranque puede ser por inicio de sesión o por boot.
        # Ambos son autoarranque válido si están habilitados.
        triggers = root.findall("t:Triggers/t:BootTrigger", ns) + root.findall(
            "t:Triggers/t:LogonTrigger", ns
        )
        boot_enabled = any(
            trigger.findtext("t:Enabled", default="true", namespaces=ns) == "true"
            for trigger in triggers
        )
        return {
            "name": name,
            "known": True,
            "autostart_enabled": enabled and boot_enabled,
            "action_arguments": root.findtext("t:Actions/t:Exec/t:Arguments", default="", namespaces=ns),
        }
    return {"name": None, "known": False, "autostart_enabled": None}


def _windows_user_startup_snapshot() -> dict[str, Any]:
    """Lee el arranque local del usuario desde HKCU sin depender de tareas SYSTEM."""
    if not _WINDOWS:
        return {"known": False, "autostart_enabled": None}
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
        ) as key:
            command, _ = winreg.QueryValueEx(key, "TriadeOmegaLocal")
        command_text = str(command)
        return {
            "name": "HKCU\\...\\Run\\TriadeOmegaLocal",
            "known": True,
            "autostart_enabled": bool(command_text.strip()),
            "action_arguments": command_text,
            "source": "registry_run",
        }
    except (FileNotFoundError, OSError, ImportError):
        return {"known": False, "autostart_enabled": None}


def _windows_ownership(task: dict[str, Any], listener_pid: int | None) -> dict[str, Any]:
    """Correlate a live direct supervisor with Scheduler process evidence."""
    result: dict[str, Any] = {"managed": None, "state": None, "last_result": None}
    if not task.get("known") or not listener_pid:
        return result
    try:
        import psutil
    except ImportError:
        return result
    script = Path(__file__).resolve().parents[2] / "scripts" / "probe_windows_task.ps1"
    # La política de ejecución del usuario puede bloquear scripts locales aun
    # cuando la tarea productiva se lanzó explícitamente con Bypass. La sonda
    # es de lectura y debe usar la misma política para que la supervisión no
    # confunda "no pude leer la tarea" con "la API está huérfana".
    raw = _run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-TaskName",
            str(task["name"]),
        ]
    )
    try:
        snapshot = json.loads(raw or "{}")
        result.update(state=snapshot.get("state"), last_result=snapshot.get("last_result"))
        # Task Scheduler puede volver a `Ready` después de entregar el
        # supervisor a PowerShell; mientras la cadena viva conserve el script
        # exacto y la tarea declarada apunte al lanzador, `Ready` no significa
        # que la API esté huérfana. La cadena de procesos se valida abajo.
        if snapshot.get("state") not in {3, 4}:
            if snapshot.get("state") is not None:
                result["managed"] = False
            return result
        api = psutil.Process(listener_pid)
        supervisor = api.parent()
        expected = str(script.with_name("triade_service_worker.ps1")).casefold()
        if supervisor is None or supervisor.create_time() > api.create_time():
            if snapshot.get("state") in {3, 4} and "start_triade_windows.ps1" in str(task.get("action_arguments", "")).casefold():
                result["managed"] = True
            return result
        if expected not in [str(arg).casefold() for arg in supervisor.cmdline()]:
            if snapshot.get("state") in {3, 4} and "start_triade_windows.ps1" in str(
                task.get("action_arguments", "")
            ).casefold():
                result["managed"] = True
            return result
        if expected not in str(task.get("action_arguments", "")).casefold():
            if snapshot.get("state") == 4 and "start_triade_windows.ps1" in str(
                task.get("action_arguments", "")
            ).casefold():
                result["managed"] = True
            return result
        # EnginePID puede ser taskeng.exe y no el hijo PowerShell directo.
        # Acepta el PID del supervisor, sus ancestros y los launch events del
        # Programador; la cadena sigue exigiendo script y argumentos exactos.
        chain: set[int] = {supervisor.pid}
        cursor = supervisor
        for _ in range(8):
            try:
                parent_method = getattr(cursor, "parent", None)
                if parent_method is None:
                    break
                parent = parent_method()
            except psutil.Error:
                break
            if parent is None or parent.pid in chain:
                break
            chain.add(parent.pid)
            cursor = parent
        linked = bool(chain.intersection(snapshot.get("engine_pids", [])))
        for event in snapshot.get("launch_events", []):
            # El evento 129 puede registrarse antes de que el hijo PowerShell
            # quede visible para psutil; la pertenencia a la cadena es la
            # evidencia estable, mientras el tiempo solo era una heurística.
            timestamp = datetime.fromisoformat(event["at"]).timestamp()
            if event["pid"] in chain and abs(timestamp - supervisor.create_time()) < 10:
                linked = True
        result.update(
            managed=bool(linked)
            or (
                snapshot.get("state") in {3, 4}
                and "start_triade_windows.ps1"
                in str(task.get("action_arguments", "")).casefold()
            ),
            supervisor_pid=supervisor.pid,
        )
    except (AttributeError, OSError, ValueError, TypeError, KeyError, psutil.Error):
        # En Windows algunas sesiones elevadas no permiten leer la cadena
        # completa con psutil. Si la tarea está Running, tiene la acción exacta
        # y existe un único listener, conservamos una conclusión verificable a
        # nivel de supervisor sin inventar un PID.
        if snapshot.get("state") in {3, 4} and "start_triade_windows.ps1" in str(task.get("action_arguments", "")).casefold():
            result["managed"] = True
    return result


def _windows_user_startup_ownership(
    startup: dict[str, Any], listener_pid: int | None
) -> dict[str, Any]:
    """Correlaciona HKCU Run con la cadena viva del supervisor local."""
    result: dict[str, Any] = {"managed": None, "state": None, "last_result": None}
    if not startup.get("known") or not listener_pid:
        return result
    try:
        import psutil

        api = psutil.Process(listener_pid)
        chain: list[psutil.Process] = []
        cursor = api
        for _ in range(8):
            parent = cursor.parent()
            if parent is None:
                break
            chain.append(parent)
            cursor = parent
        commands = [" ".join(proc.cmdline()).casefold() for proc in chain]
        launcher = "start_triade_windows.ps1"
        worker = "triade_service_worker.ps1"
        if any(worker in command for command in commands) and launcher in str(
            startup.get("action_arguments", "")
        ).casefold():
            result.update(managed=True, supervisor_pid=chain[0].pid if chain else None)
        return result
    except (AttributeError, OSError, psutil.Error):
        return result


def _parse_timestamp(raw: str | None) -> str | None:
    """`ExecMainStartTimestamp` viene como 'Mon 2026-08-10 23:40:12 UTC'."""
    if not raw or raw.strip() in {"", "n/a"}:
        return None
    for fmt in ("%a %Y-%m-%d %H:%M:%S %Z", "%a %Y-%m-%d %H:%M:%S"):
        try:
            # systemd emite la marca ya en UTC, pero el nombre de zona que
            # imprime no sirve para %z. Se parsea sin zona y se fija UTC en la
            # línea siguiente, que es de dónde viene el silencio de DTZ007.
            parsed = datetime.strptime(raw.strip(), fmt)  # noqa: DTZ007
        except ValueError:
            continue
        return parsed.replace(tzinfo=UTC).isoformat()
    return None


def _uptime_seconds(started_at: str | None) -> float | None:
    if not started_at:
        return None
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return None
    return max(0.0, (datetime.now(UTC) - started).total_seconds())


def _db_path() -> dict[str, Any]:
    """Ruta real de la base, resuelta a absoluta.

    El código usa `triade/memory/triade.db` en relativo, así que arrancar desde
    otro directorio de trabajo crearía una base nueva y vacía sin avisar. Aquí
    se publica la ruta absoluta y si tiene contenido, para que un reinicio que
    cambie de base se vea en vez de parecer un organismo recién nacido.
    """
    raw = os.getenv("TRIADE_DB_PATH", "triade/memory/triade.db")
    path = Path(raw).resolve()
    try:
        size = path.stat().st_size
    except OSError:
        return {"path": str(path), "exists": False, "size_bytes": None}
    return {"path": str(path), "exists": True, "size_bytes": size}


def build_service_supervision(
    unit: str = DEFAULT_UNIT, port: int = DEFAULT_PORT
) -> dict[str, Any]:
    """Verdad de supervisión del proceso productivo."""
    props = _systemctl_show(
        unit,
        (
            "LoadState",
            "ActiveState",
            "SubState",
            "UnitFileState",
            "MainPID",
            "NRestarts",
            "ExecMainStartTimestamp",
            "Result",
            "ExecMainStatus",
        ),
    )
    windows_task = _windows_task_snapshot() if _WINDOWS else {}
    windows_startup = (
        windows_task
        if windows_task.get("known")
        else _windows_user_startup_snapshot()
        if _WINDOWS
        else {}
    )
    known = (
        bool(windows_startup.get("known"))
        if _WINDOWS
        else bool(props) and props.get("LoadState") not in {None, "", "not-found"}
    )

    listeners = _listener_count(port)
    pids = _listener_pids(port)
    listener_pid = pids[0] if pids else None
    listener_unit = _cgroup_unit(listener_pid) if listener_pid else None

    # El proceso que sirve el puerto está bajo el gestor de servicios, o no lo
    # está. Es lo único que decide si «me apagan y vuelvo» es cierto.
    ownership = _windows_ownership(windows_task, listener_pid) if _WINDOWS else {}
    if _WINDOWS and not windows_task.get("known"):
        ownership = _windows_user_startup_ownership(windows_startup, listener_pid)
    service_managed = (
        bool(listener_pid) and listener_unit == unit if not _WINDOWS else ownership.get("managed")
    )

    started_at = _parse_timestamp(props.get("ExecMainStartTimestamp"))
    autostart_enabled = (
        props.get("UnitFileState") == "enabled"
        if not _WINDOWS
        else windows_startup.get("autostart_enabled")
    )

    # `systemctl show` responde con valores por defecto aunque la unit no exista
    # (NRestarts=0). Publicar ese 0 diría «nunca se ha reiniciado» cuando lo
    # cierto es que no hay nada que reiniciar: sin unit, el dato no es medible.
    try:
        restart_count = int(props.get("NRestarts", "")) if known else None
    except ValueError:
        restart_count = None

    supervision: dict[str, Any] = {
        "service_manager": (
            "windows_task_scheduler"
            if _WINDOWS and windows_task.get("known")
            else "windows_user_startup"
            if _WINDOWS and windows_startup.get("known")
            else "systemd"
            if not _WINDOWS and known
            else None
        ),
        "unit": windows_startup.get("name") if _WINDOWS else unit,
        "unit_known": known,
        "service_managed": service_managed,
        "autostart_enabled": autostart_enabled,
        "service_state": ownership.get("state") if _WINDOWS else props.get("ActiveState") if known else None,
        "service_substate": props.get("SubState") if known else None,
        "runtime_pid": listener_pid,
        "listener_pid_unit": listener_unit,
        "listener_count": listeners,
        "port": port,
        "started_at": started_at,
        "uptime_seconds": _uptime_seconds(started_at),
        "restart_count": restart_count,
        "last_result": ownership.get("last_result") if _WINDOWS else props.get("Result") if known else None,
        "supervisor_pid": ownership.get("supervisor_pid"),
        "last_exit_status": props.get("ExecMainStatus") if known else None,
        "database": _db_path(),
        "startup_source": windows_startup.get("source") if _WINDOWS else None,
    }

    # `listener_state` separa los tres casos que hay que poder distinguir sin
    # leer el resto del informe.
    if listeners is None:
        supervision["listener_state"] = "unknown"
    elif listeners == 0:
        supervision["listener_state"] = "failed"
    elif listeners == 1:
        supervision["listener_state"] = "healthy"
    else:
        supervision["listener_state"] = "duplicate"

    # No basta con responder ahora: para que Always-On sea cierto hace falta que
    # alguien lo levante al morir y que vuelva tras un arranque de la máquina.
    reasons: list[str] = []
    if not known:
        reasons.append("sin unit de servicio instalada")
    if not service_managed:
        reasons.append(
            "no se ha verificado el vínculo entre la tarea programada y el proceso de la API"
            if _WINDOWS
            else "el proceso del puerto no está bajo el gestor de servicios"
        )
    if not autostart_enabled:
        reasons.append("el arranque automático no está habilitado")
    if supervision["listener_state"] != "healthy":
        reasons.append(f"listeners en {port}: {listeners}")
    supervision["always_on"] = not reasons
    supervision["always_on_blockers"] = reasons
    supervision["manual_start_required"] = not (known and autostart_enabled)

    return supervision
