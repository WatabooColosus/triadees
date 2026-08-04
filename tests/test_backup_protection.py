"""El sistema pasó cuatro días sin una sola copia y nada lo dijo.

Línea de tiempo medida el 2026-08-03 sobre la base viva: los backups se crearon
sin problema hasta el 2026-07-30 23:56. El 2026-07-31 a las 20:10 una ejecución
acabó en `dead_letter` por un reinicio, y **después no se planificó ninguna más**:
la condición del planner era `os.getenv("TRIADE_BACKUP_KEY")`, la clave dejó de
estar en el entorno y la rama simplemente no se ejecutó. Sin tarea, sin aviso,
sin métrica que bajara. Un backup que deja de hacerse en silencio es peor que no
tenerlo, porque nadie va a buscarlo hasta que haga falta.

Estas pruebas fijan tres cosas: que la falta se **mide**, que una clave en
fichero también sirve para planificar, y que cada copia dice qué clave la abre.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from triade.memory.encrypted_backup import EncryptedBackup
from triade.observability.introspection import (
    BACKUP_MAX_AGE_SECONDS,
    _backup_protection_gaps,
)

FERNET_A = "0" * 42 + "="
FERNET_B = "1" * 42 + "="


def _backup(root: Path, name: str, *, age_seconds: float, fingerprint: str | None):
    directory = root / "artifacts" / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    archivo = directory / f"triade-{name}.db.gz.fernet"
    archivo.write_bytes(b"cifrado")
    manifiesto = {"file": archivo.name, "sha256": "x"}
    if fingerprint is not None:
        manifiesto["key_fingerprint"] = fingerprint
    archivo.with_suffix(archivo.suffix + ".json").write_text(
        json.dumps(manifiesto), encoding="utf-8"
    )
    momento = time.time() - age_seconds
    os.utime(archivo, (momento, momento))
    return archivo


# --- La medición de la falta --------------------------------------------------


def test_sin_clave_es_deuda_medida(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Era justo el estado del 2026-07-31 al 08-03, y no lo contaba nadie."""
    monkeypatch.delenv("TRIADE_BACKUP_KEY", raising=False)
    monkeypatch.delenv("TRIADE_BACKUP_KEY_FILE", raising=False)
    _backup(tmp_path, "reciente", age_seconds=60, fingerprint="abc123")

    entry = _backup_protection_gaps(tmp_path)

    assert entry["count"] == 1
    assert "TRIADE_BACKUP_KEY" in entry["sample"][0]


def test_una_copia_caducada_es_deuda(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRIADE_BACKUP_KEY", FERNET_A)
    _backup(
        tmp_path,
        "vieja",
        age_seconds=BACKUP_MAX_AGE_SECONDS + 3600,
        fingerprint="abc123",
    )

    entry = _backup_protection_gaps(tmp_path)

    assert entry["count"] == 1
    assert "días" in entry["sample"][0]


def test_una_copia_sin_huella_de_clave_es_deuda(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Es el estado de las 8 copias existentes: no se sabe cuál las abre."""
    monkeypatch.setenv("TRIADE_BACKUP_KEY", FERNET_A)
    _backup(tmp_path, "anonima", age_seconds=60, fingerprint=None)

    entry = _backup_protection_gaps(tmp_path)

    assert entry["count"] == 1
    assert "key_fingerprint" in entry["sample"][0]


def test_no_tener_ninguna_copia_se_dice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRIADE_BACKUP_KEY", FERNET_A)
    (tmp_path / "artifacts" / "backups").mkdir(parents=True)

    entry = _backup_protection_gaps(tmp_path)

    assert entry["count"] == 1
    assert "ninguna copia" in entry["sample"][0]


def test_con_clave_y_copia_fresca_no_hay_deuda(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La categoría tiene que poder llegar a cero, o no mide: alarma."""
    monkeypatch.setenv("TRIADE_BACKUP_KEY", FERNET_A)
    _backup(tmp_path, "buena", age_seconds=60, fingerprint="abc123")

    assert _backup_protection_gaps(tmp_path)["count"] == 0


# --- La huella de la clave ----------------------------------------------------


def test_la_huella_distingue_claves(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIADE_BACKUP_KEY", FERNET_A)
    huella_a = EncryptedBackup.key_fingerprint()
    monkeypatch.setenv("TRIADE_BACKUP_KEY", FERNET_B)
    huella_b = EncryptedBackup.key_fingerprint()

    assert huella_a and huella_b
    assert huella_a != huella_b
    # No puede filtrar la clave: es un resumen corto, no un cifrado reversible.
    assert FERNET_A not in huella_a and len(huella_a) == 16


def test_la_huella_es_estable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Si cambiara entre lecturas no serviría para emparejar nada."""
    monkeypatch.setenv("TRIADE_BACKUP_KEY", FERNET_A)
    assert EncryptedBackup.key_fingerprint() == EncryptedBackup.key_fingerprint()


def test_sin_clave_no_hay_huella(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRIADE_BACKUP_KEY", raising=False)
    monkeypatch.delenv("TRIADE_BACKUP_KEY_FILE", raising=False)
    assert EncryptedBackup.key_fingerprint() is None


# --- La planificación ---------------------------------------------------------


def _planned_types(db_path: Path) -> list[str]:
    from triade.workers.mission_planner import MissionPlanner

    return [t.task_type for t in MissionPlanner(db_path=db_path).plan_cycle()]


def _fresh_db(tmp_path: Path) -> Path:
    import sqlite3

    db_path = tmp_path / "triade.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            Path("triade/memory/schemas.sql").read_text(encoding="utf-8")
        )
    return db_path


def test_la_clave_en_fichero_tambien_planifica_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`encrypted_backup.py` acepta las dos formas; el planner miraba sólo una."""
    monkeypatch.delenv("TRIADE_BACKUP_KEY", raising=False)
    monkeypatch.setenv("TRIADE_BACKUP_KEY_FILE", str(tmp_path / "clave"))

    assert "encrypted_backup" in _planned_types(_fresh_db(tmp_path))


def test_sin_ninguna_clave_la_falta_queda_registrada(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Antes no pasaba nada de nada: ni tarea, ni error, ni rastro."""
    from triade.core.error_bus import query_internal_errors

    monkeypatch.delenv("TRIADE_BACKUP_KEY", raising=False)
    monkeypatch.delenv("TRIADE_BACKUP_KEY_FILE", raising=False)
    db_path = _fresh_db(tmp_path)

    assert "encrypted_backup" not in _planned_types(db_path)

    errores = query_internal_errors(db_path=db_path, limit=20) or []
    assert any("backup_key_missing" in str(e.get("task_type", "")) for e in errores), (
        errores
    )
