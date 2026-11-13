"""Un adaptador sólo se activa sobre el modelo para el que fue entrenado.

`governed_peft_versions` no tenía columna `base_model`, así que la gobernanza de
servido no podía expresar a qué modelo pertenece un adaptador — y el manifiesto
sí lo declaraba desde el principio, se descartaba al inscribirlo.

Estado real el 2026-08-03: los dos adaptadores entrenados declaran
`Qwen/Qwen2.5-0.5B-Instruct`, y el runtime sirve qwen2.5:3b-instruct, qwen3:4b,
qwen2.5-coder:3b, qwen3:1.7b, gemma3:4b y nomic-embed-text. Ninguno es el modelo
base del adaptador. Nada impedía activar un adaptador de 0.5B sobre un modelo de
4B, ni sobre otra familia entera, y con firma humana encima.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from triade.training.serving_governance import (
    GovernedPeftServing,
    normalize_model_id,
)

#: Los seis que sirve Ollama en el Studio, tal cual los devuelve `/api/tags`.
SERVIDOS_REALES = [
    "gemma3:4b",
    "qwen3:4b",
    "nomic-embed-text:latest",
    "qwen2.5-coder:3b",
    "qwen3:1.7b",
    "qwen2.5:3b-instruct",
]


@pytest.mark.parametrize(
    ("declarado", "servido"),
    [
        ("Qwen/Qwen2.5-0.5B-Instruct", "qwen2.5:0.5b-instruct"),
        ("Qwen/Qwen2.5-3B-Instruct", "qwen2.5:3b-instruct"),
        ("google/gemma-3-4b", "gemma3:4b"),
    ],
)
def test_el_mismo_modelo_se_reconoce_entre_proveedores(
    declarado: str, servido: str
) -> None:
    """HuggingFace y Ollama nombran el mismo modelo distinto."""
    assert normalize_model_id(declarado) == normalize_model_id(servido)


@pytest.mark.parametrize(
    ("declarado", "servido"),
    [
        # El caso real: 0.5B entrenado, 3B servido. Misma familia, otro modelo.
        ("Qwen/Qwen2.5-0.5B-Instruct", "qwen2.5:3b-instruct"),
        ("Qwen/Qwen2.5-0.5B-Instruct", "gemma3:4b"),
        ("Qwen/Qwen2.5-3B-Instruct", "qwen3:4b"),
    ],
)
def test_modelos_distintos_no_se_confunden(declarado: str, servido: str) -> None:
    assert normalize_model_id(declarado) != normalize_model_id(servido)


def test_un_nombre_vacio_no_casa_con_nada() -> None:
    """Sin procedencia declarada no hay compatibilidad que verificar."""
    assert normalize_model_id("") == ""
    assert normalize_model_id("   ") == ""


def _canary_listo(
    db: Path, *, base_model: str, servidos: list[str]
) -> tuple[GovernedPeftServing, str]:
    """Inscribe a mano un canary que ya pasó su observación.

    Se escribe directo para no arrastrar el fixture de integridad y dataset:
    aquí se mide la puerta de modelo base, no el bundle.
    """
    serving = GovernedPeftServing(db, db.parent, served_models=servidos)
    version_id = "peft-test-0001"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """INSERT INTO governed_peft_versions
            (version_id, adapter_path, integrity_sha256, dataset_id, status,
             traffic_percent, baseline_quality, rollback_ref, approved_by,
             previous_version_id, created_at, updated_at, base_model)
            VALUES (?, 'x', 'sha', 'ds', 'canary', 5.0, -1.0, 'rb', NULL, NULL,
                    '2026-08-03T00:00:00Z', '2026-08-03T00:00:00Z', ?)""",
            (version_id, base_model),
        )
        conn.execute(
            "INSERT INTO governed_peft_observations VALUES "
            "('po-1', ?, 1.0, 10.0, 1, 'test:evidence', '2026-08-03T00:00:00Z')",
            (version_id,),
        )
    return serving, version_id


def test_no_se_activa_un_adaptador_de_un_modelo_que_no_se_sirve(
    tmp_path: Path,
) -> None:
    """El caso exacto de la base viva: adaptador 0.5B, runtime sin 0.5B."""
    serving, version_id = _canary_listo(
        tmp_path / "triade.db",
        base_model="Qwen/Qwen2.5-0.5B-Instruct",
        servidos=SERVIDOS_REALES,
    )

    resultado = serving.activate(version_id, approved_by="Santiago")

    assert resultado["status"] == "blocked"
    assert resultado["reason"] == "base_model_not_served"
    assert resultado["base_model"] == "Qwen/Qwen2.5-0.5B-Instruct"


def test_se_activa_cuando_el_modelo_base_si_esta_servido(tmp_path: Path) -> None:
    """La puerta filtra, no cierra: con el modelo correcto deja pasar."""
    serving, version_id = _canary_listo(
        tmp_path / "triade.db",
        base_model="Qwen/Qwen2.5-3B-Instruct",
        servidos=SERVIDOS_REALES,
    )

    resultado = serving.activate(version_id, approved_by="Santiago")

    assert resultado["status"] == "active"
    assert resultado["version_id"] == version_id


def test_sin_procedencia_declarada_tampoco_se_activa(tmp_path: Path) -> None:
    """Las filas anteriores a la columna tienen `base_model` vacío.

    No se activa lo que no se puede verificar, aunque venga firmado.
    """
    serving, version_id = _canary_listo(
        tmp_path / "triade.db", base_model="", servidos=SERVIDOS_REALES
    )

    resultado = serving.activate(version_id, approved_by="Santiago")

    assert resultado["status"] == "blocked"
    assert resultado["reason"] == "base_model_not_served"
    assert resultado["base_model"] == "UNKNOWN"


def test_sin_ollama_no_se_activa_a_ciegas(tmp_path: Path) -> None:
    """Si no se puede saber qué hay servido, la puerta cierra."""
    serving, version_id = _canary_listo(
        tmp_path / "triade.db",
        base_model="Qwen/Qwen2.5-3B-Instruct",
        servidos=[],
    )

    resultado = serving.activate(version_id, approved_by="Santiago")

    assert resultado["status"] == "blocked"
    assert resultado["reason"] == "base_model_not_served"


def test_la_aprobacion_humana_sigue_siendo_obligatoria(tmp_path: Path) -> None:
    """La puerta nueva se añade a las que ya había, no las sustituye."""
    serving, version_id = _canary_listo(
        tmp_path / "triade.db",
        base_model="Qwen/Qwen2.5-3B-Instruct",
        servidos=SERVIDOS_REALES,
    )

    assert serving.activate(version_id, approved_by="")["reason"] == (
        "named_human_approval_required"
    )


def test_canary_incompatible_se_retira_sin_borrar_observaciones(tmp_path: Path) -> None:
    serving, version_id = _canary_listo(
        tmp_path / "triade.db",
        base_model="Qwen/Qwen2.5-0.5B-Instruct",
        servidos=SERVIDOS_REALES,
    )

    result = serving.retire_incompatible(version_id, approved_by="Santiago")

    assert result["status"] == "retired"
    assert result["reason"] == "base_model_not_served"
    assert result["observations_preserved"] is True
    with sqlite3.connect(tmp_path / "triade.db") as conn:
        status, approved_by = conn.execute(
            "SELECT status,approved_by FROM governed_peft_versions WHERE version_id=?",
            (version_id,),
        ).fetchone()
        observations = conn.execute(
            "SELECT COUNT(*) FROM governed_peft_observations WHERE version_id=?",
            (version_id,),
        ).fetchone()[0]
    assert (status, approved_by, observations) == ("retired", "Santiago", 1)


def test_no_se_retira_un_canary_compatible(tmp_path: Path) -> None:
    serving, version_id = _canary_listo(
        tmp_path / "triade.db",
        base_model="Qwen/Qwen2.5-3B-Instruct",
        servidos=SERVIDOS_REALES,
    )

    assert serving.retire_incompatible(version_id, approved_by="Santiago") == {
        "status": "blocked",
        "reason": "base_model_is_served",
    }
