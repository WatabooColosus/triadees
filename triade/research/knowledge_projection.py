"""Lleva al grafo de conocimiento lo que la investigación gobernada ya produjo.

`KnowledgeGraph` estaba entero y desconectado: modela claims, relaciones y
contradicciones, `TriadeOS` lo instancia en cada ciclo y llama a
`propagate_confidence()`, y la API expone **siete** endpoints de sólo lectura
—`/knowledge-graph/search`, `/contradictions`, `/node/{id}`, `/summary`…— sobre
`kg_nodes`, `kg_edges` y `kg_contradictions`. Las tres tablas tenían cero filas
porque `add_claim`, `add_relation` y `add_contradiction` no los llamaba nadie:
los siete endpoints devolvían el caso vacío desde siempre.

Lo que faltaba no era un escritor, que ya existía: era el productor. Y no hace
falta inventarlo. `GovernedResearchWorker.run()` ya produce exactamente lo que
el grafo modela —claims con su fuente, y las claves cuyas fuentes no coinciden—
y lo persiste en `governed_research_runs`, que lleva 231 filas reales. Esto sólo
enruta ese artefacto a la tabla diseñada para sostenerlo.

Dos decisiones que conviene dejar dichas:

- **Se deduplica por contenido exacto dentro del dominio.** Sin eso, cada
  investigación repetida sobre el mismo tema volvería a insertar los mismos
  nodos y el grafo mediría actividad donde sólo hubo repetición.
- **`kg_contradictions` no se escribe a mano.** Se añaden las aristas
  `contradicts` y se deja que `detect_contradictions()` las materialice, que es
  el mecanismo que el subsistema ya tenía. Escribir la tabla por fuera habría
  producido filas sin la arista que las explica.
"""

from __future__ import annotations

from typing import Any

from triade.os.knowledge_graph import KnowledgeGraph


def _claim_content(claim: dict[str, Any]) -> str:
    """`clave: valor`, que es como el grafo guarda una afirmación."""
    key = str(claim.get("key") or claim.get("claim") or "").strip()
    value = str(claim.get("value") or "").strip()
    if not key or not value:
        return ""
    return f"{key}: {value}"


def _existing_claim(kg: KnowledgeGraph, content: str, domain: str | None) -> int | None:
    """El nodo con ese contenido exacto, si ya está.

    `search_nodes` filtra con LIKE, así que hay que comparar el contenido
    después: un claim que sea prefijo de otro no es el mismo claim.
    """
    for node in kg.search_nodes(query=content, node_type="claim", domain=domain):
        if node.content == content:
            return node.id
    return None


def project_research_into_graph(
    kg: KnowledgeGraph,
    *,
    research_id: str,
    claims: list[dict[str, Any]],
    contradictions: list[dict[str, Any]],
    domain: str | None = None,
) -> dict[str, int]:
    """Proyecta claims y contradicciones de una investigación en el grafo.

    Devuelve el recuento de lo que realmente cambió, no de lo que se intentó:
    un run repetido debe dar ceros, y así se puede comprobar.
    """
    nodos_nuevos = 0
    aristas_nuevas = 0
    por_clave: dict[str, list[int]] = {}

    for claim in claims:
        content = _claim_content(claim)
        if not content:
            continue
        node_id = _existing_claim(kg, content, domain)
        if node_id is None:
            node_id = kg.add_claim(
                content,
                domain=domain,
                source_ref=str(claim.get("source_url") or "") or None,
            )
            nodos_nuevos += 1
        clave = str(claim.get("key") or claim.get("claim") or "").strip()
        if clave and node_id not in por_clave.setdefault(clave, []):
            por_clave[clave].append(node_id)

    for contradiction in contradictions:
        clave = str(contradiction.get("claim_key") or "").strip()
        implicados = por_clave.get(clave) or []
        if len(implicados) < 2:
            # La contradicción venía de valores que no llegaron a ser nodos
            # (claim sin clave o sin valor). Sin los dos extremos no hay arista
            # que dibujar, y una contradicción sin extremos no se inventa.
            continue
        for indice, origen in enumerate(implicados):
            salientes = {
                (edge.target_id, edge.relation_type)
                for edge in kg.get_edges(origen, direction="out")
            }
            for destino in implicados[indice + 1 :]:
                if (destino, "contradicts") in salientes:
                    continue
                kg.add_relation(
                    origen,
                    destino,
                    "contradicts",
                    evidence_refs=[f"governed_research:{research_id}"],
                )
                aristas_nuevas += 1

    contradicciones = len(kg.detect_contradictions()) if aristas_nuevas else 0
    return {
        "nodes_added": nodos_nuevos,
        "edges_added": aristas_nuevas,
        "contradictions_detected": contradicciones,
    }
