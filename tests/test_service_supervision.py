"""Un 200 en `/health/live` no prueba que Tríade vaya a volver si la matan.

Durante meses el organismo pasó por «Always-On» porque respondía mientras una
persona tuviera abierta la terminal donde lanzó `nohup uvicorn`. Nadie lo
supervisaba: al cerrar la sesión no volvía, y tras reiniciar el Studio tampoco.
El 2026-08-10, con la máquina 19 minutos arriba, había cero units instaladas y
nada escuchando en el 8010.

Lo que se comprueba aquí es la distinción que hacía falta y no existía: **quién
tiene el puerto**. Una unit puede estar `active` mientras el proceso que sirve
el tráfico es un huérfano lanzado a mano, y ese es precisamente el caso que hay
que poder ver — no un detalle teórico: el 2026-07-30 un `nohup ollama serve`
ganó la carrera por el puerto y dejó a la unit reiniciándose 150+ veces mientras
el tráfico lo atendía un proceso sin supervisor.

Por eso la pertenencia se decide contra el cgroup del PID que escucha, y no
preguntándole a systemd si la unit está viva.
"""

from __future__ import annotations

from typing import Any

import pytest

from triade.runtime import service_supervision as svc

_ACTIVE_UNIT = {
    "LoadState": "loaded",
    "ActiveState": "active",
    "SubState": "running",
    "UnitFileState": "enabled",
    "MainPID": "4242",
    "NRestarts": "2",
    "ExecMainStartTimestamp": "Mon 2026-08-10 23:40:12 UTC",
    "Result": "success",
    "ExecMainStatus": "0",
}


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    props: dict[str, str],
    pids: list[int],
    count: int | None,
    cgroup: str | None,
) -> None:
    monkeypatch.setattr(svc, "_systemctl_show", lambda *a, **k: props)
    monkeypatch.setattr(svc, "_listener_pids", lambda *a, **k: pids)
    monkeypatch.setattr(svc, "_listener_count", lambda *a, **k: count)
    monkeypatch.setattr(svc, "_cgroup_unit", lambda *a, **k: cgroup)


def test_proceso_dentro_de_la_unit_es_always_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch(
        monkeypatch,
        props=_ACTIVE_UNIT,
        pids=[4242],
        count=1,
        cgroup="triade-api.service",
    )
    result: dict[str, Any] = svc.build_service_supervision()

    assert result["service_managed"] is True
    assert result["always_on"] is True
    assert result["always_on_blockers"] == []
    assert result["manual_start_required"] is False
    assert result["listener_state"] == "healthy"
    assert result["restart_count"] == 2
    assert result["started_at"] == "2026-08-10T23:40:12+00:00"


def test_huerfano_en_el_puerto_no_cuenta_como_supervisado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La unit está activa, pero quien sirve el puerto no pertenece a ella."""
    _patch(
        monkeypatch,
        props=_ACTIVE_UNIT,
        pids=[9999],
        count=1,
        cgroup=None,  # lanzado a mano: no está en ningún cgroup de servicio
    )
    result = svc.build_service_supervision()

    assert result["service_managed"] is False
    assert result["always_on"] is False
    assert (
        "el proceso del puerto no está bajo el gestor de servicios"
        in result["always_on_blockers"]
    )


def test_dos_listeners_es_instancia_duplicada(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(
        monkeypatch,
        props=_ACTIVE_UNIT,
        pids=[4242, 4243],
        count=2,
        cgroup="triade-api.service",
    )
    result = svc.build_service_supervision()

    assert result["listener_state"] == "duplicate"
    assert result["always_on"] is False


def test_sin_listener_es_caido(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, props=_ACTIVE_UNIT, pids=[], count=0, cgroup=None)
    result = svc.build_service_supervision()

    assert result["listener_state"] == "failed"
    assert result["runtime_pid"] is None
    assert result["always_on"] is False


def test_sin_unit_instalada_no_inventa_cero_reinicios(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`systemctl show` contesta NRestarts=0 aunque la unit no exista.

    Publicar ese 0 diría «nunca se ha reiniciado», que suena a salud. Lo cierto
    es que no hay nada que reiniciar, y eso se dice con None.
    """
    _patch(
        monkeypatch,
        props={"LoadState": "not-found", "NRestarts": "0", "UnitFileState": ""},
        pids=[],
        count=0,
        cgroup=None,
    )
    result = svc.build_service_supervision()

    assert result["unit_known"] is False
    assert result["service_manager"] is None
    assert result["restart_count"] is None
    assert result["autostart_enabled"] is False
    assert result["manual_start_required"] is True
    assert "sin unit de servicio instalada" in result["always_on_blockers"]


def test_sin_systemd_no_revienta(monkeypatch: pytest.MonkeyPatch) -> None:
    """En CI no hay systemd ni `ss`: debe medir lo que pueda y no lanzar."""
    monkeypatch.setattr(svc, "_run", lambda argv: None)
    result = svc.build_service_supervision()

    assert result["always_on"] is False
    assert result["listener_count"] is None
    assert result["listener_state"] == "unknown"
    # La ruta de la base sí es medible sin systemd, y es la que decide si un
    # reinicio devolvió el mismo organismo o uno vacío.
    assert result["database"]["path"].endswith("triade.db")
