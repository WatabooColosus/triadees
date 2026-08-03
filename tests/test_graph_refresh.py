"""El panel de deuda decía la verdad sobre ficheros que ya no describían el repo.

El 2026-08-03 el informe siguió contando 31 módulos huérfanos durante dos horas
después de borrarlos: la estructura sale de artefactos, y en el Studio nadie los
regeneraba —el único disparador vivía en CI, sobre `pull_request`—. Estas
pruebas fijan el contrato del refrescador: no bloquea, no duplica escaneos, no
publica ficheros a medio escribir y no esconde sus fallos.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from triade.observability.refresh import GraphRefresher

REPO_ROOT = Path(__file__).resolve().parents[1]


def _fake_build(marker: str = "ok", *, delay: float = 0.0):
    """Sustituto de `build_all`: escribe lo mismo, sin los 53 s de AST."""

    def build_all(root, db_path, output, *, render=True):
        if delay:
            time.sleep(delay)
        output.mkdir(parents=True, exist_ok=True)
        (output / "import_graph.json").write_text(
            json.dumps({"nodes": [{"label": marker}], "edges": []}), encoding="utf-8"
        )
        (output / "index.json").write_text(
            json.dumps({"schema_version": 1, "marker": marker}), encoding="utf-8"
        )
        return {}

    return build_all


@pytest.fixture
def patched(monkeypatch):
    """Instala un `build_all` falso allí donde el refrescador lo importa."""

    def install(build_all):
        import scripts.build_internal_graphs as builder

        monkeypatch.setattr(builder, "build_all", build_all)

    return install


def test_sin_artefacto_esta_caducado_y_se_construye(tmp_path, patched):
    """Sin `index.json` no hay nada que servir: hay que generar, no esperar."""
    patched(_fake_build("primero"))
    refresher = GraphRefresher(REPO_ROOT, tmp_path / "graphs", stale_seconds=900)

    assert refresher.age_seconds() is None
    assert refresher.is_stale() is True
    assert refresher.request() == "started"
    assert refresher.wait(timeout=10) is True

    index = json.loads((tmp_path / "graphs" / "index.json").read_text())
    assert index["marker"] == "primero"
    assert refresher.is_stale() is False
    assert refresher.status()["builds"] == 1
    assert refresher.status()["last_error"] is None


def test_fresco_no_se_reconstruye(tmp_path, patched):
    """La regla es caducidad, no cada petición: un escaneo cuesta ~53 s."""
    patched(_fake_build("uno"))
    refresher = GraphRefresher(REPO_ROOT, tmp_path / "graphs", stale_seconds=900)
    refresher.request()
    refresher.wait(timeout=10)

    assert refresher.request() == "fresh"
    assert refresher.status()["builds"] == 1


def test_caducado_dispara_una_sola_reconstruccion(tmp_path, patched):
    """Diez lecturas concurrentes no pueden lanzar diez escaneos del AST."""
    gate = threading.Event()

    def blocking_build(root, db_path, output, *, render=True):
        gate.wait(timeout=10)
        return _fake_build("segundo")(root, db_path, output, render=render)

    patched(blocking_build)
    cache = tmp_path / "graphs"
    cache.mkdir()
    (cache / "index.json").write_text('{"schema_version": 1}', encoding="utf-8")

    refresher = GraphRefresher(REPO_ROOT, cache, stale_seconds=0.001)
    time.sleep(0.01)

    assert refresher.request() == "started"
    assert [refresher.request() for _ in range(9)] == ["running"] * 9

    gate.set()
    assert refresher.wait(timeout=10) is True
    assert refresher.status()["builds"] == 1


def test_la_publicacion_no_deja_ver_un_json_a_medias(tmp_path, patched):
    """Un lector durante la reconstrucción ve la generación anterior entera.

    `_load` se traga un JSON inválido devolviendo `None`, y entonces la categoría
    desaparece del informe y el total baja sin que nada haya mejorado. Por eso
    se construye aparte y se mueve con `os.replace`.
    """
    gate = threading.Event()
    seen: list[dict] = []

    def observed_build(root, db_path, output, *, render=True):
        output.mkdir(parents=True, exist_ok=True)
        (output / "import_graph.json").write_text("{ roto", encoding="utf-8")
        gate.set()
        time.sleep(0.2)
        return _fake_build("nuevo")(root, db_path, output, render=render)

    patched(observed_build)
    cache = tmp_path / "graphs"
    cache.mkdir()
    (cache / "import_graph.json").write_text(
        json.dumps({"nodes": [{"label": "viejo"}], "edges": []}), encoding="utf-8"
    )
    (cache / "index.json").write_text('{"marker": "viejo"}', encoding="utf-8")

    refresher = GraphRefresher(REPO_ROOT, cache, stale_seconds=0.001)
    time.sleep(0.01)
    refresher.request()

    gate.wait(timeout=10)
    # Mientras el fichero roto existe en el directorio de construcción, lo que
    # se sirve sigue siendo la generación anterior, y es JSON válido.
    seen.append(json.loads((cache / "import_graph.json").read_text()))
    assert seen[0]["nodes"][0]["label"] == "viejo"

    refresher.wait(timeout=10)
    assert json.loads((cache / "import_graph.json").read_text())["nodes"][0][
        "label"
    ] == "nuevo"


def test_el_fallo_se_reporta_y_espera_antes_de_reintentar(tmp_path, patched):
    """Un repo que no compila no puede provocar un escaneo por cada visita."""

    def broken_build(root, db_path, output, *, render=True):
        raise RuntimeError("el AST no se pudo leer")

    patched(broken_build)
    refresher = GraphRefresher(REPO_ROOT, tmp_path / "graphs", stale_seconds=0.001)

    assert refresher.request() == "started"
    refresher.wait(timeout=10)

    status = refresher.status()
    assert status["builds"] == 0
    assert "el AST no se pudo leer" in status["last_error"]
    assert refresher.request() == "cooldown"


def test_el_directorio_de_construccion_no_queda_tirado(tmp_path, patched):
    """Ni al terminar bien ni al fallar: el staging se limpia siempre."""
    patched(_fake_build("limpio"))
    cache = tmp_path / "graphs"
    refresher = GraphRefresher(REPO_ROOT, cache, stale_seconds=900)
    refresher.request()
    refresher.wait(timeout=10)

    assert not (cache.parent / f".{cache.name}.building").exists()
