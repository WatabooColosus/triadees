"""Batería adversarial: qué NO debe llegar nunca a memoria estable.

Un aprendizaje malo consolidado no se nota: pasa a ser el suelo sobre el que se
responde todo lo demás sobre ese sujeto. Estos tests atacan el gate por las vías
que la auditoría del 2026-08-10 identificó como plausibles —afirmación del
propio modelo sin fuente, contradicción con lo ya consolidado, duplicado,
evidencia insuficiente y candidato obsoleto— y comprueban que cada una se
detiene en un gate real, no por casualidad.
"""

from __future__ import annotations

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
