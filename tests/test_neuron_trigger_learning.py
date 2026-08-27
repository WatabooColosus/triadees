"""Una neurona aprende sus palabras de activación de su propia carta, no de la nada.

La diferencia importa más de lo que parece. Si una neurona pudiera derivar
triggers del texto de las conversaciones, aprendería a activarse **donde hay
tráfico**, no donde es útil — y acabaría capturando todo. Eso es concederse
alcance, que es justo la deriva que este runtime existe para impedir.

Aquí solo puede leer `mission` y `domain`: campos que escribió una persona al
crearla y que ella no modifica. Aprender significa *darse cuenta de lo que ya se
declaró que era*.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from triade.core.neuron_trigger_learning import (
    MAX_LEARNED_TRIGGERS,
    NeuronTriggerLearner,
    derive_triggers,
)

VISUAL = {
    "domain": "vision_image_understanding",
    "mission": (
        "Interpretar imágenes con evidencia y describir límites; "
        "no generar imágenes sin un motor generativo."
    ),
}
CODIGO = {
    "domain": "code_repair_build_tests",
    "mission": (
        "Analizar, probar y proponer reparaciones de código mediante sandbox "
        "y comandos permitidos."
    ),
}


# ── qué aprende ─────────────────────────────────────────────────────────


def test_the_visual_neuron_learns_its_own_words() -> None:
    triggers = derive_triggers(VISUAL)
    assert "imagen" in triggers
    assert "vision" in triggers


def test_the_code_neuron_learns_its_own_words() -> None:
    triggers = derive_triggers(CODIGO)
    assert "codigo" in triggers
    assert "sandbox" in triggers


def test_accents_do_not_split_a_word_in_two() -> None:
    """«imágenes» en la carta debe casar con «imagen» en la pregunta."""
    assert "imagen" in derive_triggers(VISUAL)


def test_a_neuron_that_declares_nothing_learns_nothing() -> None:
    """Y está bien: quien no sabe decir para qué sirve no debe atraer tráfico."""
    assert derive_triggers({"mission": "", "domain": ""}) == []


# ── los límites, que son lo que hace esto aceptable ─────────────────────


def test_generic_intent_words_are_never_learned() -> None:
    """`quiero` habría capturado media conversación.

    Salió de una neurona cuya misión era "Quiero informacion sobre la Banda
    Epica". Habría respondido a «quiero aprender a dibujar», que es de otra.
    """
    triggers = derive_triggers(
        {"domain": "system_governance", "mission": "Quiero informacion sobre la Banda"}
    )
    assert "quiero" not in triggers
    assert "informacion" not in triggers
    assert "banda" in triggers, "pero el tema real sí debe quedarse"


def test_the_number_of_learned_terms_is_capped() -> None:
    """Una misión larga no puede convertirse en una red de arrastre."""
    long_mission = " ".join(f"termino{i}largo" for i in range(40))
    assert len(derive_triggers({"mission": long_mission, "domain": ""})) <= (
        MAX_LEARNED_TRIGGERS
    )


def test_short_terms_are_rejected() -> None:
    """Un término corto coincide con demasiadas palabras y activa siempre."""
    triggers = derive_triggers({"mission": "api rest web ssh", "domain": ""})
    assert all(len(t) >= 4 for t in triggers)


def test_learning_only_reads_the_charter_not_conversations() -> None:
    """El contrato del módulo: nada de texto de usuario entra aquí.

    `derive_triggers` recibe la neurona y nada más. No hay parámetro por el que
    colar lo que dijo alguien en un chat, y eso es deliberado.
    """
    import inspect

    params = set(inspect.signature(derive_triggers).parameters)
    assert params == {"neuron"}


# ── persistencia ────────────────────────────────────────────────────────


def _db(tmp_path: Path, neurons: list[tuple[str, str, str, str]]) -> Path:
    path = tmp_path / "triade.db"
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE neurons (id INTEGER PRIMARY KEY, name TEXT, mission TEXT,
        domain TEXT, triggers TEXT, status TEXT, updated_at TEXT)"""
    )
    for index, (name, mission, domain, triggers) in enumerate(neurons, start=1):
        conn.execute(
            "INSERT INTO neurons (id,name,mission,domain,triggers,status) "
            "VALUES (?,?,?,?,?,'experimental')",
            (index, name, mission, domain, triggers),
        )
    conn.commit()
    conn.close()
    return path


def test_plan_does_not_write_anything(tmp_path: Path) -> None:
    """Un cambio que altera qué neuronas reciben tráfico debe poder mirarse antes."""
    path = _db(tmp_path, [("Visual", VISUAL["mission"], VISUAL["domain"], "[]")])
    learner = NeuronTriggerLearner(path)
    proposals = learner.plan()
    assert len(proposals) == 1
    assert "imagen" in proposals[0]["learned_triggers"]

    conn = sqlite3.connect(path)
    stored = conn.execute("SELECT triggers FROM neurons WHERE id=1").fetchone()[0]
    conn.close()
    assert stored == "[]", "plan() escribió en la base"


def test_apply_writes_the_learned_terms(tmp_path: Path) -> None:
    path = _db(tmp_path, [("Visual", VISUAL["mission"], VISUAL["domain"], "[]")])
    report = NeuronTriggerLearner(path).apply()
    assert report["updated"] == 1
    assert report["self_granted_scope"] is False

    conn = sqlite3.connect(path)
    stored = json.loads(
        conn.execute("SELECT triggers FROM neurons WHERE id=1").fetchone()[0]
    )
    conn.close()
    assert "imagen" in stored


def test_human_declared_triggers_are_never_overwritten(tmp_path: Path) -> None:
    """Aprender no puede significar pisar lo que decidió una persona."""
    path = _db(
        tmp_path,
        [("Visual", VISUAL["mission"], VISUAL["domain"], '["solo_esto_quiero"]')],
    )
    learner = NeuronTriggerLearner(path)
    assert learner.plan() == []

    learner.apply()
    conn = sqlite3.connect(path)
    stored = json.loads(
        conn.execute("SELECT triggers FROM neurons WHERE id=1").fetchone()[0]
    )
    conn.close()
    assert stored == ["solo_esto_quiero"]


def test_lifecycle_triggers_do_not_count_as_declared(tmp_path: Path) -> None:
    """`every_session` no dice de qué trata la neurona: no bloquea el aprendizaje."""
    path = _db(
        tmp_path,
        [("Visual", VISUAL["mission"], VISUAL["domain"], '["every_session"]')],
    )
    proposals = NeuronTriggerLearner(path).plan()
    assert len(proposals) == 1
    assert "every_session" in proposals[0]["existing_triggers"]
    assert "imagen" in proposals[0]["learned_triggers"]


def test_applying_twice_is_idempotent(tmp_path: Path) -> None:
    path = _db(tmp_path, [("Codigo", CODIGO["mission"], CODIGO["domain"], "[]")])
    learner = NeuronTriggerLearner(path)
    first = learner.apply()
    second = learner.apply()
    assert first["updated"] == 1
    assert second["updated"] == 0


def test_the_proposal_carries_its_justification(tmp_path: Path) -> None:
    """Sin justificación, un trigger aprendido es indistinguible de uno inventado."""
    path = _db(tmp_path, [("Codigo", CODIGO["mission"], CODIGO["domain"], "[]")])
    proposal = NeuronTriggerLearner(path).plan()[0]
    assert proposal["source"] == "charter"
    assert "sandbox" in proposal["justification"]


def test_el_arranque_invoca_al_aprendiz() -> None:
    """Un componente probado y sin llamador no arregla nada.

    Este módulo existía desde el 2026-07-31 con catorce pruebas —incluidas las
    de las dos neuronas concretas del caso— y **nadie lo importaba**. Las dos
    seguían con cero activaciones un mes después. Las pruebas de comportamiento
    de arriba no podían detectarlo: pasaban todas con el arreglo desconectado.

    Por eso esta prueba mira el cableado y no la conducta. Es deliberadamente
    estructural: si alguien quita la llamada del arranque, las otras catorce
    seguirán en verde y sólo caerá ésta.
    """
    import ast
    from pathlib import Path

    arranque = Path(__file__).resolve().parents[1] / "apps" / "single_port_app.py"
    arbol = ast.parse(arranque.read_text(encoding="utf-8"))

    importado = any(
        isinstance(n, ast.ImportFrom)
        and n.module == "triade.core.neuron_trigger_learning"
        and any(a.name == "NeuronTriggerLearner" for a in n.names)
        for n in ast.walk(arbol)
    )
    assert importado, "el arranque ya no importa NeuronTriggerLearner"

    # Importarlo no basta: hay que llamarlo. Se busca `NeuronTriggerLearner(...)`
    # seguido de `.apply(...)`, que es la forma que escribe de verdad.
    aplicado = any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "apply"
        and isinstance(n.func.value, ast.Call)
        and isinstance(n.func.value.func, ast.Name)
        and n.func.value.func.id == "NeuronTriggerLearner"
        for n in ast.walk(arbol)
    )
    assert aplicado, "el arranque importa el aprendiz pero no llama a apply()"
