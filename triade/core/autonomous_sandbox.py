"""Snapshots SHA-256 para el rollback gobernado de archivos.

Tríade Ω — Autonomous Sandbox

Reglas:
- Snapshot de archivos antes de ejecutar código.
- Detectar cambios post-ejecución comparando hashes.
- Rollback restaura el contenido original desde el snapshot.
- La ejecución y su auditoría canónicas viven en ``triade.sandbox``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path


class AutonomousSandbox:
    """Captura el estado previo usado por el worker para un rollback de archivos.

    La antigua implementación también ejecutaba Python arbitrario y mantenía
    una segunda bitácora SQLite que nunca recibió filas. Esa vía no tenía
    callers productivos; el ejecutor permitido y la evidencia de replay viven en
    :mod:`triade.sandbox.executor` y :mod:`triade.sandbox.isolation`.
    """

    def __init__(self, db_path: str | Path, runs_dir: str | Path) -> None:
        self.db_path = Path(db_path)
        self.runs_dir = Path(runs_dir)
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def create_snapshot(self, files_to_watch: Sequence[str | Path]) -> dict[str, str]:
        """Captura SHA-256 de cada archivo existente."""
        snapshot: dict[str, str] = {}
        for filepath in files_to_watch:
            p = Path(filepath)
            if p.is_file():
                snapshot[str(p.resolve())] = self._hash_file(p)
            else:
                snapshot[str(p.resolve())] = ""
        return snapshot

    def _hash_file(self, path: Path) -> str:
        sha = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha.update(chunk)
        return sha.hexdigest()
