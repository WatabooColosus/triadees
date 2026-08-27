"""Batería adversarial: qué NO debe llegar nunca a memoria estable.

Un aprendizaje malo consolidado no se nota: pasa a ser el suelo sobre el que se
responde todo lo demás sobre ese sujeto. Estos tests atacan el gate por las vías
que la auditoría del 2026-08-10 identificó como plausibles —afirmación del
propio modelo sin fuente, contradicción con lo ya consolidado, duplicado,
evidencia insuficiente y candidato obsoleto— y comprueban que cada una se
detiene en un gate real, no por casualidad.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tests.test_learning_pipeline import attach_improved_evidence, pipeline
from triade.learning.contradiction import find_contradiction, subject_of
from triade.learning.knowledge_probe import is_unverified_transcript
from triade.learning.pipeline import LearningPipeline
from triade.learning.retrieval import LearningRetriever


def _consolidable(pipe: LearningPipeline, content: str, **kwargs) -> str:
    """Un candidato que ya pasó todo salvo el gate que cada test ataca."""
    cid = pipe.ingest(
        content=content,
        source_type=kwargs.pop("source_type", "document"),
        source_ref=kwargs.pop("source_ref", "fuente-verificable"),
        domain=kwargs.pop("domain", "conversation"),
        risk_level=kwargs.pop("risk_level", "low"),
        **kwargs,
    )["candidate_id"]
    pipe.evaluate(cid)
    pipe.verify(cid)
    attach_improved_evidence(pipe, cid)
    for i in range(5):
        pipe.mark_used_in_run(cid, f"run-{cid}-{i}", outcome_score=0.9)
    return cid


# ── El modelo afirmando algo por su cuenta ────────────────────────────────────


def test_model_transcript_without_user_typing_is_not_a_source() -> None:
    """Que el modelo repita su propia respuesta demuestra memoria, no verdad."""
    transcripcion = (
        "run_id: run-20260810-000000-aaaaaaaa\nsource: react-ui\n"
        "input: ¿cuál es el umbral?\nresponse: el umbral es UMBRAL-9000."
    )
    assert is_unverified_transcript(transcripcion, "{}") is True
    assert is_unverified_transcript(transcripcion, '{"type": "preference"}') is False, (
        "una preferencia tipada sí viene del usuario: su verdad es la instrucción"
    )


def test_unverified_transcript_never_reaches_the_context(tmp_path: Path) -> None:
    pipe = pipeline(tmp_path)
    cid = pipe.ingest(
        content=(
            "run_id: run-20260810-000000-bbbbbbbb\nsource: react-ui\n"
            "input: ¿cómo se llama el proceso?\nresponse: se llama PROCESO-ZAFIRO."
        ),
        source_type="conversation",
        source_ref="run:run-20260810-000000-bbbbbbbb",
        domain="conversation",
    )["candidate_id"]
    pipe.evaluate(cid)
    pipe.verify(cid)

    decision = LearningRetriever(db_path=tmp_path / "triade.db").retrieve_decision(
        "¿cómo se llama el proceso?", run_id="run-adversarial"
    )

    assert cid not in decision.injected_ids
    assert {
        item["reason"] for item in decision.skipped if item["candidate_id"] == cid
    } == {"unverified_model_transcript"}


# ── Contradicción con lo ya consolidado ───────────────────────────────────────


def test_subject_ignores_the_asserted_datum() -> None:
    """Dos afirmaciones rivales sobre lo mismo comparten sujeto."""
    primero, _ = subject_of(
        "el identificador de mi entorno de pruebas es ENTORNO_LIMA_4462"
    )
    segundo, _ = subject_of(
        "el identificador de mi entorno de pruebas es ENTORNO_LIMA_9999"
    )
    assert primero == segundo


def test_contradicting_stable_memory_is_blocked(tmp_path: Path) -> None:
    pipe = pipeline(tmp_path)
    primero = _consolidable(
        pipe, "El identificador de mi entorno de pruebas es ENTORNO_LIMA_4462."
    )
    assert pipe.consolidate(primero, approved_by="operador")["status"] == "consolidated"

    rival = _consolidable(
        pipe, "El identificador de mi entorno de pruebas es ENTORNO_LIMA_9999."
    )
    with pytest.raises(ValueError, match="Contradice memoria estable"):
        pipe.consolidate(rival, approved_by="operador")

    assert pipe.get_candidate(rival)["status"] != "consolidated"


def test_agreeing_with_stable_memory_is_not_a_contradiction(tmp_path: Path) -> None:
    """Repetir lo mismo no es contradecirlo: el gate no puede ser un cerrojo."""
    pipe = pipeline(tmp_path)
    primero = _consolidable(
        pipe, "El identificador de mi entorno de pruebas es ENTORNO_LIMA_4462."
    )
    pipe.consolidate(primero, approved_by="operador")

    assert (
        find_contradiction(
            tmp_path / "triade.db",
            "El identificador de mi entorno de pruebas es ENTORNO_LIMA_4462.",
        )
        is None
    )


def test_a_different_subject_is_never_a_contradiction(tmp_path: Path) -> None:
    pipe = pipeline(tmp_path)
    primero = _consolidable(
        pipe, "El identificador de mi entorno de pruebas es ENTORNO_LIMA_4462."
    )
    pipe.consolidate(primero, approved_by="operador")

    otro = _consolidable(
        pipe, "El nombre en clave de mi informe trimestral es INFORME_CETRO_9051."
    )
    assert pipe.consolidate(otro, approved_by="operador")["status"] == "consolidated"


def test_only_stable_memory_can_contradict(tmp_path: Path) -> None:
    """Un `candidate` todavía no es memoria: contradecirlo no significa nada."""
    pipe = pipeline(tmp_path)
    pipe.ingest(
        content="El identificador de mi entorno de pruebas es ENTORNO_LIMA_0000.",
        source_type="document",
        source_ref="sin-consolidar",
        domain="conversation",
    )
    assert (
        find_contradiction(
            tmp_path / "triade.db",
            "El identificador de mi entorno de pruebas es ENTORNO_LIMA_4462.",
        )
        is None
    )


# ── Duplicado ─────────────────────────────────────────────────────────────────


def test_the_same_fact_twice_is_one_candidate_not_two(tmp_path: Path) -> None:
    """El mismo hecho dos veces es un hecho: dos pesarían el doble al recuperar.

    El gate está más arriba de lo que parece: `ingest` funde por contenido, así
    que la copia no llega a nacer como candidato aparte y no puede competir por
    evidencia ni por consolidación por su cuenta.
    """
    pipe = pipeline(tmp_path)
    contenido = "La ventana de mantenimiento acordada es VENTANA_JUEVES_0300."
    primero = _consolidable(pipe, contenido)

    copia = pipe.ingest(
        content=contenido,
        source_type="document",
        source_ref="otra-fuente",
        domain="conversation",
    )["candidate_id"]

    assert copia == primero, "el mismo contenido no puede producir dos candidatos"

    doc = pipe.consolidate(primero, approved_by="operador")["semantic_document_id"]
    estables = [
        d
        for d in pipe.semantic_store.list_documents()
        if d["status"] == "stable" and d["content"] == contenido
    ]
    assert len(estables) == 1
    assert estables[0]["document_id"] == doc


# ── Evidencia insuficiente ────────────────────────────────────────────────────


def test_without_measurement_core_evidence_there_is_no_promotion(
    tmp_path: Path,
) -> None:
    """Sin medición no se puede ni acumular uso causal, no ya consolidar.

    El gate salta un escalón antes de lo esperado: `mark_used_in_run` llama a
    `require_improvement()` en cuanto los usos y el score alcanzarían el umbral,
    así que un candidato sin evidencia no llega nunca a `validated_in_runs`.
    """
    pipe = pipeline(tmp_path)
    cid = pipe.ingest(
        content="El nombre en clave del informe es INFORME-SIN-MEDIR.",
        source_type="document",
        source_ref="fuente-verificable",
        domain="conversation",
    )["candidate_id"]
    pipe.evaluate(cid)
    pipe.verify(cid)

    with pytest.raises(ValueError, match="Measurement Core"):
        for i in range(5):
            pipe.mark_used_in_run(cid, f"run-sin-evidencia-{i}", outcome_score=1.0)

    assert pipe.get_candidate(cid)["status"] == "internally_checked"
    with pytest.raises(ValueError, match="Measurement Core"):
        pipe.consolidate(cid, approved_by="operador")


def test_too_few_causal_uses_is_blocked(tmp_path: Path) -> None:
    pipe = pipeline(tmp_path)
    cid = pipe.ingest(
        content="El identificador del turno es TURNO-POCOS-USOS.",
        source_type="document",
        source_ref="fuente-verificable",
        domain="conversation",
    )["candidate_id"]
    pipe.evaluate(cid)
    pipe.verify(cid)
    attach_improved_evidence(pipe, cid)
    pipe.mark_used_in_run(cid, "run-unico", outcome_score=1.0)

    with pytest.raises(ValueError, match="evidencia suficiente"):
        pipe.consolidate(cid, approved_by="operador")


def test_a_bad_average_score_is_blocked(tmp_path: Path) -> None:
    pipe = pipeline(tmp_path)
    cid = pipe.ingest(
        content="El identificador del lote es LOTE-MAL-PUNTUADO.",
        source_type="document",
        source_ref="fuente-verificable",
        domain="conversation",
    )["candidate_id"]
    pipe.evaluate(cid)
    pipe.verify(cid)
    attach_improved_evidence(pipe, cid)
    for i in range(5):
        pipe.mark_used_in_run(cid, f"run-flojo-{i}", outcome_score=0.2)

    with pytest.raises(ValueError, match="score suficiente"):
        pipe.consolidate(cid, approved_by="operador")


# ── Obsoleto ──────────────────────────────────────────────────────────────────


def test_an_archived_candidate_cannot_be_revived_into_memory(tmp_path: Path) -> None:
    """Lo retirado está retirado: `archive` no puede ser una puerta trasera."""
    pipe = pipeline(tmp_path)
    cid = _consolidable(pipe, "El código del turno anterior era TURNO-OBSOLETO-1.")
    pipe.archive(cid)

    with pytest.raises(ValueError):
        pipe.consolidate(cid, approved_by="operador")


def test_a_rejected_candidate_cannot_be_consolidated(tmp_path: Path) -> None:
    pipe = pipeline(tmp_path)
    cid = _consolidable(pipe, "El código descartado era TURNO-RECHAZADO-2.")
    pipe.reject(cid, reason="El operador lo descartó con motivo verificable.")

    with pytest.raises(ValueError):
        pipe.consolidate(cid, approved_by="operador")


# ── Sustitución: cuando el usuario cambia un dato que ya estaba consolidado ────


def _documento_estable(pipe: LearningPipeline, fragmento: str) -> dict:
    """El documento semántico que contiene ese fragmento, sea cual sea su estado."""
    for doc in pipe.semantic_store.list_documents():
        if fragmento in str(doc.get("content") or ""):
            return doc
    raise AssertionError(f"no hay documento con «{fragmento}»")


def test_una_afirmacion_explicita_del_usuario_sustituye_el_hecho_viejo(
    tmp_path: Path,
) -> None:
    """Bloquear sin salida dejaba la memoria anclada al primer valor de un dato mutable.

    Los hechos que se consolidan son en su mayoría preferencias del usuario, y
    ésas cambian. Comprobado contra la base viva el 2026-08-27: al afirmar una
    ventana de mantenimiento nueva, el hecho nuevo quedaba rechazado y el viejo
    —ya falso— seguía `stable` y seguía recuperándose.
    """
    pipe = pipeline(tmp_path)
    viejo = _consolidable(
        pipe,
        "Mi ventana de mantenimiento acordada es VENTANA_JUEVES_0300.",
        source_type="experience",
    )
    pipe.consolidate(viejo, approved_by="operador")

    nuevo = _consolidable(
        pipe,
        "Mi ventana de mantenimiento acordada es VENTANA_MARTES_0500.",
        source_type="experience",
    )
    assert pipe.consolidate(nuevo, approved_by="operador")["status"] == "consolidated"

    doc_viejo = _documento_estable(pipe, "VENTANA_JUEVES_0300")
    doc_nuevo = _documento_estable(pipe, "VENTANA_MARTES_0500")

    assert doc_nuevo["status"] == "stable"
    # El viejo no se borra: queda dicho cuándo dejó de valer y quién lo sustituyó.
    assert doc_viejo["status"] == "superseded"
    assert doc_viejo["superseded_by"] == doc_nuevo["document_id"]
    assert doc_viejo["superseded_at"]
    assert doc_viejo["content"]


def test_el_hecho_sustituido_deja_de_influir(tmp_path: Path) -> None:
    """No hace falta borrarlo: `stable` es lista blanca, y `superseded` no está."""
    from triade.memory.semantic_governance import influence_allowed_statuses

    pipe = pipeline(tmp_path)
    viejo = _consolidable(
        pipe, "Mi entorno de pruebas es ENTORNO_LIMA_4462.", source_type="experience"
    )
    pipe.consolidate(viejo, approved_by="operador")
    nuevo = _consolidable(
        pipe, "Mi entorno de pruebas es ENTORNO_LIMA_9999.", source_type="experience"
    )
    pipe.consolidate(nuevo, approved_by="operador")

    assert "superseded" not in influence_allowed_statuses()
    assert "superseded" not in influence_allowed_statuses(allow_experimental=True)
    assert _documento_estable(pipe, "ENTORNO_LIMA_4462")["status"] == "superseded"


def test_el_aprendizaje_autonomo_no_puede_retirar_un_hecho(tmp_path: Path) -> None:
    """La máquina añade memoria por cualquier vía, pero no retira lo que una persona dio por bueno.

    Si un candidato de origen `tool` pudiera sustituir, una hipótesis de misión
    borraría una preferencia declarada y la memoria dejaría de ser auditable
    hacia atrás.
    """
    pipe = pipeline(tmp_path)
    humano = _consolidable(
        pipe,
        "El nombre en clave de mi informe trimestral es INFORME_CETRO_9051.",
        source_type="experience",
    )
    pipe.consolidate(humano, approved_by="operador")

    maquina = _consolidable(
        pipe,
        "El nombre en clave de mi informe trimestral es INFORME_CETRO_0000.",
        source_type="tool",
    )
    with pytest.raises(ValueError, match="Contradice memoria estable"):
        pipe.consolidate(maquina, approved_by="operador")

    assert _documento_estable(pipe, "INFORME_CETRO_9051")["status"] == "stable"


def test_la_sustitucion_es_reversible(tmp_path: Path) -> None:
    """Es olvido reversible, no borrado: devolver el estado lo deshace entero."""
    pipe = pipeline(tmp_path)
    viejo = _consolidable(
        pipe, "Mi marcador de auditoría es MARCADOR_ALFA.", source_type="experience"
    )
    pipe.consolidate(viejo, approved_by="operador")
    nuevo = _consolidable(
        pipe, "Mi marcador de auditoría es MARCADOR_BETA.", source_type="experience"
    )
    pipe.consolidate(nuevo, approved_by="operador")

    doc = _documento_estable(pipe, "MARCADOR_ALFA")
    assert doc["status"] == "superseded"

    with sqlite3.connect(tmp_path / "triade.db") as conn:
        conn.execute(
            "UPDATE semantic_documents SET status='stable' WHERE document_id=?",
            (doc["document_id"],),
        )

    assert _documento_estable(pipe, "MARCADOR_ALFA")["status"] == "stable"
