"""La identidad evoluciona desde la reflexión, y sólo cuando la reflexión sabe.

`auto_identity` tenía dos lectores productivos —`core/qualia.py:192`, que compone
la identidad evolucionada en cada run, y `core/bodega.py`— y cero filas.
`evolve_from_reflection` existía, era alcanzable, y no lo llamaba nadie: los dos
lectores recibían la lista vacía desde siempre y el contador
`auto_identity_traits` del propio tick medía 0 por construcción.

Lo que faltaba era el gate, no el escritor: `load_active()` expone los rasgos ya
en `candidate`, así que un rasgo entra en la identidad en cuanto se escribe.
"""

from __future__ import annotations

from triade.core.life_pulse import LifePulseEngine
from triade.memory.auto_identity_store import AutoIdentityStore

OBSERVACIONES = [
    "El runner tarda mas de lo esperado cuando el modelo central esta frio",
    "Las misiones de investigacion fallan si no hay fuentes independientes",
]
TEMAS = ["latencia del arranque en frio", "verificacion de fuentes independientes"]


def _reflexion(*, sabe: bool = True, toca_ancla: bool = False) -> dict:
    return {
        "core_awareness": {"knows_what_happened": sabe},
        "policy": {"identity_core_modified": toca_ancla},
        "observations": list(OBSERVACIONES),
        "learning_candidates": {"candidate_themes": list(TEMAS)},
    }


def _pulse(tmp_path) -> LifePulseEngine:
    return LifePulseEngine(db_path=str(tmp_path / "pulse.db"))


def test_una_reflexion_con_cobertura_produce_rasgos(tmp_path):
    pulse = _pulse(tmp_path)

    evolucionados = pulse._evolve_identity_from(_reflexion())

    assert evolucionados
    activos = AutoIdentityStore(db_path=str(tmp_path / "pulse.db")).load_active()
    assert activos, "los rasgos no llegan al lector productivo"
    # Y llegan como candidatos, no como identidad asentada.
    assert {t["status"] for t in activos} == {"candidate"}


def test_una_reflexion_que_no_sabe_lo_que_paso_no_produce_identidad(tmp_path):
    """Cobertura pobre observa sobre huecos; de ahí no debe salir identidad."""
    pulse = _pulse(tmp_path)

    assert pulse._evolve_identity_from(_reflexion(sabe=False)) == []
    assert AutoIdentityStore(db_path=str(tmp_path / "pulse.db")).load_active() == []


def test_si_la_reflexion_declara_que_tocaria_el_ancla_no_se_evoluciona(tmp_path):
    """El ancla se rebasa con una decisión del operador, no en un tick."""
    pulse = _pulse(tmp_path)

    assert pulse._evolve_identity_from(_reflexion(toca_ancla=True)) == []
    assert AutoIdentityStore(db_path=str(tmp_path / "pulse.db")).load_active() == []


def test_repetir_la_observacion_da_evidencia_y_no_filas(tmp_path):
    """Así es como un patrón recurrente gana confianza sin inflar la tabla."""
    pulse = _pulse(tmp_path)
    store = AutoIdentityStore(db_path=str(tmp_path / "pulse.db"))

    pulse._evolve_identity_from(_reflexion())
    primero = store.load_active()
    pulse._evolve_identity_from(_reflexion())
    segundo = store.load_active()

    assert len(segundo) == len(primero)
    assert max(t["evidence_count"] for t in segundo) > max(
        t["evidence_count"] for t in primero
    )


def test_evolucionar_no_escribe_en_el_ancla(tmp_path):
    """`identity_core` es otra tabla y sigue siendo asunto del operador."""
    pulse = _pulse(tmp_path)
    db = tmp_path / "pulse.db"

    from triade.db import sqlite3

    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS identity_core "
            "(id INTEGER PRIMARY KEY, key TEXT, value TEXT, category TEXT)"
        )
        conn.execute(
            "INSERT INTO identity_core (key, value, category) VALUES (?, ?, ?)",
            ("nombre", "Tríade", "ancla"),
        )

    pulse._evolve_identity_from(_reflexion())

    with sqlite3.connect(str(db)) as conn:
        filas = conn.execute(
            "SELECT key, value FROM identity_core ORDER BY id"
        ).fetchall()
    assert [tuple(f) for f in filas] == [("nombre", "Tríade")]
