"""Regeneración de los grafos internos sin bloquear a quien los pide.

El problema que resuelve es concreto: reconstruir el AST del repositorio cuesta
~53 s, así que las rutas de lectura sirven artefactos ya escritos. Nadie los
regeneraba en el Studio —el único disparador automático vivía en CI, sobre
`pull_request`—, de modo que el panel podía repetir la misma cifra durante horas
después de un cambio real y presentarla como medición actual.

La política es *serve-stale-while-revalidate*: se devuelve lo que hay, se marca
su edad, y si está caducado se lanza **una** reconstrucción en segundo plano. La
petición no espera; la siguiente ya lee lo nuevo.

Tres reglas que no son negociables aquí:

- **Un solo constructor a la vez.** Un lock y un hilo daemon; si llegan diez
  peticiones mientras se construye, las diez leen el artefacto viejo y ninguna
  encola otro escaneo.
- **Nadie lee un fichero a medio escribir.** Se construye en un directorio
  hermano y cada JSON entra en su sitio con `os.replace`, que es atómico en el
  mismo sistema de ficheros. `index.json` va el último porque de su `mtime`
  cuelga la frescura de todo lo demás.
- **El fallo se cuenta, no se esconde.** Si la reconstrucción revienta, el
  estado queda en `failed` con el error y una espera antes de reintentar, para
  que un repositorio roto no queme la CPU en bucle.

Nada de esto se dispara solo: se dispara cuando alguien mira. Un temporizador
gastaría 53 s de CPU cada intervalo aunque nadie tuviera la página abierta.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any

#: Cuándo se considera caducado el artefacto y merece la pena reconstruirlo.
#: Quince minutos es la escala a la que cambia el repositorio mientras se
#: trabaja: un commit no se ve al instante, pero tampoco se tarda una tarde.
DEFAULT_STALE_SECONDS = 15 * 60
#: Tras un fallo se espera antes de volver a intentarlo. Sin esto, un repo que
#: no compila provoca un escaneo continuo de 53 s por cada visita a la página.
FAILURE_COOLDOWN_SECONDS = 5 * 60


def _env_seconds(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


class GraphRefresher:
    """Mantiene frescos los artefactos de un directorio de grafos.

    Es explícitamente un objeto y no un puñado de funciones con globales porque
    los tests necesitan un refrescador propio, apuntando a un `tmp_path`, sin
    tocar el del proceso vivo.
    """

    def __init__(
        self,
        root: Path,
        cache_dir: Path,
        db_path: Path | None = None,
        *,
        stale_seconds: float | None = None,
    ) -> None:
        self.root = Path(root)
        self.cache_dir = Path(cache_dir)
        self.db_path = Path(db_path) if db_path is not None else None
        self.stale_seconds = (
            stale_seconds
            if stale_seconds is not None
            else _env_seconds("TRIADE_GRAPHS_STALE_SECONDS", DEFAULT_STALE_SECONDS)
        )
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._started_at: float | None = None
        self._finished_at: float | None = None
        self._duration: float | None = None
        self._error: str | None = None
        self._failed_at: float | None = None
        self._builds = 0
        self._exit_code: int | None = None
        self._restore_status()

    # -- lectura del estado en disco -------------------------------------

    @property
    def _index(self) -> Path:
        return self.cache_dir / "index.json"

    @property
    def _status_file(self) -> Path:
        return self.cache_dir / "refresh_status.json"

    def _restore_status(self) -> None:
        """Recupera el último resultado; reiniciar la API no borra el fallo."""
        try:
            payload = json.loads(self._status_file.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        self._started_at = payload.get("started_at")
        self._finished_at = payload.get("finished_at")
        self._duration = payload.get("duration_seconds")
        self._error = payload.get("last_error")
        self._failed_at = payload.get("failed_at")
        self._builds = int(payload.get("builds") or 0)
        self._exit_code = payload.get("exit_code")

    def _persist_status(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "command": "scripts.build_internal_graphs.build_all(render=False)",
            "started_at": self._started_at,
            "finished_at": self._finished_at,
            "duration_seconds": self._duration,
            "exit_code": self._exit_code,
            "last_error": self._error,
            "stderr_summary": self._error,
            "failed_at": self._failed_at,
            "builds": self._builds,
        }
        temporary = self._status_file.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        os.replace(temporary, self._status_file)

    def generated_at(self) -> float | None:
        """`mtime` de `index.json`, o `None` si nunca se generó nada."""
        try:
            return self._index.stat().st_mtime
        except OSError:
            return None

    def age_seconds(self) -> float | None:
        generated = self.generated_at()
        return None if generated is None else time.time() - generated

    def is_stale(self) -> bool:
        """Sin artefacto también es caducado: hay que construirlo igual."""
        age = self.age_seconds()
        return age is None or age >= self.stale_seconds

    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    # -- disparo ---------------------------------------------------------

    def request(self, *, force: bool = False) -> str:
        """Pide una reconstrucción si hace falta. Nunca bloquea.

        Devuelve qué se decidió, y ese motivo viaja hasta la interfaz: quien
        mira la cifra tiene que poder distinguir «esto está al día» de «esto es
        viejo y ya se está recalculando».
        """
        if self.is_running():
            return "running"
        if not force and not self.is_stale():
            return "fresh"
        if not force and self._failed_at is not None:
            waited = time.time() - self._failed_at
            if waited < FAILURE_COOLDOWN_SECONDS:
                return "cooldown"

        with self._lock:
            if self.is_running():
                return "running"
            self._started_at = time.time()
            self._error = None
            self._exit_code = None
            self._persist_status()
            thread = threading.Thread(
                target=self._run,
                name="internal-graphs-refresh",
                daemon=True,
            )
            self._thread = thread
            thread.start()
        return "started"

    def wait(self, timeout: float | None = None) -> bool:
        """Espera a la reconstrucción en curso. Sólo para tests y scripts."""
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    # -- ejecución -------------------------------------------------------

    def _run(self) -> None:
        started = time.time()
        staging = self.cache_dir.parent / f".{self.cache_dir.name}.building"
        try:
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True, exist_ok=True)
            # Import local: `build_all` arrastra todos los constructores y este
            # módulo se importa desde rutas donde el arranque debe ser barato.
            from scripts.build_internal_graphs import build_all

            build_all(self.root, self.db_path, staging, render=False)
            self._publish(staging)
        except Exception as exc:  # noqa: BLE001 — el fallo se reporta, no se traga
            self._error = f"{type(exc).__name__}: {exc}"
            self._failed_at = time.time()
            self._exit_code = 1
        else:
            self._error = None
            self._failed_at = None
            self._exit_code = 0
            self._builds += 1
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            self._finished_at = time.time()
            self._duration = self._finished_at - started
            self._persist_status()

    def _publish(self, staging: Path) -> None:
        """Mueve el resultado a su sitio sin que nadie lea un JSON a medias.

        `index.json` es el último en entrar: mientras no se mueva, cualquier
        lector sigue viendo la generación anterior como la vigente.
        """
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        index = staging / "index.json"
        if not index.exists():
            raise RuntimeError("la reconstrucción no escribió index.json")
        for produced in sorted(staging.glob("*.json")):
            if produced.name == "index.json":
                continue
            os.replace(produced, self.cache_dir / produced.name)
        os.replace(index, self._index)

    # -- informe ---------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Estado legible por la interfaz, con la edad ya resuelta en segundos."""
        age = self.age_seconds()
        generated = self.generated_at()
        return {
            "running": self.is_running(),
            "stale": self.is_stale(),
            "stale_after_seconds": self.stale_seconds,
            "age_seconds": None if age is None else round(age, 1),
            "started_at": self._started_at,
            "finished_at": self._finished_at,
            "last_build_seconds": (
                None if self._duration is None else round(self._duration, 1)
            ),
            "builds": self._builds,
            "last_error": self._error,
            "exit_code": self._exit_code,
            "command": "scripts.build_internal_graphs.build_all(render=False)",
            "stderr_summary": self._error,
            "last_valid_artifact": "index.json" if generated is not None else None,
            "last_valid_generated_at": generated,
            "last_valid_age_seconds": None if age is None else round(age, 1),
        }
