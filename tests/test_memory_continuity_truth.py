import sqlite3

from triade.memory.continuity_truth import enforce_memory_truth, memory_truth_snapshot


def test_false_ephemeral_claim_is_replaced(tmp_path):
    db = tmp_path / "triade.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE runs (id TEXT)")
        conn.execute("INSERT INTO runs VALUES ('run-1')")
        conn.execute("CREATE TABLE episodic_memory (id TEXT)")
    snapshot = memory_truth_snapshot(db)
    response, corrections = enforce_memory_truth(
        "¿Recuerdas fuera de cada sesión?",
        "No guardo nada; todo el contenido desaparecerá.",
        snapshot,
    )
    assert "conservo memoria persistente" in response
    assert "runs (1)" in response
    assert corrections == ["false_ephemeral_memory_claim_replaced"]


def test_truthful_answer_is_unchanged(tmp_path):
    db = tmp_path / "triade.db"
    db.touch()
    original = "Mi Bodega persiste entre sesiones y recupera contexto relevante."
    assert enforce_memory_truth(
        "¿Tienes memoria?", original, memory_truth_snapshot(db)
    ) == (original, [])


def test_vague_identity_answer_gets_continuity_prepended(tmp_path):
    """A una pregunta directa se le responde primero, sin tirar lo ya dicho.

    Antes esto **sustituía** la respuesta entera, y por eso el gate secuestraba
    respuestas correctas: bastaba con que el input nombrara la memoria. La
    etiqueta cambió de `memory_continuity_answer_enforced` a
    `..._fact_prepended` porque la operación es otra — el hecho se antepone y
    la respuesta original se conserva.
    """
    db = tmp_path / "triade.db"
    db.touch()
    response, corrections = enforce_memory_truth(
        "¿Recuerdas fuera de cada sesión?",
        "Soy Tríade y tengo una Bodega.",
        memory_truth_snapshot(db),
    )
    assert response.startswith("Sí: conservo memoria persistente")
    assert "Soy Tríade y tengo una Bodega." in response, "no se tira lo que ya dijo"
    assert corrections == ["memory_continuity_fact_prepended"]


# ── §18: regresiones sobre casos reales observados en la batería ────────────
#
# Los dos primeros son inputs literales que quedaron secuestrados: el gate
# reemplazó una respuesta correcta por el texto enlatado de continuidad sólo
# porque la pregunta contenía la palabra «memoria».

SNAPSHOT_VIVO = {
    "persistent": True,
    "counts": {
        "runs": 2379,
        "episodic_memory": 1258,
        "semantic_documents": 869,
        "learning_queue": 1002,
    },
    # Las publica `memory_truth_snapshot()` y faltaban aquí: una fixture que no
    # tiene la forma del dato real prueba otra cosa que la que se cree.
    "identity_continuous": True,
    "session_boundary_does_not_delete_memory": True,
    "recall_is_selective_not_total": True,
}


def test_pregunta_lora_que_menciona_memoria_no_se_secuestra():
    """§18.4 — «…en vez de resolverla con memoria, herramientas o prompting»."""
    pregunta = (
        "¿Existe actualmente alguna capacidad en la que tengas evidencia "
        "suficiente para justificar entrenar un LoRA en vez de resolverla con "
        "memoria, herramientas o prompting? Si no existe, dilo y no entrenes nada."
    )
    respuesta = (
        "No. Ninguna capacidad tiene hoy evidencia suficiente: no hay "
        "verification_reports con delta medido sobre una competencia concreta."
    )
    salida, correcciones = enforce_memory_truth(pregunta, respuesta, SNAPSHOT_VIVO)
    assert salida == respuesta
    assert correcciones == []


def test_pregunta_federada_que_menciona_memoria_no_se_secuestra():
    """§18.5 — «…entra en conflicto con tu memoria»."""
    pregunta = (
        "Si recibes conocimiento federado de otro nodo y entra en conflicto "
        "con tu memoria, ¿qué ruta real debería seguir?"
    )
    respuesta = (
        "Inbox federado, verificación de firma, contraste contra el grafo de "
        "conocimiento y resolución de la contradicción antes de aceptar nada."
    )
    salida, correcciones = enforce_memory_truth(pregunta, respuesta, SNAPSHOT_VIVO)
    assert salida == respuesta
    assert correcciones == []


def test_pregunta_explicita_de_persistencia_si_recibe_enforcement():
    """§18.6 — la puerta debe seguir cerrándose cuando toca."""
    salida, correcciones = enforce_memory_truth(
        "¿Conservas memoria entre sesiones o se borra todo al cerrar?",
        "No estoy seguro de eso.",
        SNAPSHOT_VIVO,
    )
    assert "conservo memoria persistente" in salida.lower()
    assert correcciones


def test_la_correccion_no_destruye_el_contenido_valido():
    """§18.7 — se quita la frase falsa, no el resto de la respuesta."""
    respuesta = (
        "El almacenamiento usa SQLite en modo WAL. Todo el contenido "
        "desaparecerá al cerrar. La Bodega indexa episodios y documentos."
    )
    salida, correcciones = enforce_memory_truth(
        "¿Tu memoria persiste entre sesiones?", respuesta, SNAPSHOT_VIVO
    )
    assert "SQLite en modo WAL" in salida
    assert "La Bodega indexa episodios" in salida
    assert "desaparecerá al cerrar" not in salida
    assert any("removed:" in c for c in correcciones)


def test_el_enforcement_es_idempotente():
    """Aplicarlo dos veces no debe acumular párrafos ni volver a corregir."""
    pregunta = "¿Recuerdas fuera de cada sesión?"
    primera, _ = enforce_memory_truth(pregunta, "Soy Tríade.", SNAPSHOT_VIVO)
    segunda, correcciones = enforce_memory_truth(pregunta, primera, SNAPSHOT_VIVO)
    assert segunda == primera
    assert correcciones == []


# ── Contradicción afirmada: no se le cree al modelo, se comprueba ─────────────


def test_una_contradiccion_afirmada_se_comprueba_antes_de_aceptarla():
    """El fallo medido el 2026-08-26, con la ruta que lo comprueba.

    Preguntado por «la memoria persiste entre sesiones» frente a «el recall es
    selectivo», el sistema las declaró contradictorias. No lo son, y lo
    desmiente este mismo módulo: `memory_truth_snapshot()` publica
    `session_boundary_does_not_delete_memory` y `recall_is_selective_not_total`
    como ciertas a la vez. El veredicto lo producía el modelo por su cuenta, sin
    ninguna ruta que lo verificara: `classify_relation` existía desde el día
    anterior con su prueba, y no lo llamaba nadie.
    """
    salida, correcciones = enforce_memory_truth(
        "¿la memoria persiste entre sesiones, o el recall es selectivo?",
        "Las dos afirmaciones se contradicen. La Bodega indexa episodios.",
        SNAPSHOT_VIVO,
    )

    assert "asserted_contradiction_corrected" in correcciones
    assert "removed:se contradicen" in correcciones
    # El veredicto no se afirma por criterio propio: se cita el del clasificador.
    assert "classify_relation" in salida
    assert "compatible" in salida.lower()
    # Y el resto de la respuesta sobrevive.
    assert "La Bodega indexa episodios." in salida
    assert "se contradicen" not in salida.lower()


def test_una_respuesta_que_no_afirma_contradiccion_no_se_toca():
    """La compuerta corrige un veredicto falso, no comenta cualquier respuesta."""
    original = (
        "Sí: conservo memoria persistente fuera de cada sesión, y recordar es "
        "selectivo."
    )
    salida, correcciones = enforce_memory_truth(
        "¿persiste tu memoria entre sesiones?", original, SNAPSHOT_VIVO
    )

    assert "classify_relation" not in salida
    assert "asserted_contradiction_corrected" not in correcciones


def test_el_veredicto_sale_del_clasificador_y_no_de_una_frase_fija():
    """Si el clasificador dijera que sí hay contradicción, no se corregiría nada.

    Es la diferencia entre comprobar y volver a acusar desde el otro lado: la
    compuerta sólo interviene cuando el veredicto comprobado dice que las dos
    afirmaciones se sostienen. Se fija aquí para que nadie sustituya la llamada
    por un texto enlatado.
    """
    from triade.memory.continuity_truth import (
        PERSISTENCE_CLAIM,
        SELECTIVE_RECALL_CLAIM,
    )
    from triade.os.claim_relation import ClaimRelation, classify_relation

    veredicto = classify_relation(PERSISTENCE_CLAIM, SELECTIVE_RECALL_CLAIM)
    assert veredicto.relation is not ClaimRelation.CONTRADICTION
    assert veredicto.reason


def test_la_compuerta_invoca_al_clasificador():
    """Un módulo probado y sin llamador no arregla nada.

    `claim_relation.py` llegó a `main` con 260 líneas, su prueba y **cero**
    importadores de producción: el arreglo estaba escrito y desconectado, así
    que el fallo que corregía seguía vivo. Esta prueba mira el cableado, no la
    conducta: si alguien quita la llamada, las de arriba podrían seguir en verde.
    """
    import ast
    from pathlib import Path

    modulo = (
        Path(__file__).resolve().parents[1]
        / "triade"
        / "memory"
        / "continuity_truth.py"
    )
    arbol = ast.parse(modulo.read_text(encoding="utf-8"))

    assert any(
        isinstance(n, ast.ImportFrom)
        and n.module == "triade.os.claim_relation"
        and any(a.name == "classify_relation" for a in n.names)
        for n in ast.walk(arbol)
    ), "continuity_truth ya no importa classify_relation"
    assert any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "classify_relation"
        for n in ast.walk(arbol)
    ), "importa el clasificador pero no lo llama"
