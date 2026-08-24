"""El grafo de conocimiento deja de estar vacío porque alguien lo llena.

`kg_nodes`, `kg_edges` y `kg_contradictions` tenían escritor declarado y cero
filas: `add_claim`, `add_relation` y `add_contradiction` no los llamaba nadie.
Mientras tanto la API servía siete endpoints de sólo lectura sobre esas tablas,
todos devolviendo el caso vacío, y `TriadeOS` llamaba a `propagate_confidence()`
en cada ciclo sobre un grafo sin nodos.

El productor no había que inventarlo: la investigación gobernada ya produce
claims con su fuente y detecta las claves cuyas fuentes no coinciden.
"""

from __future__ import annotations

from pathlib import Path

from triade.observability.activation_contracts import ContractVerifier, load_contracts
from triade.os.knowledge_graph import KnowledgeGraph
from triade.research.knowledge_projection import project_research_into_graph

CLAIMS = [
    {"key": "altura", "value": "8848 m", "source_url": "https://a.example/1"},
    {"key": "altura", "value": "8849 m", "source_url": "https://b.example/2"},
    {"key": "cordillera", "value": "Himalaya", "source_url": "https://a.example/1"},
]
CONTRADICCIONES = [
    {"claim_key": "altura", "values": ["8848 m", "8849 m"], "resolution": "unresolved"}
]
ROOT = Path(__file__).resolve().parents[1]


def _kg(tmp_path) -> KnowledgeGraph:
    return KnowledgeGraph(tmp_path / "kg.db")


def test_los_claims_se_vuelven_nodos_con_su_fuente(tmp_path):
    kg = _kg(tmp_path)

    resumen = project_research_into_graph(
        kg,
        research_id="res-1",
        claims=CLAIMS,
        contradictions=[],
        domain="geografia",
    )

    assert resumen["nodes_added"] == 3
    nodos = kg.search_nodes(node_type="claim", domain="geografia")
    contenidos = {n.content for n in nodos}
    assert contenidos == {"altura: 8848 m", "altura: 8849 m", "cordillera: Himalaya"}
    fuentes = {n.source_ref for n in nodos}
    assert "https://a.example/1" in fuentes and "https://b.example/2" in fuentes


def test_la_contradiccion_produce_arista_y_se_materializa(tmp_path):
    kg = _kg(tmp_path)

    resumen = project_research_into_graph(
        kg,
        research_id="res-1",
        claims=CLAIMS,
        contradictions=CONTRADICCIONES,
        domain="geografia",
    )

    # Dos valores para `altura` → una arista `contradicts` entre sus dos nodos.
    assert resumen["edges_added"] == 1
    # Y `kg_contradictions` sale de esa arista, no de una escritura a mano.
    assert resumen["contradictions_detected"] >= 1
    assert kg.list_contradictions()


def test_repetir_la_misma_investigacion_no_infla_el_grafo(tmp_path):
    """Sin esto, el grafo mediría repetición y la llamaría actividad."""
    kg = _kg(tmp_path)
    argumentos = {
        "research_id": "res-1",
        "claims": CLAIMS,
        "contradictions": CONTRADICCIONES,
        "domain": "geografia",
    }

    primero = project_research_into_graph(kg, **argumentos)
    segundo = project_research_into_graph(kg, **{**argumentos, "research_id": "res-2"})

    assert primero["nodes_added"] == 3
    assert segundo == {
        "nodes_added": 0,
        "edges_added": 0,
        "contradictions_detected": 0,
    }
    assert kg.count_nodes(domain="geografia") == 3


def test_un_claim_que_es_prefijo_de_otro_no_es_el_mismo_claim(tmp_path):
    """`search_nodes` filtra con LIKE; la comparación exacta va después."""
    kg = _kg(tmp_path)

    project_research_into_graph(
        kg,
        research_id="res-1",
        claims=[{"key": "estado", "value": "ok"}],
        contradictions=[],
        domain="d",
    )
    project_research_into_graph(
        kg,
        research_id="res-2",
        claims=[{"key": "estado", "value": "ok pero degradado"}],
        contradictions=[],
        domain="d",
    )

    assert kg.count_nodes(domain="d") == 2


def test_un_claim_sin_clave_o_sin_valor_no_entra(tmp_path):
    kg = _kg(tmp_path)

    resumen = project_research_into_graph(
        kg,
        research_id="res-1",
        claims=[{"key": "", "value": "huerfano"}, {"key": "solo_clave", "value": ""}],
        contradictions=[{"claim_key": "solo_clave", "values": ["a", "b"]}],
        domain="d",
    )

    assert resumen == {
        "nodes_added": 0,
        "edges_added": 0,
        "contradictions_detected": 0,
    }
    assert kg.count_nodes() == 0


def test_las_tablas_relacionales_vacias_tienen_contrato_falsable(tmp_path):
    kg = _kg(tmp_path)
    project_research_into_graph(
        kg,
        research_id="sin-conflicto",
        claims=[{"key": "estado", "value": "verificado"}],
        contradictions=[],
        domain="d",
    )
    verifier = ContractVerifier(
        ROOT,
        table_profiles={
            "kg_edges": {"rows": 0},
            "kg_contradictions": {"rows": 0},
        },
        db_path=kg.db_path,
    )
    contracts = load_contracts()

    assert verifier.verify(contracts["table:kg_edges"]).holds
    assert verifier.verify(contracts["table:kg_contradictions"]).holds
