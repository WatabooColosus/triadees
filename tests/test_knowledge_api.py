"""Los endpoints que el usuario puede abrir para comprobar qué sabe Tríade.

Antes devolvían 404. Sin `/api/runtime/build` era además imposible distinguir
«esto no existe» de «el proceso corre código viejo».
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db = tmp_path / "triade.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE learning_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id TEXT UNIQUE,
            source_type TEXT, source_ref TEXT, title TEXT, content TEXT,
            normalized_summary TEXT, domain TEXT, risk_level TEXT, confidence REAL,
            utility REAL, status TEXT, verification_notes TEXT, created_at TEXT,
            updated_at TEXT, run_use_count INTEGER DEFAULT 0,
            run_outcome_scores TEXT, avg_outcome_score REAL DEFAULT 0)"""
    )
    conn.execute(
        "INSERT INTO learning_queue (candidate_id, title, content, status, source_ref,"
        " created_at, updated_at) VALUES ('c1','Titulo','contenido',"
        "'internally_checked','run:o','2026-07-01T00:00:00+00:00','2026-07-01T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()

    import apps.routes.knowledge as mod

    monkeypatch.setattr(mod, "DB_PATH", str(db))
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(mod.router)
    return TestClient(app)


def test_el_resumen_responde_200_y_cuenta_bien(client) -> None:
    r = client.get("/api/knowledge/summary")
    assert r.status_code == 200
    d = r.json()
    assert d["candidates"] == 1
    assert d["stable"] == 0
    assert d["evidence_verified"] == 0


def test_un_candidato_no_aparece_como_saber_estable(client) -> None:
    r = client.get("/api/knowledge?state=stable")
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_el_detalle_devuelve_origen_y_motivo(client) -> None:
    d = client.get("/api/knowledge/c1").json()
    assert d["knowledge_id"] == "c1"
    assert d["source_run_ids"] == ["run:o"]
    assert "no se muestra como saber" in d["reason"]


def test_un_saber_inexistente_da_404(client) -> None:
    assert client.get("/api/knowledge/no-existe").status_code == 404


def test_la_actividad_esta_ordenada_por_fecha(client) -> None:
    d = client.get("/api/learning/activity").json()
    marcas = [e["timestamp"] for e in d["events"] if e["timestamp"]]
    assert marcas == sorted(marcas, reverse=True)


def test_build_devuelve_sha_rama_y_db(client) -> None:
    d = client.get("/api/runtime/build").json()
    assert len(d["git_sha"]) in (7, 40) or d["git_sha"] == "unknown"
    assert d["branch"]
    assert d["db_exists"] is True
    assert d["knowledge_visibility_version"]


def test_la_api_lee_la_db_configurada(client, tmp_path: Path) -> None:
    d = client.get("/api/runtime/build").json()
    assert str(tmp_path) in d["db_path"]


def test_las_tareas_sin_efecto_se_declaran_como_tales(client) -> None:
    d = client.get("/api/learning/tasks").json()
    tipos = {t["task_type"]: t for t in d["tasks"]}
    assert "learning_evidence_generation" in tipos
    assert tipos["learning_evidence_generation"]["last_effect"] in (
        "never_scheduled",
        "alive_but_no_effect",
    )


def test_los_rechazos_tienen_endpoint_propio(client) -> None:
    assert client.get("/api/learning/rejections").status_code == 200


def test_last_used_esta_vacio_si_nada_se_uso(client) -> None:
    d = client.get("/api/learning/last-used").json()
    assert d["count"] == 0
