"""Una retirada de esquema que se deshace sola no es una retirada.

Tríade no tiene un runner central de migraciones: cada subsistema reejecuta su
propio `.sql` con `executescript` cuando lo necesita —`MetabolicCoordinator.
_ensure_tables()`, `EncryptedBackup.__init__`, `IdentityContinuity.
_ensure_base_schema()`, y una docena más—. Es idempotente y funciona bien para
crear, pero convierte cada fichero de migración en **DDL viva**, no en historia.

De ahí sale un fallo que ningún test de migraciones veía: una migración de
retirada (`DROP TABLE`) puede quedar anulada por un `CREATE TABLE` que sigue
dentro de otro fichero que alguien reejecuta después. Medido el 2026-08-08 con
`metabolic_config`: `034` la retiraba, la base viva la tenía igualmente, y
`032` la recreaba en cada ciclo metabólico.

Las dos pruebas de aquí son el gate general —vale para cualquier tabla retirada,
hoy o en el futuro, sin nombrar ninguna— y la certificación concreta de que la
cadena termina donde dice terminar.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "triade" / "memory" / "migrations"
SCHEMAS = ROOT / "triade" / "memory" / "schemas.sql"

_DROP = re.compile(
    r"^\s*DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?[\"'`\[]?(\w+)",
    re.IGNORECASE | re.MULTILINE,
)
_CREATE = re.compile(
    r"^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"'`\[]?(\w+)",
    re.IGNORECASE | re.MULTILINE,
)


def _sql_files() -> list[Path]:
    return [SCHEMAS, *sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql"))]


def _tables(pattern: re.Pattern[str], path: Path) -> set[str]:
    return {m.lower() for m in pattern.findall(path.read_text(encoding="utf-8"))}


def test_ninguna_tabla_retirada_sigue_creandose_en_otro_sql() -> None:
    """El gate general: retirar y crear la misma tabla es no retirarla.

    No lleva lista de nombres a propósito. La regla se deriva de la estructura
    —qué `DROP` y qué `CREATE` hay en el repositorio— para que valga igual con
    la próxima retirada, que nadie va a acordarse de añadir aquí.

    Por qué no basta con "el CREATE está antes que el DROP": el orden del número
    de migración no manda nada en tiempo de ejecución. Cada subsistema reejecuta
    su fichero cuando le toca, y el último que corra gana. Un `CREATE`
    superviviente es una retirada que va a deshacerse; cuándo, depende de qué
    subsistema arranque después.
    """
    retiradas: dict[str, Path] = {}
    for path in _sql_files():
        for tabla in _tables(_DROP, path):
            retiradas[tabla] = path

    supervivientes: list[str] = []
    for path in _sql_files():
        for tabla in _tables(_CREATE, path) & set(retiradas):
            supervivientes.append(
                f"{tabla}: retirada en {retiradas[tabla].name}, "
                f"pero {path.name} la sigue creando"
            )

    assert not supervivientes, (
        "hay retiradas de esquema que se deshacen solas:\n  "
        + "\n  ".join(sorted(supervivientes))
    )


def test_la_cadena_de_migraciones_deja_lo_retirado_ausente(tmp_path: Path) -> None:
    """La certificación concreta: aplicar todo y comprobar el estado final.

    El gate anterior es estático. Éste ejecuta la cadena entera sobre una base
    nueva —`schemas.sql` más las 35 migraciones en orden— y comprueba que lo
    que `034` retira no está. Es la prueba que los tres instrumentos de la
    investigación de agosto no llegaron a hacer: todos medían otra cosa.
    """
    db = tmp_path / "cadena.db"
    conn = sqlite3.connect(db)
    for path in _sql_files():
        conn.executescript(path.read_text(encoding="utf-8"))
    conn.commit()

    presentes = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    conn.close()

    retiradas = _tables(_DROP, MIGRATIONS / "034_retire_orphan_schema.sql")

    assert not retiradas & presentes, (
        f"la cadena termina con tablas ya retiradas: {sorted(retiradas & presentes)}"
    )


def test_el_metabolismo_no_recrea_lo_que_034_retira(tmp_path: Path) -> None:
    """El caso que costó siete intentos: quien deshacía la retirada era el organismo.

    `_ensure_tables()` corre en cada `_start_cycle()`. Con `metabolic_config`
    dentro de `032`, la tabla volvía a los pocos minutos de cualquier retirada
    —y en una base nueva no llegaba a irse nunca, porque `034` sí se aplica pero
    `032` se reejecuta después—.

    La prueba fija el `db_path` del coordinador con un `assert` explícito. Las
    tres mediciones que dieron verde en falso durante la investigación fallaron
    justo ahí: creían medir sobre una copia y leían la base real.
    """
    from triade.metabolism.coordinator import MetabolicCoordinator

    db = tmp_path / "triade.db"
    conn = sqlite3.connect(db)
    for path in _sql_files():
        conn.executescript(path.read_text(encoding="utf-8"))
    conn.commit()
    conn.close()

    coordinador = MetabolicCoordinator(db_path=db)
    assert coordinador.db_path == db, "el coordinador no está usando la copia"
    coordinador._ensure_tables()

    conn = sqlite3.connect(db)
    presentes = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    conn.close()

    # Lo que el metabolismo sí necesita sigue estando: esto no es "032 sobra".
    assert "metabolic_cycle" in presentes
    assert "metabolic_needs" in presentes
    assert "metabolic_config" not in presentes
