"""El detector de deuda de alias tiene que encontrar los cortes ya conocidos.

Todos los fallos de la auditoría del 2026-08-03 tenían la misma forma: un lector
apuntando al hermano muerto de la cosa que sí se escribe. Cada uno costó una
auditoría manual. La prueba de que el detector sirve no es que produzca una
lista, es que produzca **estos** casos sin que nadie los busque.
"""

from __future__ import annotations

from triade.observability.alias_debt import (
    HINT_THRESHOLD,
    SIMILARITY_THRESHOLD,
    find_dead_status_values,
    find_lexical_aliases,
    find_orphan_readers,
    piece_weights,
    similarity,
)

#: La forma real de la base viva, recortada a lo que decide cada señal.
PERFILES_REALES = {
    # El caso que destapó todo: salience.py leía `goals`, la ingesta iba a
    # `planning_graph`. No se parecen en el nombre en absoluto.
    "goals": {"readers": 1, "writers": 1, "rows": 0},
    "planning_graph": {"readers": 1, "writers": 1, "rows": 28},
    # El bug histórico: 10 lectores y 3 escritores sobre una tabla con 0 filas.
    "semantic_memory": {"readers": 10, "writers": 3, "rows": 0},
    "semantic_documents": {"readers": 6, "writers": 3, "rows": 186},
    # Las dos colas: ninguna está muerta, así que no es deuda de alias léxico.
    "worker_tasks": {"readers": 7, "writers": 11, "rows": 4777},
    "autonomous_tasks": {"readers": 25, "writers": 25, "rows": 8326},
}


def _por_nombre(hallazgos: list) -> dict[str, object]:
    return {h.dead: h for h in hallazgos}


def test_encuentra_el_lector_de_goals() -> None:
    """`goals` no se parece a `planning_graph`: sólo la forma lo delata."""
    hallazgos = _por_nombre(find_orphan_readers(PERFILES_REALES))

    assert "goals" in hallazgos
    assert hallazgos["goals"].evidence["rows"] == 0
    assert hallazgos["goals"].evidence["readers"] == 1


def test_una_tabla_con_escritores_y_cero_filas_es_peor_no_mejor() -> None:
    """El escritor existe y no corre: el circuito aparenta estar completo."""
    hallazgos = _por_nombre(find_orphan_readers(PERFILES_REALES))

    caso = hallazgos["semantic_memory"]
    assert caso.evidence["writers"] == 3
    assert "no se ejecuta nunca" in caso.detail
    # Y además señala con quién se confunde, que es lo accionable.
    assert caso.live == "semantic_documents"


def test_no_acusa_a_las_tablas_vivas() -> None:
    """Dos colas con filas no son deuda de alias, aunque se parezcan."""
    muertas = {h.dead for h in find_orphan_readers(PERFILES_REALES)}

    assert "planning_graph" not in muertas
    assert "semantic_documents" not in muertas
    assert "worker_tasks" not in muertas
    assert "autonomous_tasks" not in muertas


def test_un_prefijo_compartido_no_es_parecido() -> None:
    """`neuron_certifications` casaba con las ocho tablas `neuron_*`.

    Compartir el espacio de nombres daba 50 % automático en cualquier nombre de
    dos piezas, y un hallazgo se convertía en ocho líneas de lo mismo.
    """
    familia = [
        "neuron_certifications",
        "neuron_activity",
        "neuron_scores",
        "neuron_training",
        "neuron_missions",
        "neuron_evidence",
        "neuron_curricula",
        "neuron_competencies",
    ]
    pesos = piece_weights(familia)

    sin_pesos = similarity("neuron_certifications", "neuron_activity")
    con_pesos = similarity("neuron_certifications", "neuron_activity", pesos)

    assert sin_pesos >= SIMILARITY_THRESHOLD
    assert con_pesos < SIMILARITY_THRESHOLD


def test_cada_tabla_muerta_se_reporta_una_sola_vez() -> None:
    """Un informe que repite el mismo hallazgo ahoga al que lo lee."""
    perfiles = {
        "metabolic_config": {"readers": 1, "writers": 0, "rows": 0},
        "metabolic_cycle": {"readers": 1, "writers": 1, "rows": 5},
        "metabolic_needs": {"readers": 1, "writers": 1, "rows": 7},
        "metabolic_signals": {"readers": 1, "writers": 1, "rows": 9},
    }
    muertas = [h.dead for h in find_lexical_aliases(perfiles)]

    assert muertas.count("metabolic_config") <= 1


def test_un_estado_que_nadie_escribe_es_una_condicion_muerta(tmp_path) -> None:
    """La forma exacta del corte terminal del aprendizaje.

    `_plan_memory_consolidation()` contaba `status = 'validated_in_runs'` y el
    pipeline hacía tiempo que terminaba en `evidence_verified`. La consulta era
    válida, la tabla existía, la columna existía, y el resultado era cero para
    siempre.
    """
    (tmp_path / "planner.py").write_text(
        "SQL = \"SELECT COUNT(*) FROM learning_queue WHERE status = 'validated_in_runs'\"\n",
        encoding="utf-8",
    )
    (tmp_path / "producer.py").write_text(
        "UPDATE = \"UPDATE learning_queue SET status = 'evidence_verified'\"\n",
        encoding="utf-8",
    )

    hallazgos = _por_nombre(find_dead_status_values(tmp_path))

    assert "validated_in_runs" in hallazgos
    assert "evidence_verified" not in hallazgos


def test_un_estado_escrito_y_consultado_no_se_acusa(tmp_path) -> None:
    (tmp_path / "modulo.py").write_text(
        "LEE = \"SELECT * FROM t WHERE status = 'activo'\"\n"
        "ESCRIBE = \"UPDATE t SET status = 'activo'\"\n",
        encoding="utf-8",
    )

    assert find_dead_status_values(tmp_path) == []


def test_el_liston_de_pista_es_mas_bajo_que_el_de_acusacion() -> None:
    """La pista acompaña a un hallazgo que ya se sostiene por su forma."""
    assert HINT_THRESHOLD < SIMILARITY_THRESHOLD
    assert similarity("semantic_memory", "semantic_documents") >= HINT_THRESHOLD


def test_un_estado_devuelto_por_return_cuenta_como_escrito(tmp_path) -> None:
    """`return "candidate_reviewable"` escribe: quien llama guarda lo devuelto.

    Sin esto el detector acusaba a `candidate_reviewable`, que
    `neuron_formation_pipeline.py` produce en dos returns. Los falsos positivos
    son lo único que puede matar a este detector: un informe en el que hay que
    descartar a mano deja de leerse.
    """
    (tmp_path / "lector.py").write_text(
        "SQL = \"SELECT * FROM neurons WHERE status = 'candidate_reviewable'\"\n",
        encoding="utf-8",
    )
    (tmp_path / "productor.py").write_text(
        'def clasificar():\n    return "candidate_reviewable"\n', encoding="utf-8"
    )

    assert find_dead_status_values(tmp_path) == []


# ── formas de escritura que el detector debe reconocer ────────────────
# Las cuatro salieron del triaje del 2026-08-03: eran los únicos
# `dead_status_value` clasificados como corte confirmado, y ninguno lo era.


def test_un_default_de_columna_produce_el_estado(tmp_path) -> None:
    """`DEFAULT 'detected'`: la fila nace con ese estado sin que nadie lo asigne."""
    (tmp_path / "esquema.py").write_text(
        "DDL = \"CREATE TABLE t (status TEXT NOT NULL DEFAULT 'detected')\"\n"
        "LEE = \"SELECT * FROM t WHERE status = 'detected'\"\n",
        encoding="utf-8",
    )
    assert find_dead_status_values(tmp_path) == []


def test_un_literal_de_diccionario_produce_el_estado(tmp_path) -> None:
    """`{"status": "starting"}`, incluido dentro de `update(...)`."""
    (tmp_path / "modulo.py").write_text(
        'ESTADO = {}\nESTADO.update({"status": "starting"})\n'
        "LEE = \"SELECT * FROM t WHERE status = 'starting'\"\n",
        encoding="utf-8",
    )
    assert find_dead_status_values(tmp_path) == []


def test_una_asignacion_de_clave_produce_el_estado(tmp_path) -> None:
    """`_STATE["status"] = "starting"`."""
    (tmp_path / "modulo.py").write_text(
        '_STATE = {}\n_STATE["status"] = "arrancando"\n'
        "LEE = \"SELECT * FROM t WHERE status = 'arrancando'\"\n",
        encoding="utf-8",
    )
    assert find_dead_status_values(tmp_path) == []


def test_un_desempaquetado_de_tupla_produce_el_estado(tmp_path) -> None:
    """`state, error = "runtime_recovered", None`."""
    (tmp_path / "modulo.py").write_text(
        'state, error = "runtime_recovered", None\n'
        "LEE = \"SELECT * FROM t WHERE state = 'runtime_recovered'\"\n",
        encoding="utf-8",
    )
    assert find_dead_status_values(tmp_path) == []


def test_sql_parametrizado_rebaja_la_acusacion_a_sospecha(tmp_path) -> None:
    """`SET status = ?` no dice qué valor manda: no se puede acusar en absoluto.

    Tampoco se descarta el hallazgo — puede seguir siendo un corte —, pero baja
    de `dead_status_value` a `suspected_dead_status` y de `confirmed` a
    `suspected`, que es lo que la evidencia sostiene.
    """
    (tmp_path / "modulo.py").write_text(
        'ESCRIBE = "UPDATE t SET status = ?"\n'
        "LEE = \"SELECT * FROM t WHERE status = 'quizas_vivo'\"\n",
        encoding="utf-8",
    )
    hallazgos = find_dead_status_values(tmp_path)

    assert [h.signal for h in hallazgos] == ["suspected_dead_status"]
    assert hallazgos[0].confidence == "suspected"
    assert hallazgos[0].evidence["parameterised_writers"] == ["modulo.py"]


def test_sin_escritura_parametrizada_la_acusacion_es_firme(tmp_path) -> None:
    """La rebaja es por evidencia opaca, no un descuento general."""
    (tmp_path / "modulo.py").write_text(
        "LEE = \"SELECT * FROM t WHERE status = 'nadie_lo_escribe'\"\n",
        encoding="utf-8",
    )
    hallazgos = find_dead_status_values(tmp_path)

    assert [h.signal for h in hallazgos] == ["dead_status_value"]
    assert hallazgos[0].confidence == "confirmed"
