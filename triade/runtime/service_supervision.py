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

import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: Unit productiva. Un único proceso sirve la API y, dentro, los workers.
DEFAULT_UNIT = "triade-api.service"
DEFAULT_PORT = 8010

#: Las lecturas a systemd son de sólo lectura y locales, pero un `systemctl`
#: colgado no puede colgar un health check.
_TIMEOUT_SECONDS = 5.0


def _run(argv: list[str]) -> str | None:
    """Ejecuta una lectura y devuelve stdout, o None si no se puede."""
    if not argv or shutil.which(argv[0]) is None:
        return None
    try:
        completed = subprocess.run(
            argv,
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
    known = bool(props) and props.get("LoadState") not in {None, "", "not-found"}

    listeners = _listener_count(port)
    pids = _listener_pids(port)
    listener_pid = pids[0] if pids else None
    listener_unit = _cgroup_unit(listener_pid) if listener_pid else None

    # El proceso que sirve el puerto está bajo el gestor de servicios, o no lo
    # está. Es lo único que decide si «me apagan y vuelvo» es cierto.
    service_managed = bool(listener_pid) and listener_unit == unit

    started_at = _parse_timestamp(props.get("ExecMainStartTimestamp"))
    autostart_enabled = props.get("UnitFileState") == "enabled" if known else False

    # `systemctl show` responde con valores por defecto aunque la unit no exista
    # (NRestarts=0). Publicar ese 0 diría «nunca se ha reiniciado» cuando lo
    # cierto es que no hay nada que reiniciar: sin unit, el dato no es medible.
    try:
        restart_count = int(props.get("NRestarts", "")) if known else None
    except ValueError:
        restart_count = None

    supervision: dict[str, Any] = {
        "service_manager": "systemd" if known else None,
        "unit": unit,
        "unit_known": known,
        "service_managed": service_managed,
        "autostart_enabled": autostart_enabled,
        "service_state": props.get("ActiveState") if known else None,
        "service_substate": props.get("SubState") if known else None,
        "runtime_pid": listener_pid,
        "listener_pid_unit": listener_unit,
        "listener_count": listeners,
        "port": port,
        "started_at": started_at,
        "uptime_seconds": _uptime_seconds(started_at),
        "restart_count": restart_count,
        "last_result": props.get("Result") if known else None,
        "last_exit_status": props.get("ExecMainStatus") if known else None,
        "database": _db_path(),
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
        reasons.append("el proceso del puerto no está bajo el gestor de servicios")
    if not autostart_enabled:
        reasons.append("el arranque automático no está habilitado")
    if supervision["listener_state"] != "healthy":
        reasons.append(f"listeners en {port}: {listeners}")
    supervision["always_on"] = not reasons
    supervision["always_on_blockers"] = reasons
    supervision["manual_start_required"] = not (known and autostart_enabled)

    return supervision
