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
