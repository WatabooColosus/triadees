"""Apagar es parar lo que arrancaste, no dejar que te rematen.

Hasta el 2026-08-12 el arranque encendía seis subsistemas —always_on, workers,
life_pulse, registro federado, metabolismo y watchdog— y el cierre paraba dos.
Los demás seguían vivos, el proceso no terminaba, y systemd lo remataba con
SIGKILL al vencer `TimeoutStopSec`, dejando la unit en `failed`.

Un SIGKILL no es un apagado: las tareas en vuelo se quedan en `running`, los
leases sin devolver y la base sin punto de control. Es el estado en que apareció
Tríade tras el apagado del servidor del 2026-08-11.
"""

from __future__ import annotations

from typing import Any

import apps.single_port_app as app_module

DB = "triade/memory/triade.db"


class _Coordinator:
    def __init__(self, registro: dict[str, Any]) -> None:
        self._registro = registro

    def stop(self, timeout: float = 30.0) -> dict[str, Any]:
        self._registro["metabolism_timeout"] = timeout
        return {"status": "stopped"}


def _parchear(monkeypatch, registro: dict[str, Any], *, revienta: str = "") -> None:
    import triade.metabolism.coordinator as metabolism
    from triade.core import always_on, worker_autostart

    def _anotar(nombre: str):
        def _fn(*args, **kwargs):
            registro[nombre] = True
            if revienta == nombre:
                raise RuntimeError(f"{nombre} falló al parar")
            return {"status": "stopped"}

        return _fn

    monkeypatch.setattr(worker_autostart, "stop_workers_always_on", _anotar("workers"))
    monkeypatch.setattr(always_on, "stop_always_on", _anotar("always_on"))

    def _get_coordinator(db_path=DB):
        registro["metabolism"] = True
        if revienta == "metabolism":
            raise RuntimeError("metabolism falló al parar")
        return _Coordinator(registro)

    monkeypatch.setattr(metabolism, "get_coordinator", _get_coordinator)
    monkeypatch.setattr(
        app_module.NODE_LIVE_REGISTRY, "stop", _anotar("node_live_registry")
    )
    monkeypatch.setattr(app_module.LIFE_PULSE, "stop", _anotar("life_pulse"))


def test_se_para_todo_lo_que_el_arranque_levanto(monkeypatch):
    registro: dict[str, Any] = {}
    _parchear(monkeypatch, registro)

    resultados = app_module._stop_background(DB)

    for subsistema in (
        "workers",
        "metabolism",
        "always_on",
        "node_live_registry",
        "life_pulse",
    ):
        assert registro.get(subsistema), f"{subsistema} no se paró al apagar"
        assert subsistema in resultados


def test_el_metabolismo_no_se_lleva_el_plazo_entero(monkeypatch):
    """`stop()` espera 30 s por defecto, que es el plazo completo de systemd."""
    registro: dict[str, Any] = {}
    _parchear(monkeypatch, registro)

    app_module._stop_background(DB)

    assert registro["metabolism_timeout"] < app_module._SHUTDOWN_BUDGET_SECONDS


def test_si_uno_revienta_los_demas_se_paran_igual(monkeypatch):
    """Si no, un fallo al parar deja vivo todo lo que venía detrás."""
    registro: dict[str, Any] = {}
    _parchear(monkeypatch, registro, revienta="workers")

    resultados = app_module._stop_background(DB)

    assert resultados["workers"]["status"] == "error"
    for subsistema in ("metabolism", "always_on", "node_live_registry", "life_pulse"):
        assert registro.get(subsistema), f"{subsistema} no se paró tras el fallo"


def test_el_presupuesto_cabe_holgado_en_el_plazo_de_systemd():
    """La unit remata a los 30 s; hay que terminar cómodamente antes."""
    unit = (
        app_module.__file__.rsplit("/apps/", 1)[0]
        + "/deploy/systemd/triade-api.service"
    )
    with open(unit, encoding="utf-8") as fh:
        texto = fh.read()
    assert "TimeoutStopSec=30" in texto
    assert app_module._SHUTDOWN_BUDGET_SECONDS <= 15.0
