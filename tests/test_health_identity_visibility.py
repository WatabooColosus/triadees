"""Un organismo que se detecta manipulado no puede reportarse sano.

El 2026-08-12 Tríade se estaba autoverificando con `integrity=degraded_safe`,
`tamper_detected=true` y dos desajustes contra su ancla —`schema_version` y
`manifest_hash`— mientras `/health/deep` respondía `healthy` con un 200. La
identidad sólo se comprobaba en el arranque (`single_port_app.py:55`) y su
resultado no llegaba a ningún endpoint: un desajuste posterior era invisible
hasta que alguien fuera a buscarlo a mano.
"""

from __future__ import annotations

from apps.routes import health

SANA = {
    "integrity": "ok",
    "degraded_mode": False,
    "tamper_detected": False,
    "mismatches": [],
    "schema_version": "036",
    "continuity_from_previous_run": True,
}
MANIPULADA = {
    "integrity": "degraded_safe",
    "degraded_mode": True,
    "tamper_detected": True,
    "mismatches": ["schema_version", "manifest_hash"],
    "schema_version": "036",
    "continuity_from_previous_run": False,
}


class _Continuity:
    def __init__(self, veredicto, *, registros):
        self._veredicto = veredicto
        self._registros = registros

    def verify(self, run_id=None, record=True):
        self._registros.append(record)
        return self._veredicto


def _parchear(monkeypatch, veredicto, registros):
    import triade.core.identity_continuity as ic

    monkeypatch.setattr(
        ic,
        "IdentityContinuity",
        lambda db_path: _Continuity(veredicto, registros=registros),
    )


def test_identidad_sana_no_degrada(monkeypatch):
    registros: list[bool] = []
    _parchear(monkeypatch, SANA, registros)

    bloque = health._identity()

    assert bloque["integrity_ok"] is True
    assert bloque["tamper_detected"] is False


def test_identidad_manipulada_se_ve_y_marca_no_ok(monkeypatch):
    registros: list[bool] = []
    _parchear(monkeypatch, MANIPULADA, registros)

    bloque = health._identity()

    assert bloque["integrity_ok"] is False
    assert bloque["tamper_detected"] is True
    assert bloque["mismatches"] == ["schema_version", "manifest_hash"]


def test_sondear_el_health_no_deja_fila_de_verificacion(monkeypatch):
    """Es un sondeo: no debe escribir una verificación por cada mirada."""
    registros: list[bool] = []
    _parchear(monkeypatch, SANA, registros)

    health._identity()

    assert registros == [False]


def test_si_no_se_puede_leer_la_identidad_no_se_declara_rota(monkeypatch):
    """`None` es «no se sabe», y no debe degradar a un organismo sano."""
    import triade.core.identity_continuity as ic

    def _explota(db_path):
        raise OSError("base ocupada")

    monkeypatch.setattr(ic, "IdentityContinuity", _explota)

    bloque = health._identity()

    assert bloque["integrity_ok"] is None
    assert bloque["error"] == "OSError"
