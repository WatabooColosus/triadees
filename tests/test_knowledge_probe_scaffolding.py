"""Preguntar por vocabulario del repositorio no mide aprendizaje.

Medido sobre la base viva el 2026-08-03. Los candidatos con más uso real del
sistema —hasta 44 usos y media 0.934— extraían `mission_id` como dato
distintivo, y la pregunta resultante era:

    «…debe evaluarse con evidencia local trazable por ___ y run_ref…»

La respuesta está implícita en el propio enunciado. El brazo de control acertaba
5 de 5 sin haber aprendido nada, así que la evidencia salía
`control 1.0, tratamiento 1.0, delta 0.0 -> neutral`, siempre. No eran
candidatos malos: era una sonda inválida.

Y el `neutral` no era inocuo. Escribe fila en `learning_evidence`, el
`NOT EXISTS` del planner deja de ser cierto y el candidato queda excluido para
siempre de volver a medirse con una sonda mejor. Un instrumento roto quemaba
candidatos buenos.
"""

from __future__ import annotations

import pytest

from triade.learning.knowledge_probe import extract_target, is_unverified_transcript

#: El caso real que lo destapó, recortado del candidato `learn-47874b4587e840e5`.
CONTENIDO_REAL = (
    "Para la misión 'Misión fundacional · Impulso Pereza', mantener como "
    "hipótesis operacional que Detectar inercia o fatiga y transformarla en "
    "descanso consciente, prioridad y diligencia sostenible. debe evaluarse "
    "con evidencia local trazable por mission_id y run_ref antes de "
    "consolidar memoria estable"
)


def test_el_caso_que_lo_destapo_ya_no_es_medible() -> None:
    """44 usos, media 0.934, y la sonda sólo sabía preguntar por `mission_id`."""
    assert extract_target(CONTENIDO_REAL) is None


@pytest.mark.parametrize(
    "identificador",
    ["mission_id", "run_ref", "source_ref", "candidate_id", "task_type", "goal_id"],
)
def test_ningun_identificador_de_andamiaje_sirve_de_pregunta(
    identificador: str,
) -> None:
    """Están en todo el repositorio y en el vocabulario de cualquier modelo.

    El módulo declara que sólo vale «un dato concreto que el modelo no sabría
    por su cuenta». Éstos los sabe.
    """
    contenido = f"El paso se registra con {identificador} al cerrar el ciclo."
    assert extract_target(contenido) is None


def test_un_dato_de_verdad_distintivo_sigue_sirviendo() -> None:
    """El filtro descarta andamiaje, no aprendizaje real."""
    assert extract_target("El veredicto se marca como VEREDICTO-TRIADE.") == (
        "VEREDICTO-TRIADE"
    )


def test_una_respuesta_del_modelo_no_se_convierte_en_hecho_verificado() -> None:
    contenido = (
        "run_id: run-real\nsource: react-ui\nintent: analyze\n"
        "input: ¿Qué PRAGMA encuentra claves huérfanas?\n"
        "response: Debes usar PRAGMA foreign_keys.\nverification_status: ok"
    )

    assert is_unverified_transcript(contenido) is True
    assert (
        is_unverified_transcript(contenido, '{"type": "correction", "role": "user"}')
        is False
    )
    assert extract_target("Usa el prefijo WRK:: al reportar.") == "WRK::"
    assert (
        extract_target("Primero se ejecuta drain_queue y luego los leases.")
        == "drain_queue"
    )


def test_convive_el_andamiaje_con_un_dato_real() -> None:
    """Si hay un dato bueno, el andamiaje no puede taparlo ni robarle el sitio."""
    contenido = (
        "El run_ref se guarda, pero la marca que importa es VEREDICTO-TRIADE, "
        "con su mission_id asociado."
    )
    assert extract_target(contenido) == "VEREDICTO-TRIADE"


def test_verification_status_es_andamiaje_y_no_ahoga_lo_que_si_afirma() -> None:
    """La misma fuga que `mission_id`, por otra puerta y a mayor escala.

    Medido el 2026-08-08 sobre la base viva: 230 de 250 candidatos con
    `source_type='conversation'` extraían `verification_status`, y el **96%** de
    sus evidencias salía `neutral` — la firma de una sonda cuya respuesta está
    en el propio enunciado, idéntica a la de agosto: control 1.0, tratamiento
    1.0, delta 0.0.

    Es un nombre de campo del registro de run, no un hecho que el modelo no
    supiera. Los dos únicos `improved` de esa población salieron de targets que
    sí afirman algo del mundo, ahogados 100 a 1 por transcripciones.
    """
    from triade.learning.knowledge_probe import extract_target

    transcripcion = (
        "run_id: run-20260808-023639-e8047fff source: phase1-real-e2e "
        "verification_status: ok"
    )
    assert extract_target(transcripcion) != "verification_status"

    # Lo que sí afirma algo del mundo tiene que seguir siendo medible: el filtro
    # existe para que estos compitan, no para callar a todos.
    for afirmacion in ("recall_is_selective_not_total", "identity_continuous"):
        assert extract_target(f"Se aprendió que {afirmacion} en este run") == afirmacion


def test_una_certificacion_no_es_una_conversacion(tmp_path) -> None:
    """Los runs de prueba no deben alimentar la memoria.

    Medido el 2026-08-08: tras filtrar `verification_status`, 43 candidatos
    conversacionales extraían `TRIADA_VIVA` —la frase de las propias
    certificaciones— como dato distintivo. Medir si Tríade recuerda su frase de
    test no es aprender: es memorizar el andamiaje.
    """
    from triade.learning.post_run import schedule_learning_from_run

    comun = {
        "run_id": "run-x",
        "message": "hola",
        "response": "hola",
        "enabled": True,
    }

    prueba = schedule_learning_from_run(
        tmp_path / "t.db", source="phase1-real-e2e", **comun
    )
    real = schedule_learning_from_run(tmp_path / "t.db", source="react-ui", **comun)

    assert prueba["scheduled"] is False
    assert "source_sin_aprendizaje" in prueba["reason"]
    assert real["scheduled"] is True, "la UI real sí tiene que aprender"
