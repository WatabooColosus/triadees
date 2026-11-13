"""La auditoría de copias miraba el entorno equivocado.

`_backup_protection_gaps` decidía si hay clave de cifrado con `os.getenv` del
proceso que audita. Pero quien hace las copias es el runtime, y el runtime
recibe su configuración del `.env` del repo por el `EnvironmentFile` de systemd:
una shell interactiva no lo tiene cargado.

El 2026-08-10 eso se vio en crudo: el proceso de `triade-api.service` tenía
`TRIADE_BACKUP_KEY_FILE` en `/proc/<pid>/environ`, las copias se estaban
haciendo, y la auditoría lanzada desde la terminal declaraba igualmente «sin
TRIADE_BACKUP_KEY ni TRIADE_BACKUP_KEY_FILE: no se crea ninguna copia».

Un falso positivo aquí es peor que no medir. Esta categoría existe porque el
2026-07-31 la clave desapareció de verdad y el sistema pasó cuatro días sin una
sola copia sin que nada lo dijera; si además avisa cuando no pasa nada, deja de
creerse el día que pasa.

De paso arregla un punto ciego: sin la variable en el entorno, la comprobación
de permisos del fichero de clave —la que encontró el `0744` que bloqueaba
restaurar— devolvía lista vacía y no llegaba a ejecutarse nunca.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from triade.observability.introspection import (
    _backup_key_configured,
    _backup_key_file_path,
)


@pytest.fixture(autouse=True)
def _sin_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    """Audita como lo haría una shell: sin las variables del runtime."""
    monkeypatch.delenv("TRIADE_BACKUP_KEY", raising=False)
    monkeypatch.delenv("TRIADE_BACKUP_KEY_FILE", raising=False)


def test_lee_la_clave_del_env_del_repo(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "# comentario\nTRIADE_BACKUP_KEY_FILE=/ruta/backup.key\n",
        encoding="utf-8",
    )
    assert _backup_key_configured(tmp_path) is True
    assert _backup_key_file_path(tmp_path) == "/ruta/backup.key"


def test_el_entorno_manda_sobre_el_fichero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text(
        "TRIADE_BACKUP_KEY_FILE=/del/fichero.key\n", encoding="utf-8"
    )
    monkeypatch.setenv("TRIADE_BACKUP_KEY_FILE", "/del/entorno.key")
    assert _backup_key_file_path(tmp_path) == "/del/entorno.key"


def test_sin_clave_en_ninguna_parte_sigue_siendo_deuda(tmp_path: Path) -> None:
    """El fallo real tiene que seguir detectándose: no se ha tapado la señal."""
    (tmp_path / ".env").write_text("TRIADE_ALWAYS_ON=true\n", encoding="utf-8")
    assert _backup_key_configured(tmp_path) is False
    assert _backup_key_file_path(tmp_path) == ""


def test_variable_declarada_pero_vacia_no_cuenta(tmp_path: Path) -> None:
    """`TRIADE_BACKUP_KEY_FILE=` no configura nada, aunque el nombre esté ahí."""
    (tmp_path / ".env").write_text("TRIADE_BACKUP_KEY_FILE=\n", encoding="utf-8")
    assert _backup_key_configured(tmp_path) is False


def test_sin_fichero_env_no_revienta(tmp_path: Path) -> None:
    assert _backup_key_configured(tmp_path) is False
    assert _backup_key_file_path(tmp_path) == ""


def test_comillas_alrededor_del_valor(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        'TRIADE_BACKUP_KEY_FILE="/con/comillas.key"\n', encoding="utf-8"
    )
    assert _backup_key_file_path(tmp_path) == "/con/comillas.key"
