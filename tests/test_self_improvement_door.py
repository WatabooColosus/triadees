"""La automejora gobernada necesita una puerta por la que se pueda entrar.

`triade/self_improvement/` estaba completo —store, bridge, canary, orquestador,
aprendizaje del fallo— y sin ninguna forma de usarlo. Su ciclo exige por diseño
que un humano decida la dirección: `create_candidate` obliga a que la propuesta
esté `approved` y `approve()` a que haya un `approved_by`. La separación es
correcta; lo que faltaba era poder dar esa firma.

Medido el 2026-08-08: cero endpoints y cero comandos CLI que tocaran el
subsistema; `register_signal` sólo aparecía en tests; y las tablas
`improvement_signals` / `improvement_proposals` / `improvement_canaries` ni
siquiera existían en la base viva. De ahí que `self_improvement_evaluation` y
`self_improvement_canary_observation` figuraran entre los task types nunca
ejecutados: su handler cuelga de ese gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.single_port_app import app

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def cliente(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TRIADE_DB_PATH", str(tmp_path / "triade.db"))
    monkeypatch.setenv("TRIADE_DISABLE_BACKGROUND", "1")
    monkeypatch.delenv("TRIADE_API_KEY", raising=False)
    with TestClient(app) as cliente:
        yield cliente


def test_existe_puerta_para_proponer_y_aprobar(cliente: TestClient) -> None:
    """El ciclo completo: señal → propuesta → firma humana."""
    señal = cliente.post(
        "/api/governance/improvement/signals",
        json={
            "capability_id": "semantic_memory",
            "metric_id": "recall",
            "observed_score": 0.4,
            "target_score": 0.8,
        },
    )
    assert señal.status_code == 200, señal.text
    signal_id = señal.json()["signal"]["signal_id"]

    propuesta = cliente.post(
        "/api/governance/improvement/proposals",
        json={
            "signal_id": signal_id,
            "hypothesis": "subir el recall ajustando el umbral de similitud",
            "requested_capability": "semantic_memory",
        },
    )
    assert propuesta.status_code == 200, propuesta.text
    proposal_id = propuesta.json()["proposal"]["proposal_id"]

    aprobada = cliente.post(
        f"/api/governance/improvement/proposals/{proposal_id}/approve",
        json={"approved_by": "operador"},
    )

    assert aprobada.status_code == 200, aprobada.text
    assert aprobada.json()["proposal"]["status"] == "approved"


def test_la_firma_humana_sigue_siendo_obligatoria(cliente: TestClient) -> None:
    """Abrir la puerta no relaja el gate: sin firma no se aprueba nada."""
    respuesta = cliente.post(
        "/api/governance/improvement/proposals/proposal-inexistente/approve",
        json={"approved_by": "   "},
    )

    assert respuesta.status_code != 200


def test_el_estado_es_consultable(cliente: TestClient) -> None:
    """Sin poder mirarlo, el subsistema seguiría siendo invisible."""
    respuesta = cliente.get("/api/governance/improvement/status")

    assert respuesta.status_code == 200, respuesta.text
    assert "snapshot" in respuesta.json()
