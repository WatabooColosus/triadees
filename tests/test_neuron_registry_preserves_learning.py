"""Registrar una neurona que ya existe no puede borrar lo que aprendió.

Encontrado midiendo, no leyendo (2026-07-31):

1. Se escriben los triggers aprendidos en producción → quedan bien.
2. Se reinicia el servidor.
3. Los triggers vuelven a `[]`, con `updated_at` justo en el arranque.

`ensure_specialized_model_neurons()` recrea `Neurona Visual` y `Neurona de Código
y Reparación` desde un `NeuronSpec` fijo que **no declara triggers**, y
`register()` hace `ON CONFLICT(name) DO UPDATE SET triggers = excluded.triggers`.
Como el spec no trae ninguno, escribe `[]` encima.

Una rutina llamada "asegurar que existe" estaba **destruyendo estado aprendido en
cada arranque**. Y explica algo que parecía otra cosa: esas dos neuronas no
tenían triggers vacíos porque nadie se los hubiera puesto, sino porque cualquiera
que lo hiciera —una persona o la propia neurona— los perdía al siguiente
reinicio.

La corrección es estrecha a propósito: si el spec entrante **no declara**
triggers, se conservan los existentes. Si los declara, mandan ellos. "No tengo
opinión" y "quiero que esté vacío" dejan de ser lo mismo.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from triade.core.neuron_creator import NeuronSpec
from triade.core.neuron_registry import NeuronRegistry


def _spec(name: str = "Neurona Visual", **kwargs: object) -> NeuronSpec:
    return NeuronSpec(
        name=name,
        mission="Interpretar imágenes con evidencia y describir límites.",
        domain="vision_image_understanding",
        status="experimental",
        created_by="test",
        **kwargs,  # type: ignore[arg-type]
    )


def _triggers(db: Path, name: str) -> list[str]:
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT triggers FROM neurons WHERE name = ?", (name,)).fetchone()
    conn.close()
    raw = row[0] if row else "[]"
    return list(json.loads(raw or "[]"))


def test_re_registering_keeps_learned_triggers(tmp_path: Path) -> None:
    """El defecto exacto: el arranque borraba lo aprendido."""
    db = tmp_path / "triade.db"
    registry = NeuronRegistry(db)
    registry.register(_spec())

    # La neurona aprende de su propia carta.
    from triade.core.neuron_trigger_learning import NeuronTriggerLearner

    NeuronTriggerLearner(db).apply()
    aprendidos = _triggers(db, "Neurona Visual")
    assert "imagen" in aprendidos

    # Un arranque vuelve a llamar a `ensure_...`, que re-registra sin triggers.
    registry.register(_spec())

    assert _triggers(db, "Neurona Visual") == aprendidos, (
        "el re-registro borró los triggers aprendidos"
    )


def test_an_explicit_spec_still_wins(tmp_path: Path) -> None:
    """Conservar no puede significar volverse inmutable.

    Si alguien declara triggers a propósito, mandan ellos: la corrección
    distingue «no tengo opinión» de «quiero que esté vacío», no bloquea la
    segunda.
    """
    db = tmp_path / "triade.db"
    registry = NeuronRegistry(db)
    registry.register(_spec(triggers=["viejo"]))
    registry.register(_spec(triggers=["nuevo", "declarado"]))
    assert _triggers(db, "Neurona Visual") == ["nuevo", "declarado"]


def test_first_registration_is_unaffected(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    NeuronRegistry(db).register(_spec(triggers=["inicial"]))
    assert _triggers(db, "Neurona Visual") == ["inicial"]


def test_a_neuron_that_never_had_triggers_stays_empty(tmp_path: Path) -> None:
    """No se inventa nada: conservar vacío es conservar."""
    db = tmp_path / "triade.db"
    registry = NeuronRegistry(db)
    registry.register(_spec())
    registry.register(_spec())
    assert _triggers(db, "Neurona Visual") == []


def test_other_fields_still_update_on_re_registration(tmp_path: Path) -> None:
    """La corrección es estrecha: solo protege `triggers`.

    La misión y el dominio deben seguir actualizándose desde el spec, que es su
    fuente de verdad.
    """
    db = tmp_path / "triade.db"
    registry = NeuronRegistry(db)
    registry.register(_spec())
    spec = _spec()
    spec.mission = "Misión corregida"
    registry.register(spec)

    conn = sqlite3.connect(db)
    mission = conn.execute(
        "SELECT mission FROM neurons WHERE name = ?", ("Neurona Visual",)
    ).fetchone()[0]
    conn.close()
    assert mission == "Misión corregida"
