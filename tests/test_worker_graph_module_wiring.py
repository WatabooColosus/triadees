"""El grafo de workers tiene que poder detectar denervación en su propia carpeta.

Antes escribía `"active"` a mano por el mero hecho de que el fichero existiera y
sólo emitía dos relaciones —`contracts → tipo` y `tipo → worker_loop`—, así que
ningún módulo tenía jamás entrada ni salida: 11 de 13 salían aislados y en verde
a la vez. Entre los aislados estaba el espinazo vivo del planificador
(`worker_loop → scheduler → mission_planner → adaptive_scheduler → task_queue`),
y en el mismo verde estaban `advanced_scheduler` y `worker_supervisor`, que no
los alcanza ningún entrypoint que alguien arranque.

Un grafo que pinta igual las dos cosas no es observabilidad: es decoración.
"""

from __future__ import annotations

from pathlib import Path

from triade.observability.code_graph import (
    build_module_index,
    reachable_modules,
)
from triade.observability.runtime_graph import build_worker_graph

REPO_ROOT = Path(__file__).resolve().parent.parent


def _grafo() -> tuple[dict[str, object], list]:
    nodes, edges = build_worker_graph(REPO_ROOT, build_module_index(REPO_ROOT))
    return {n.node_id: n for n in nodes}, edges


def _grados(nodes: dict, edges: list) -> dict[str, int]:
    grado = dict.fromkeys(nodes, 0)
    for edge in edges:
        if edge.source in grado:
            grado[edge.source] += 1
        if edge.target in grado:
            grado[edge.target] += 1
    return grado


def test_el_espinazo_del_planificador_esta_dibujado() -> None:
    """La cadena por la que pasa cada tarea no puede salir como nodos sueltos."""
    nodes, edges = _grafo()
    imports = {
        (e.source, e.target) for e in edges if e.relation == "imports"
    }

    def arista(origen: str, destino: str) -> bool:
        return (
            f"worker_module:triade/workers/{origen}.py",
            f"worker_module:triade/workers/{destino}.py",
        ) in imports

    assert arista("worker_loop", "scheduler")
    assert arista("scheduler", "mission_planner")
    assert arista("scheduler", "adaptive_scheduler")
    assert arista("scheduler", "task_queue")


def test_ningun_modulo_vivo_queda_sin_entrada_ni_salida() -> None:
    """Un módulo alcanzable tiene que tener al menos una arista que lo demuestre."""
    nodes, edges = _grafo()
    grado = _grados(nodes, edges)

    sueltos = [
        node_id
        for node_id, node in nodes.items()
        if node_id.startswith("worker_module:")
        and node.state == "active"
        and grado[node_id] == 0
    ]
    assert sueltos == [], f"módulos vivos sin ninguna arista: {sueltos}"


def test_lo_que_ningun_entrypoint_alcanza_no_se_pinta_de_verde() -> None:
    """`advanced_scheduler` y `worker_supervisor` tienen importadores, pero muertos.

    Es la distinción que la cuenta de importadores no puede hacer: los importa
    código que a su vez no ejecuta nadie.
    """
    nodes, _edges = _grafo()
    alcanzables = reachable_modules(REPO_ROOT, build_module_index(REPO_ROOT))

    for nombre in ("advanced_scheduler", "worker_supervisor"):
        node = nodes[f"worker_module:triade/workers/{nombre}.py"]
        assert node.state == "disconnected"
        assert node.metadata["reachable_from_entrypoint"] is False
        # Tiene importadores: no es que nadie lo nombre, es que nadie lo ejecuta.
        assert node.metadata["importers"] > 0
        assert node.metadata["live_importers"] == []
        assert f"triade/workers/{nombre}.py" not in alcanzables


def test_el_estado_sale_de_la_evidencia_y_no_de_que_el_fichero_exista() -> None:
    """Un módulo nuevo sin importadores no puede nacer en verde."""
    nodes, _edges = _grafo()
    modulos = [n for k, n in nodes.items() if k.startswith("worker_module:")]

    assert modulos, "el grafo debe tener módulos de workers"
    for node in modulos:
        assert node.state == (
            "active" if node.metadata["reachable_from_entrypoint"] else "disconnected"
        )


def test_solo_se_dibujan_importadores_externos_que_se_ejecutan() -> None:
    """Pintar un importador muerto sugeriría una conexión que nunca ocurre."""
    nodes, edges = _grafo()
    alcanzables = reachable_modules(REPO_ROOT, build_module_index(REPO_ROOT))

    externos = [
        n for k, n in nodes.items() if n.metadata.get("external_to_workers") is True
    ]
    assert externos, "el cableado externo debe ser visible"
    for node in externos:
        assert node.metadata["path"] in alcanzables

    # Y toda arista apunta a un nodo que existe: nada de aristas colgando.
    conocidos = set(nodes)
    for edge in edges:
        assert edge.source in conocidos
        assert edge.target in conocidos
