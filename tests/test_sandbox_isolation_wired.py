"""El sandbox declaraba límites que no aplicaba y afirmaba lo que no medía.

`SANDBOX_POLICY` publica `max_timeout_seconds` y `max_memory_mb`;
`run_in_sandbox` recibía un `timeout` que no usaba en ninguna línea, y devolvía
`network_used: False` y `writes_outside_sandbox: False` codificados a mano, sin
instrumentación de red ni de escrituras que los respaldara.

Enfrente, `triade/sandbox/isolation.py` tenía 187 líneas describiendo CPU, RAM,
PID y tiempo, cero importadores, y un `enforce()` que devolvía siempre
`violations: []` sin mirar nada — un control que decía «enforced» pasara lo que
pasara, que es peor que no tener control, porque quien lee la respuesta cree que
hubo uno.

Se conectan los dos: el consumo real se mide y se compara con lo declarado, la
ejecución queda registrada, y lo que no se puede medir se declara como tal
en vez de darse por cumplido.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from triade.sandbox.executor import run_in_sandbox
from triade.sandbox.isolation import SandboxLimits, SandboxPolicy


def test_enforce_detecta_un_exceso_real(tmp_path: Path) -> None:
    """Antes devolvía cero violaciones aunque la tarea tardara una hora."""
    policy = SandboxPolicy(tmp_path / "triade.db")
    limits = SandboxLimits(cpu_seconds=1, timeout_seconds=2)

    veredicto = policy.enforce(
        limits, {"duration_seconds": 9.0, "cpu_seconds": 5.0}
    )

    assert veredicto["status"] == "violations_detected"
    assert len(veredicto["violations"]) == 2
    assert any("timeout_seconds" in v for v in veredicto["violations"])
    assert any("cpu_seconds" in v for v in veredicto["violations"])


def test_enforce_no_inventa_un_incumplimiento(tmp_path: Path) -> None:
    """Detectar de más también es mentir: una tarea dentro de límites está limpia."""
    policy = SandboxPolicy(tmp_path / "triade.db")

    veredicto = policy.enforce(
        SandboxLimits(cpu_seconds=10, timeout_seconds=30),
        {"duration_seconds": 0.01, "cpu_seconds": 0.01},
    )

    assert veredicto["status"] == "clean"
    assert veredicto["violations"] == []


def test_enforce_declara_lo_que_no_mide(tmp_path: Path) -> None:
    """No saber no es estar bien, y el informe tiene que distinguirlo.

    La memoria no se mide porque `ru_maxrss` es marca de agua de todo el proceso:
    restarla entre dos puntos no dice lo que gastó una tarea.
    """
    policy = SandboxPolicy(tmp_path / "triade.db")

    veredicto = policy.enforce(SandboxLimits(), {"duration_seconds": 0.1})

    assert "memory_mb" in veredicto["unmeasured"]
    assert veredicto["enforcement"] == "post_hoc_detection", (
        "el contrato tiene que decir que detecta, no que impide"
    )


def test_el_ejecutor_mide_el_consumo_de_cada_tarea(tmp_path: Path) -> None:
    resultado = run_in_sandbox("sha256", {"text": "hola"}, runs_dir=tmp_path / "runs")

    assert resultado["status"] == "completed"
    observado = resultado["limits"]["observed"]
    assert observado["duration_seconds"] >= 0
    assert observado["cpu_seconds"] >= 0
    assert resultado["limits"]["status"] == "clean"


def test_ninguna_tarea_de_la_whitelist_puede_tocar_red_ni_shell() -> None:
    """Los `False` del informe se sostienen leyendo el módulo, no por instrumentación.

    Esta prueba es lo que impide que dejen de ser ciertos sin que nadie se entere:
    el día que una tarea nueva importe `socket` o `subprocess`, el informe seguiría
    diciendo `network_used: False` y aquí saltará antes (F-054).
    """
    fuente = (
        Path(__file__).resolve().parents[1] / "triade" / "sandbox" / "executor.py"
    ).read_text(encoding="utf-8")
    for prohibido in ("import socket", "import requests", "import urllib", "import subprocess"):
        assert prohibido not in fuente, (
            f"{prohibido} en el ejecutor: `network_used: False` dejaría de ser cierto"
        )


def test_cada_ejecucion_queda_registrada(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`sandbox_replay` existía y estaba vacía porque nadie escribía en ella."""
    db = tmp_path / "triade.db"
    from triade.sandbox import executor

    monkeypatch.setattr(executor, "_isolation_policy", lambda: SandboxPolicy(db))

    run_in_sandbox("sha256", {"text": "traza"}, runs_dir=tmp_path / "runs")

    with sqlite3.connect(db) as conn:
        filas = conn.execute(
            "SELECT task_type, success, duration_ms FROM sandbox_replay"
        ).fetchall()

    assert len(filas) == 1
    assert filas[0][0] == "sha256"
    assert filas[0][1] == 1
    assert filas[0][2] >= 0


def test_sin_base_el_sandbox_sigue_ejecutando(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Medir es deseable; ejecutar es obligatorio. El orden importa."""
    from triade.sandbox import executor

    monkeypatch.setattr(executor, "_isolation_policy", lambda: None)

    resultado = run_in_sandbox("echo", {"text": "y"}, runs_dir=tmp_path / "runs")

    assert resultado["status"] == "completed"
    assert "limits" not in resultado, "sin política no se inventa un veredicto"
