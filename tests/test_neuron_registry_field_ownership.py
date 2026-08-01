"""Contrato de propiedad de campos del registro neuronal.

El defecto original (ver `test_neuron_registry_preserves_learning.py`) era un
caso particular de algo más general: `register()` trataba la ausencia de un
campo como una orden de borrado. Aquí se fija la regla para cada columna, y en
particular las que no pueden reducirse en silencio: permisos, restricciones,
evidencia exigida y estado.

Todo se comprueba leyendo SQLite directamente o con una instancia nueva del
registro, que es lo que de verdad simula un reinicio.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from triade.core.model_acquisition import ensure_specialized_model_neurons
from triade.core.neuron_creator import NeuronSpec
from triade.core.neuron_registry import NeuronRegistry

VISUAL = "Neurona Visual"


def _spec(name: str = VISUAL, **kwargs: Any) -> NeuronSpec:
    base: dict[str, Any] = {
        "mission": "Interpretar imágenes con evidencia.",
        "domain": "vision_image_understanding",
        "status": "experimental",
        "created_by": "model_acquisition_governed",
    }
    base.update(kwargs)
    return NeuronSpec(name=name, **base)


def _row(db: Path, name: str = VISUAL) -> dict[str, Any]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM neurons WHERE name = ?", (name,)).fetchone()
    conn.close()
    assert row is not None, f"no existe la neurona {name}"
    return dict(row)


def _touch(db: Path, name: str, **columns: str) -> None:
    """Fija columnas a un valor centinela, para detectar escrituras espurias."""
    conn = sqlite3.connect(db)
    sets = ", ".join(f"{c} = ?" for c in columns)
    conn.execute(f"UPDATE neurons SET {sets} WHERE name = ?", (*columns.values(), name))
    conn.commit()
    conn.close()


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "triade.db"


# ── Aprendizaje ───────────────────────────────────────────────────────────


def test_learned_fields_survive_a_silent_re_registration(db: Path) -> None:
    registry = NeuronRegistry(db)
    registry.register(
        _spec(triggers=["imagen", "foto"], success_metrics=["accuracy"]),
        contract_payload={
            "activation_policy": {"mode": "on_demand", "confidence": 0.7},
            "enriquecido": ["evidencia-1"],
        },
    )

    registry.register(_spec())  # un arranque que no declara nada

    row = _row(db)
    assert json.loads(row["triggers"]) == ["imagen", "foto"]
    assert json.loads(row["success_metrics"]) == ["accuracy"]
    assert json.loads(row["activation_policy"]) == {
        "mode": "on_demand",
        "confidence": 0.7,
    }
    assert json.loads(row["contract_json"])["enriquecido"] == ["evidencia-1"]


def test_learning_survives_a_new_registry_instance(db: Path) -> None:
    """Un reinicio de verdad: otra instancia, otra conexión."""
    NeuronRegistry(db).register(_spec(triggers=["imagen"]))
    NeuronRegistry(db).register(_spec())

    assert NeuronRegistry(db).get_neuron(VISUAL)["triggers"] == ["imagen"]


# ── Seguridad: nada se reduce en silencio ─────────────────────────────────


def test_forbidden_actions_and_evidence_only_grow(db: Path) -> None:
    registry = NeuronRegistry(db)
    registry.register(
        _spec(
            forbidden_actions=["modify_identity_core", "write_stable_memory"],
            evidence_required=["vision_eval_suite"],
        )
    )
    # Un registro posterior declara menos restricciones de las que ya había.
    registry.register(
        _spec(forbidden_actions=["run_shell_free"], evidence_required=["test_report"])
    )

    row = _row(db)
    assert set(json.loads(row["forbidden_actions"])) == {
        "modify_identity_core",
        "write_stable_memory",
        "run_shell_free",
    }
    assert set(json.loads(row["evidence_required"])) == {
        "vision_eval_suite",
        "test_report",
    }


def test_permissions_are_never_widened_by_merging(db: Path) -> None:
    """Los permisos se reemplazan, no se unen: unir sería ampliar."""
    registry = NeuronRegistry(db)
    registry.register(_spec(inputs_allowed=["image"], outputs_allowed=["text"]))
    registry.register(_spec(inputs_allowed=["pdf"], outputs_allowed=["json"]))

    row = _row(db)
    assert json.loads(row["inputs_allowed"]) == ["pdf"]
    assert json.loads(row["outputs_allowed"]) == ["json"]

    # Y un spec silencioso tampoco los borra.
    registry.register(_spec())
    row = _row(db)
    assert json.loads(row["inputs_allowed"]) == ["pdf"]
    assert json.loads(row["outputs_allowed"]) == ["json"]


def test_status_is_never_downgraded_by_re_registration(db: Path) -> None:
    registry = NeuronRegistry(db)
    registry.register(_spec(status="stable"))
    registry.register(_spec(status="experimental"))
    assert _row(db)["status"] == "stable"


def test_status_can_still_be_promoted_and_governed_downgrade_works(db: Path) -> None:
    registry = NeuronRegistry(db)
    registry.register(_spec(status="experimental"))
    registry.register(_spec(status="stable"))
    assert _row(db)["status"] == "stable"

    # Bajar exige la ruta gobernada, que sigue funcionando.
    registry.update_status(VISUAL, "quarantined")
    assert _row(db)["status"] == "quarantined"


# ── Identidad y procedencia ───────────────────────────────────────────────


def test_identity_and_provenance_are_immutable(db: Path) -> None:
    registry = NeuronRegistry(db)
    neuron_id = registry.register(_spec(created_by="humano_original"))
    _touch(db, VISUAL, created_at="2020-01-01 00:00:00")

    registry.register(_spec(created_by="bootstrap_impostor", triggers=["nuevo"]))

    row = _row(db)
    assert row["id"] == neuron_id
    assert row["created_by"] == "humano_original"
    assert row["created_at"] == "2020-01-01 00:00:00"


def test_updated_at_does_not_move_on_a_no_op(db: Path) -> None:
    registry = NeuronRegistry(db)
    registry.register(_spec(triggers=["imagen"]))
    _touch(db, VISUAL, updated_at="SIN-TOCAR")

    registry.register(_spec(triggers=["imagen"]))
    assert _row(db)["updated_at"] == "SIN-TOCAR"


def test_updated_at_moves_when_something_really_changes(db: Path) -> None:
    registry = NeuronRegistry(db)
    registry.register(_spec())
    _touch(db, VISUAL, updated_at="SIN-TOCAR")

    registry.register(_spec(mission="Misión distinta"))
    assert _row(db)["updated_at"] != "SIN-TOCAR"


# ── Actualización deliberada ──────────────────────────────────────────────


def test_an_explicit_field_can_still_be_cleared(db: Path) -> None:
    """Conservar no es volverse inmutable: vaciar a propósito sigue siendo posible."""
    registry = NeuronRegistry(db)
    registry.register(_spec(triggers=["obsoleto"]))
    registry.register(_spec(), explicit_fields={"triggers"})
    assert json.loads(_row(db)["triggers"]) == []


def test_replace_definition_overwrites_on_purpose(db: Path) -> None:
    registry = NeuronRegistry(db)
    registry.register(_spec(triggers=["viejo"], inputs_allowed=["image"]))
    registry.register(_spec(), conflict_policy="replace_definition")

    row = _row(db)
    assert json.loads(row["triggers"]) == []
    assert json.loads(row["inputs_allowed"]) == []
    # Ni siquiera una sobrescritura deliberada reescribe la procedencia.
    assert row["created_by"] == "model_acquisition_governed"


def test_create_if_missing_never_touches_an_existing_neuron(db: Path) -> None:
    registry = NeuronRegistry(db)
    neuron_id = registry.register(_spec(triggers=["imagen"], status="stable"))
    _touch(db, VISUAL, updated_at="SIN-TOCAR")

    assert registry.create_if_missing(_spec(mission="otra cosa")) == neuron_id

    row = _row(db)
    assert row["mission"] == "Interpretar imágenes con evidencia."
    assert row["updated_at"] == "SIN-TOCAR"
    assert json.loads(row["triggers"]) == ["imagen"]


def test_an_unknown_conflict_policy_is_rejected(db: Path) -> None:
    with pytest.raises(ValueError, match="conflict_policy"):
        NeuronRegistry(db).register(_spec(), conflict_policy="lo_que_sea")


# ── La rutina de arranque real ────────────────────────────────────────────


def test_specialized_bootstrap_is_idempotent_three_times(db: Path) -> None:
    """El caso que se veía en producción, con la rutina de verdad."""
    ensure_specialized_model_neurons(db)

    registry = NeuronRegistry(db)
    registry.register(
        _spec(triggers=["imagen", "foto", "captura"]),
    )
    registry.update_status(VISUAL, "stable")
    _touch(db, VISUAL, updated_at="SIN-TOCAR")
    antes = _row(db)

    for _ in range(3):
        ensure_specialized_model_neurons(db)

    despues = _row(db)
    assert despues == antes, "el arranque repetido modificó la neurona"
    assert json.loads(despues["triggers"]) == ["imagen", "foto", "captura"]
    assert despues["status"] == "stable"
    assert despues["updated_at"] == "SIN-TOCAR"


def test_two_neurons_do_not_mix_state(db: Path) -> None:
    ensure_specialized_model_neurons(db)
    registry = NeuronRegistry(db)
    registry.register(_spec(VISUAL, triggers=["imagen"]))
    registry.register(
        _spec("Neurona de Código y Reparación", triggers=["pytest", "traceback"])
    )
    ensure_specialized_model_neurons(db)

    assert json.loads(_row(db, VISUAL)["triggers"]) == ["imagen"]
    assert json.loads(_row(db, "Neurona de Código y Reparación")["triggers"]) == [
        "pytest",
        "traceback",
    ]


# ── Integridad ────────────────────────────────────────────────────────────


def test_a_hostile_name_does_not_reach_sql(db: Path) -> None:
    hostil = "x'; DROP TABLE neurons; --"
    registry = NeuronRegistry(db)
    registry.register(_spec(hostil, triggers=["a"]))
    registry.register(_spec(hostil))

    assert json.loads(_row(db, hostil)["triggers"]) == ["a"]
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT count(*) FROM neurons").fetchone()[0] == 1
    conn.close()


def test_json_round_trips_without_corruption(db: Path) -> None:
    raros = ['comillas "dobles"', "apóstrofo ' simple", "emoji 🧠", "salto\nlínea"]
    registry = NeuronRegistry(db)
    registry.register(_spec(triggers=raros))
    registry.register(_spec())

    assert NeuronRegistry(db).get_neuron(VISUAL)["triggers"] == raros


def test_database_stays_consistent(db: Path) -> None:
    ensure_specialized_model_neurons(db)
    NeuronRegistry(db).register(_spec(triggers=["imagen"]))
    ensure_specialized_model_neurons(db)

    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_foundational_bootstrap_does_not_rewrite_on_every_start(db: Path) -> None:
    """Las diez fundacionales se reescribían enteras en cada arranque.

    Declaran triggers fijos, así que no bastaba con proteger el silencio: la
    rutina tenía que dejar de actualizar.
    """
    from triade.core.foundational_neurons import ensure_foundational_neurons

    ensure_foundational_neurons(db)

    registry = NeuronRegistry(db)
    aprendidos = ["duda", "contradicción", "evidencia"]
    registry.register(
        _spec("Neurona Central", mission="Coordinar.", triggers=aprendidos)
    )
    _touch(db, "Neurona Central", updated_at="SIN-TOCAR")

    ensure_foundational_neurons(db)
    ensure_foundational_neurons(db)

    row = _row(db, "Neurona Central")
    assert json.loads(row["triggers"]) == aprendidos
    assert row["status"] == "stable"
    assert row["updated_at"] == "SIN-TOCAR"
