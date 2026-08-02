"""El grupo de control no puede tener la respuesta por otra puerta.

Auditoría 2026-08-02. Encontrado con el aprendizaje gobernado ya encendido en
producción, siguiendo un run real de punta a punta.

Un mismo run genera hoy **dos** filas en `learning_queue`:

* la ruta gobernada extrae la proposición atómica
  («Para los informes de auditoría usa siempre la etiqueta AUDITORIA-OMEGA…»);
* la ruta antigua vuelca la transcripción entera, que **contiene esa misma
  frase literal**, con el dato incluido.

`_build_prompt` excluía del control únicamente el candidato bajo medición. El
volcado hermano seguía siendo recuperable, así que el brazo de control recibía
la respuesta y acertaba 5 de 5. Medido en producción:

    control_mean = 1.0    treatment_mean = 1.0    delta = 0.0 -> "neutral"

Un control que ya sabe la respuesta no mide nada. Eso explica que 349
generaciones de evidencia no hayan producido ni un saber nuevo: no es que los
candidatos fueran malos, es que el experimento estaba invalidado de origen.

La regla que se fija aquí: **un experimento sobre un run no puede usar como
control nada derivado de ese mismo run.**
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.learning.evidence_producer import LearningEvidenceProducer

RUN = "run-20260802-aislamiento"
ATOMICO = "exp-atomico"
VOLCADO = "learn-volcado"
DATO = "AUDITORIA-OMEGA"

PREGUNTA = (
    "Según la preferencia registrada, ¿qué va en el hueco de: «Para los "
    "informes de auditoria usa siempre la etiqueta ___ al principio»? "
    "Responde solo con el valor exacto."
)


def _db(tmp_path: Path) -> Path:
    db = tmp_path / "triade.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """CREATE TABLE learning_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id TEXT UNIQUE,
                source_type TEXT, source_ref TEXT, title TEXT, content TEXT,
                normalized_summary TEXT, domain TEXT, risk_level TEXT,
                confidence REAL, utility REAL, status TEXT,
                verification_notes TEXT, created_at TEXT, updated_at TEXT,
                run_use_count INTEGER DEFAULT 0, run_outcome_scores TEXT,
                avg_outcome_score REAL DEFAULT 0)"""
        )
        conn.executemany(
            "INSERT INTO learning_queue (candidate_id,source_type,source_ref,title,"
            "content,normalized_summary,domain,risk_level,confidence,status,"
            "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    ATOMICO,
                    "experience",
                    f"run:{RUN}",
                    "preference",
                    f"Para los informes de auditoria usa siempre la etiqueta {DATO} al principio.",
                    "para los informes de auditoria usa siempre la etiqueta auditoria omega al principio",
                    "conversation",
                    "none",
                    1.0,
                    "evidence_verified",
                    "2026-08-02T04:00:00+00:00",
                    "2026-08-02T04:00:00+00:00",
                ),
                (
                    # El volcado de la ruta antigua: mismo run, y trae el dato.
                    VOLCADO,
                    "conversation",
                    f"run:{RUN}",
                    "Post-run learning",
                    (
                        f"run_id: {RUN}\nsource: ui\nintent: analyze\n"
                        f"input: Para los informes de auditoria usa siempre la "
                        f"etiqueta {DATO} al principio.\n"
                        "response: Recibido.\nverification_status: ok"
                    ),
                    (
                        f"run id {RUN} source ui intent analyze input para los "
                        "informes de auditoria usa siempre la etiqueta auditoria "
                        "omega al principio"
                    ),
                    "conversation",
                    "low",
                    0.65,
                    "evidence_verified",
                    "2026-08-02T04:00:00+00:00",
                    "2026-08-02T04:00:00+00:00",
                ),
            ],
        )
        conn.commit()
    return db


class TestControlAislado:
    def test_el_control_no_recibe_el_volcado_del_mismo_run(
        self, tmp_path: Path
    ) -> None:
        """El hermano del mismo run trae la respuesta: no puede entrar."""
        producer = LearningEvidenceProducer(
            _db(tmp_path), generate=lambda _p: "", temperature=0.0, seed=7731
        )

        _prompt, decision = producer._build_prompt(
            PREGUNTA, ATOMICO, "control", "run-control"
        )

        assert VOLCADO not in decision.injected_ids, (
            "el brazo de control recibió el volcado del mismo run, que contiene "
            "la respuesta literal: el experimento no mide nada"
        )
        assert ATOMICO not in decision.injected_ids

    def test_el_prompt_de_control_no_contiene_la_respuesta(
        self, tmp_path: Path
    ) -> None:
        """La comprobación que de verdad importa: el texto que ve el modelo."""
        producer = LearningEvidenceProducer(
            _db(tmp_path), generate=lambda _p: "", temperature=0.0, seed=7731
        )

        prompt, _ = producer._build_prompt(PREGUNTA, ATOMICO, "control", "run-control")

        cuerpo = prompt.replace(PREGUNTA, "")
        assert DATO.lower() not in cuerpo.lower(), (
            f"el prompt de control contiene la respuesta:\n{prompt}"
        )

    def test_el_tratamiento_si_recibe_el_candidato(self, tmp_path: Path) -> None:
        """Aislar el control no puede dejar al tratamiento sin su saber."""
        producer = LearningEvidenceProducer(
            _db(tmp_path), generate=lambda _p: "", temperature=0.0, seed=7731
        )

        _prompt, decision = producer._build_prompt(
            PREGUNTA, ATOMICO, "treatment", "run-trat"
        )

        assert ATOMICO in decision.injected_ids
        assert VOLCADO not in decision.injected_ids


class TestMedicionValida:
    def test_un_control_que_no_sabe_produce_delta_medible(self, tmp_path: Path) -> None:
        """Con el control aislado, saber el dato marca la diferencia.

        El generador simulado responde con lo que le hayan puesto en el bloque
        de contexto: es exactamente el comportamiento que el experimento quiere
        detectar.
        """
        db = _db(tmp_path)

        def generate(prompt: str) -> str:
            return DATO if DATO in prompt else "no lo se"

        producer = LearningEvidenceProducer(
            db, generate=generate, temperature=0.0, seed=7731
        )
        resultado = producer.produce(
            candidate_id=ATOMICO,
            question=PREGUNTA,
            evaluator=lambda r: DATO.lower() in r.lower(),
            repetitions=5,
        )

        assert resultado.control_mean == 0.0, (
            f"el control acertó sin tener el dato: {resultado.control_mean}"
        )
        assert resultado.treatment_mean == 1.0
        assert resultado.absolute_delta == 1.0
        assert resultado.decision == "improved"
