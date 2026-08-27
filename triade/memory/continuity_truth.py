"""Verdad operativa sobre identidad y memoria longitudinal."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from triade.db import sqlite3

#: Vocabulario del tema «memoria». Necesario, pero **no suficiente**: nombrar la
#: memoria no es preguntar por ella.
MEMORY_QUESTION = re.compile(
    r"\b(recuerd|memoria|sesiones?|contexto anterior|olvid|persist|fuera de (?:la|cada) sesi[oó]n)\w*\b",
    re.IGNORECASE,
)

#: Lo que sí es preguntar por la **continuidad** de la memoria.
#:
#: Medido sobre dos inputs reales que quedaron secuestrados:
#:
#:   «¿Existe una capacidad que justifique entrenar un LoRA en vez de resolverla
#:    con memoria, herramientas o prompting?»
#:   «Si recibes conocimiento federado de otro nodo y entra en conflicto con tu
#:    memoria, ¿qué ruta sigue?»
#:
#: Ninguna pregunta por la persistencia. Las dos contenían «memoria», y con eso
#: bastaba para que la respuesta entera —correcta— se sustituyera por el texto
#: enlatado de continuidad. Una es una pregunta de política de entrenamiento y
#: la otra de resolución de conflictos federados.
#:
#: El patrón exige que la memoria sea el **sujeto** de la pregunta: que se
#: pregunte si persiste, si se borra, si se olvida, si sobrevive al cierre.
CONTINUITY_QUESTION = re.compile(
    r"(?:"
    r"\b(?:conservas?|conserva|guardas?|mantienes?|tienes|hay)\b[^.?!]{0,40}"
    r"\b(?:memoria|recuerdos?)\b"
    r"|\b(?:memoria|recuerdos?)\b[^.?!]{0,40}"
    # `continu\w*` cubre «real y continua», «continuidad», «continuo». Faltaba, y
    # `test_single_port_chat_answers_semantic_memory_state_with_qualia` lo cazó:
    # «¿Tu memoria semántica es real y continua?» pregunta por la continuidad
    # con todas las letras y se quedaba sin enforcement. No entra en conflicto
    # con los casos que había que dejar pasar —ni la pregunta de LoRA ni la de
    # federación dicen «continua»—, porque exige además nombrar la memoria cerca.
    r"\b(?:persist\w*|continu\w*|se borra|se pierde|desaparec\w*|sobreviv\w*"
    r"|entre sesiones)\b"
    r"|\b(?:recuerdas?|olvidas?|te acuerdas)\b"
    r"|\bentre sesiones\b|\bfuera de (?:la|cada) sesi[oó]n\b"
    r"|\bal (?:cerrar|reiniciar)\b[^.?!]{0,40}\b(?:sesi[oó]n|memoria)\b"
    r"|\bmemoria (?:estable|persistente|longitudinal)\b"
    r")",
    re.IGNORECASE,
)

FALSE_EPHEMERAL_CLAIMS = (
    "todo el contenido",
    "desaparecerá",
    "desaparecera",
    "no guardo",
    "no tengo una memoria",
    "solo durante esta sesión",
    "solo durante esta sesion",
    "una vez que la sesión concluye",
    "una vez que la sesion concluye",
    "memoria está vacía",
    "memoria esta vacia",
)


def memory_truth_snapshot(db_path: str | Path) -> dict[str, Any]:
    path = Path(db_path)
    counts = {
        "runs": 0,
        "episodic_memory": 0,
        "semantic_documents": 0,
        "learning_queue": 0,
    }
    if path.is_file():
        with sqlite3.connect(path) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            for table in counts:
                if table in tables:
                    counts[table] = int(
                        conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    )
    return {
        "persistent": path.is_file(),
        "db_path": str(path),
        "counts": counts,
        "identity_continuous": True,
        "session_boundary_does_not_delete_memory": True,
        "recall_is_selective_not_total": True,
        "truth": (
            "Tríade conserva identidad, runs, episodios, documentos semánticos y candidatos en SQLite entre sesiones y reinicios. "
            "Recordar es selectivo: persistir no garantiza recuperar cada detalle en cada respuesta."
        ),
    }


def enforce_memory_truth(
    user_input: str, response: str, snapshot: dict[str, Any]
) -> tuple[str, list[str]]:
    lowered = response.lower()
    # Nombrar la memoria (`MEMORY_QUESTION`) no basta: hace falta que la
    # pregunta sea **sobre** su continuidad. Ver el comentario de
    # `CONTINUITY_QUESTION`.
    asks_continuity = bool(
        MEMORY_QUESTION.search(user_input) and CONTINUITY_QUESTION.search(user_input)
    )
    contradicts = any(claim in lowered for claim in FALSE_EPHEMERAL_CLAIMS)
    states_continuity = any(
        claim in lowered
        for claim in (
            "memoria persistente",
            "persiste entre sesiones",
            "persisten entre sesiones",
            "fuera de cada sesión",
        )
    )
    if not snapshot.get("persistent"):
        return response, []

    counts = snapshot.get("counts", {})
    # El hecho va **delante**, no detrás: a una pregunta directa se le responde
    # primero. Lo que cambia respecto al comportamiento anterior no es el orden
    # sino que la respuesta original se conserva en vez de tirarse.
    hechos = (
        "Sí: conservo memoria persistente fuera de cada sesión. La Bodega guarda "
        f"runs ({counts.get('runs', 0)}), episodios ({counts.get('episodic_memory', 0)}), "
        f"documentos semánticos ({counts.get('semantic_documents', 0)}) y aprendizajes "
        f"candidatos ({counts.get('learning_queue', 0)}) en SQLite. "
        "Recordar es selectivo: persistir no garantiza recuperar cada detalle."
    )

    # Caso 1: la respuesta afirma algo falso. Se corrige **el fragmento**, no la
    # respuesta entera: el resto puede ser correcto y perderlo era destruir
    # trabajo bueno para arreglar una frase mala.
    if contradicts:
        corregida, tocados = _redact_false_claims(response)
        if not corregida.strip():
            # No quedaba nada más que la afirmación falsa: entonces sí procede
            # sustituir, porque no hay respuesta que preservar.
            return hechos, ["false_ephemeral_memory_claim_replaced"]
        return (
            f"{hechos}\n\n{corregida.lstrip()}",
            ["false_ephemeral_memory_claim_corrected", *tocados],
        )

    # Caso 2: se pregunta de verdad por la continuidad y la respuesta no la
    # afirma. Se **añade** el hecho; no se tira lo que ya dijo.
    #
    # `asks_continuity` es lo que antes era `asks_memory`: entonces bastaba con
    # que el input nombrara la memoria, y eso secuestraba preguntas de LoRA y de
    # federación que sólo la mencionaban de pasada.
    if asks_continuity and not states_continuity:
        if not response.strip():
            return hechos, ["memory_continuity_answer_enforced"]
        return (
            f"{hechos}\n\n{response.lstrip()}",
            ["memory_continuity_fact_prepended"],
        )

    return response, []


def _redact_false_claims(response: str) -> tuple[str, list[str]]:
    """Quita las frases que afirman falsamente que la memoria es efímera.

    Se trabaja por frases, no por documento: una respuesta larga y correcta
    puede llevar una sola frase mala, y sustituirla entera sería tirar el resto.
    """
    frases = re.split(r"(?<=[.!?])\s+", response)
    conservadas: list[str] = []
    tocados: list[str] = []
    for frase in frases:
        bajada = frase.lower()
        culpable = next((c for c in FALSE_EPHEMERAL_CLAIMS if c in bajada), None)
        if culpable is None:
            conservadas.append(frase)
        else:
            tocados.append(f"removed:{culpable}")
    return " ".join(conservadas).strip(), tocados
