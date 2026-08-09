"""El destilador convierte texto en afirmaciones contrastables.

Sin él, `GovernedResearchWorker` cae siempre en `unverifiable` y no ingiere
nada: medido en producción el 2026-08-09, **153 ejecuciones de
`research_curriculum`, cero candidatos**. El proveedor web devolvía la
transcripción cruda y `governed.py:142` exige afirmaciones.
"""

from __future__ import annotations

from typing import Any

from triade.research.claim_distiller import (
    MODEL_EXTRACTOR,
    RULE_EXTRACTOR,
    distill_claims,
    distill_model,
    distill_rules,
)

TEXTO = (
    "La trazabilidad es un registro verificable de cada decisión tomada por el "
    "sistema durante su ejecución. "
    "El control de acceso se define como el conjunto de reglas que determinan "
    "quién puede leer o escribir cada recurso. "
    "Hola. "
    "La auditoría consiste en revisar la evidencia registrada para comprobar "
    "que las reglas se cumplieron de verdad."
)


class ModeloFalso:
    """Devuelve lo que se le diga, para probar el destilador y no a Ollama."""

    def __init__(self, respuesta: str) -> None:
        self.respuesta = respuesta
        self.llamadas: list[str] = []

    def generate(
        self,
        model: str,
        prompt: str,
        system: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> Any:
        self.llamadas.append(prompt)
        return type("R", (), {"text": self.respuesta})()


class ModeloRoto:
    def generate(self, *args: Any, **kwargs: Any) -> Any:
        raise OSError("ollama caído")


# --- Reglas: determinista y sin modelo ---------------------------------------


def test_las_reglas_extraen_pares_clave_valor() -> None:
    claims = distill_rules(TEXTO, question="trazabilidad auditoría")

    claves = {c["key"] for c in claims}
    assert "trazabilidad" in claves
    assert "control de acceso" in claves
    assert "auditoría" in claves
    assert all(c["extractor"] == RULE_EXTRACTOR for c in claims)


def test_las_reglas_son_deterministas() -> None:
    assert distill_rules(TEXTO) == distill_rules(TEXTO)


def test_las_reglas_descartan_frases_que_no_definen_nada() -> None:
    claims = distill_rules(TEXTO)

    assert all(len(c["value"]) >= 25 for c in claims)
    assert "hola" not in {c["key"] for c in claims}


def test_texto_vacio_no_produce_afirmaciones() -> None:
    assert distill_claims("   ", extractor="both") == []


# --- Modelo: se verifica, no se cree -----------------------------------------


def test_el_modelo_aporta_afirmaciones_ancladas() -> None:
    modelo = ModeloFalso(
        '[{"key": "evidencia registrada", "value": "revisar la evidencia '
        'registrada permite comprobar que las reglas se cumplieron"}]'
    )

    claims = distill_model(TEXTO, client=modelo, model="qwen3:1.7b")

    assert [c["key"] for c in claims] == ["evidencia registrada"]
    assert claims[0]["extractor"] == MODEL_EXTRACTOR


def test_una_afirmacion_que_el_texto_no_sostiene_se_descarta() -> None:
    """La puerta que hace admisible un modelo dentro de la cadena de evidencia."""
    modelo = ModeloFalso(
        '[{"key": "presupuesto", "value": "el proyecto costó catorce millones '
        'de euros repartidos entre cinco proveedores externos"}]'
    )

    assert distill_model(TEXTO, client=modelo, model="qwen3:1.7b") == []


def test_respuesta_no_json_no_rompe_la_investigacion() -> None:
    assert (
        distill_model(TEXTO, client=ModeloFalso("lo siento, no puedo"), model="m") == []
    )


def test_modelo_caido_no_rompe_la_investigacion() -> None:
    assert distill_model(TEXTO, client=ModeloRoto(), model="m") == []


# --- Combinación y caída a reglas --------------------------------------------


def test_sin_cliente_el_modo_modelo_cae_a_reglas() -> None:
    """Quedarse sin investigar por no tener Ollama sería peor que la cobertura."""
    claims = distill_claims(TEXTO, extractor="model", client=None)

    assert claims
    assert all(c["extractor"] == RULE_EXTRACTOR for c in claims)


def test_both_une_los_dos_y_mandan_las_reglas() -> None:
    modelo = ModeloFalso(
        '[{"key": "trazabilidad", "value": "otra definicion distinta de la '
        'trazabilidad segun el modelo durante la ejecución"},'
        '{"key": "evidencia registrada", "value": "revisar la evidencia '
        'registrada comprueba que las reglas se cumplieron"}]'
    )

    claims = distill_claims(TEXTO, extractor="both", client=modelo, model="m")
    por_clave = {c["key"]: c for c in claims}

    # La clave que proponen los dos se queda con la versión determinista.
    assert por_clave["trazabilidad"]["extractor"] == RULE_EXTRACTOR
    # Y la que sólo ve el modelo suma cobertura.
    assert por_clave["evidencia registrada"]["extractor"] == MODEL_EXTRACTOR


def test_cada_afirmacion_declara_quien_la_produjo() -> None:
    modelo = ModeloFalso(
        '[{"key": "evidencia registrada", "value": "revisar la evidencia '
        'registrada comprueba que las reglas se cumplieron"}]'
    )

    claims = distill_claims(TEXTO, extractor="both", client=modelo, model="m")

    assert all(c["extractor"] in {RULE_EXTRACTOR, MODEL_EXTRACTOR} for c in claims)


# --- El eslabón cerrado ------------------------------------------------------


def test_la_investigacion_gobernada_pasa_de_unverifiable_a_candidato(
    tmp_path: Any,
) -> None:
    """ANTES: 153 ejecuciones, todas `unverifiable`. DESPUÉS: candidato real.

    Las dos fuentes y su contenido son los mismos en los dos casos; lo único que
    cambia es si alguien destiló afirmaciones del texto.
    """
    from triade.research.governed import GovernedResearchWorker

    fuentes = [
        {
            "url": "https://owasp.org/www-project-top-ten/",
            "title": "OWASP",
            "content": TEXTO,
        },
        {
            "url": "https://www.nist.gov/cyberframework",
            "title": "NIST",
            "content": (
                "La gobernanza es un marco de decisiones documentadas sobre "
                "quién responde de cada riesgo del sistema."
            ),
        },
    ]

    def sin_destilar(question: str, minimum: int) -> dict[str, Any]:
        return {"sources": fuentes, "failures": []}

    def con_destilador(question: str, minimum: int) -> dict[str, Any]:
        return {
            "sources": [
                {**s, "claims": distill_claims(str(s["content"]), question=question)}
                for s in fuentes
            ],
            "failures": [],
        }

    comun = {
        "question": "gobernanza trazabilidad auditoría del sistema",
        "trigger": "gap",
        "scope": "goal_research",
        "allowed_sources": ["owasp.org", "www.nist.gov"],
    }

    antes = GovernedResearchWorker(tmp_path / "antes.db", sin_destilar).run(**comun)
    despues = GovernedResearchWorker(tmp_path / "despues.db", con_destilador).run(
        **comun
    )

    assert antes["status"] == "unverifiable"
    assert antes.get("candidate_id") is None

    assert despues["status"] == "candidate_created"
    assert despues["candidate_id"]


# --- Lo que no pasó la puerta también enseña ---------------------------------


def test_el_fallo_repetido_se_reconoce_y_cambia_el_trigger(tmp_path: Any) -> None:
    """156 runs idénticos, 156 `unverifiable`, y nadie leyó ese historial.

    `repeated_failure` es un trigger que el diseño ya contemplaba y que ningún
    productor emitía: 156/156 entraban como `gap`.
    """
    from triade.research.governed import (
        REPEATED_FAILURE_THRESHOLD,
        GovernedResearchWorker,
        prior_failed_research,
    )

    db = tmp_path / "research.db"

    def sin_afirmaciones(question: str, minimum: int) -> dict[str, Any]:
        return {
            "sources": [
                {"url": "https://owasp.org/a", "title": "A", "content": TEXTO},
                {"url": "https://www.nist.gov/b", "title": "B", "content": TEXTO},
            ],
            "failures": [],
        }

    worker = GovernedResearchWorker(db, sin_afirmaciones)
    comun = {
        "question": "gobernanza trazabilidad",
        "trigger": "gap",
        "scope": "goal_research",
        "allowed_sources": ["owasp.org", "www.nist.gov"],
    }

    primeros = [worker.run(**comun) for _ in range(REPEATED_FAILURE_THRESHOLD)]
    assert all(r["status"] == "unverifiable" for r in primeros)
    assert primeros[0]["prior_failures"] == 0
    assert primeros[0]["repeated_failure"] is False

    siguiente = worker.run(**comun)

    # El proceso ya sabe que insistir así no lleva a ninguna parte.
    assert siguiente["prior_failures"] >= REPEATED_FAILURE_THRESHOLD
    assert siguiente["repeated_failure"] is True
    assert (
        prior_failed_research(db, "gobernanza trazabilidad", "goal_research")
        > REPEATED_FAILURE_THRESHOLD
    )


def test_una_pregunta_que_si_produjo_no_cuenta_como_fallo(tmp_path: Any) -> None:
    """Sólo educa el fallo; un candidato creado no es un intento fallido."""
    from triade.research.governed import GovernedResearchWorker, prior_failed_research

    db = tmp_path / "research.db"

    def con_afirmaciones(question: str, minimum: int) -> dict[str, Any]:
        return {
            "sources": [
                {
                    "url": "https://owasp.org/a",
                    "title": "A",
                    "content": TEXTO,
                    "claims": distill_claims(TEXTO, question=question),
                },
                {
                    "url": "https://www.nist.gov/b",
                    "title": "B",
                    "content": "La gobernanza es un marco de decisiones documentadas del sistema.",
                    "claims": distill_claims(
                        "La gobernanza es un marco de decisiones documentadas del sistema.",
                        question=question,
                    ),
                },
            ],
            "failures": [],
        }

    resultado = GovernedResearchWorker(db, con_afirmaciones).run(
        question="gobernanza trazabilidad",
        trigger="gap",
        scope="goal_research",
        allowed_sources=["owasp.org", "www.nist.gov"],
    )

    assert resultado["status"] == "candidate_created"
    assert prior_failed_research(db, "gobernanza trazabilidad", "goal_research") == 0


def test_both_no_duplica_la_misma_clave_con_otra_preposicion() -> None:
    """«control de acceso» y «control acceso» son el mismo concepto.

    Un modelo no siempre repite las preposiciones; sin normalizar la huella,
    `both` guardaba las dos y la evidencia salía con ruido duplicado.
    """
    modelo = ModeloFalso(
        '[{"key": "control acceso", "value": "conjunto de reglas que determinan '
        'quién puede leer o escribir cada recurso"}]'
    )

    claims = distill_claims(TEXTO, extractor="both", client=modelo, model="m")

    assert sum(1 for c in claims if "control" in c["key"]) == 1


# --- El recibo del efecto ----------------------------------------------------


def test_el_candidato_creado_emite_recibo_verificado(tmp_path: Any) -> None:
    """`candidate_created` declara un efecto, y sin recibo se rechaza.

    Nunca había saltado porque la investigación jamás creó un candidato: 156
    runs en `unverifiable`, que no declara efecto. El primero que sí lo creó
    murió con `verified_effect_receipt_missing` y el candidato ya escrito.
    """
    from triade.workers.worker_loop import WorkerLoop

    db = tmp_path / "triade.db"
    resultado = {
        "research_id": "gr-test",
        "status": "candidate_created",
        "candidate_id": "learn-inexistente",
        "sources": [{}, {}],
        "claims": [{}],
        "minimum_independent_sources": 2,
        "prior_failures": 0,
    }

    loop = WorkerLoop(db_path=db, runs_dir=tmp_path / "runs")

    # Sin fila en `learning_queue` el recibo NO se firma: la poscondición se
    # comprueba releyendo la base, no repitiendo lo que dijo el handler.
    recibo = loop._research_effect_receipt(resultado)
    assert recibo is not None
    assert recibo.verified is False
    assert recibo.postcondition["row_exists"] is False

    # Con la fila escrita de verdad, el recibo sale verificado.
    import sqlite3 as _sq

    with _sq.connect(db) as conn:
        conn.execute(
            "INSERT INTO learning_queue (candidate_id,title,content,domain,"
            "source_type,source_ref,status,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,datetime('now'),datetime('now'))",
            (
                "learn-inexistente",
                "t",
                "c",
                "d",
                "web",
                "research:x",
                "candidate",
            ),
        )

    recibo = loop._research_effect_receipt(resultado)
    assert recibo.verified is True
    assert recibo.postcondition["passed"] is True
    assert recibo.action == "create_learning_candidate"
    assert recibo.evidence_refs


def test_sin_candidato_no_se_inventa_recibo(tmp_path: Any) -> None:
    """`unverifiable` no declara efecto: firmar un recibo ahí sería mentir."""
    from triade.workers.worker_loop import WorkerLoop

    loop = WorkerLoop(db_path=tmp_path / "triade.db", runs_dir=tmp_path / "runs")

    assert (
        loop._research_effect_receipt(
            {"research_id": "gr-x", "status": "unverifiable", "candidate_id": None}
        )
        is None
    )


# --- Calidad: navegación de página no es conocimiento ------------------------

#: Las cuatro afirmaciones reales que la primera investigación produjo sobre
#: owasp.org el 2026-08-09. Tres son la página hablando de sí misma y una es la
#: única que afirma algo del tema. Todas tienen forma perfecta de definición.
TEXTO_OWASP = (
    "The OWASP Top 10 is a standard awareness document for developers and web "
    "application security. "
    "Previous versions are available at OWASP Top Ten 2021 and OWASP Top 10 2017. "
    "Older versions are available in the Github repo. "
    "If you are interested in helping, please contact the members of the team "
    "for the language you want to contribute to."
)


def test_solo_sobrevive_la_afirmacion_que_afirma_algo() -> None:
    claims = distill_rules(TEXTO_OWASP, question="owasp seguridad aplicaciones")

    claves = {c["key"] for c in claims}
    assert "owasp top 10" in claves, "la única que sí define algo debe quedarse"
    assert claves == {"owasp top 10"}, f"navegación colada: {claves - {'owasp top 10'}}"


def test_un_sujeto_que_no_nombra_nada_se_descarta() -> None:
    """«If you are interested in helping…» tiene la misma forma que una definición."""
    assert (
        distill_rules("If you are interested in helping, please contact us now.") == []
    )


def test_la_navegacion_de_pagina_se_descarta() -> None:
    for frase in (
        "Previous versions are available at OWASP Top Ten 2021 and OWASP Top 10 2017.",
        "Older versions are available in the Github repo of the project.",
        "Los manuales anteriores están disponibles en el repositorio del proyecto.",
    ):
        assert distill_rules(frase) == [], f"coló navegación: {frase!r}"


def test_el_modelo_tambien_pasa_por_el_filtro_de_calidad() -> None:
    """La higiene no depende de quién produjo la afirmación."""
    modelo = ModeloFalso(
        '[{"key": "older versions", "value": "are available in the Github repo '
        'of the OWASP project"}]'
    )

    assert distill_model(TEXTO_OWASP, client=modelo, model="m") == []
