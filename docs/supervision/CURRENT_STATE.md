# Estado actual del supervisor externo

> Este archivo describe el proyecto desde fuera. No es memoria interna de Tríade.

## Identificación

- Rama: `feat/claude-external-supervisor`
- Commit base del ciclo: `5757e64`
- PR: #69
- Fecha de auditoría: 2026-08-03
- Entorno ejecutado: Lightning Studio, NVIDIA L4 24 GB · 8 CPU · 31 GB RAM.
  Ollama 11434 con seis modelos presentes; app en 8010 arrancada y verificada;
  base viva `triade/memory/triade.db` (107 tablas) abierta siempre en `mode=ro`.

## Estado verificable

Las cifras salen de `artifacts/internal_graphs/`, regenerable con
`python scripts/build_internal_graphs.py --output artifacts/internal_graphs`.
No hay porcentajes globales: cada celda cita el grafo que la sostiene.

| Área | Estado | Evidencia | Vigencia |
|---|---|---|---|
| Seguridad e identidad | PARTIAL | `.env` y `.git` viajan enmascarados como `crypt:<sha256>` y sin contenido (`test_graphs_never_expose_secrets`). `identity_core` intacto, 6 filas, no tocado en este ciclo | 2026-08-03 |
| Grafo físico | VERIFIED | `file_graph.json`: 14 524 nodos, 22 ocultos inventariados, directorios de datos contados sin expandir | 2026-08-03 |
| Grafo de imports | VERIFIED | `import_graph.json`: 803 módulos, 5 303 aristas, 403 sin importador (54 en `triade/` y `apps/`) | 2026-08-03 |
| Grafo de llamadas | PARTIAL | `call_graph.json`: 6 753 símbolos, 9 850 llamadas resueltas. Sólo estático: no ve despacho dinámico | 2026-08-03 |
| Grafo de entrypoints | VERIFIED | `entrypoint_graph.json`: 77 entrypoints, 14 con lanzador real, 63 sin nadie que los arranque | 2026-08-03 |
| Grafo neural/runtime | VERIFIED | `neural_graph.json`: 402 nodos y 1 282 aristas desde SQLite en solo lectura | 2026-08-03 |
| LIFE_PULSE | VERIFIED | `vital_chain_graph.json`: `metabolic_cycle` 5 048 filas con actividad en 24 h | 2026-08-03 |
| Workers y scheduler | PARTIAL | `worker_graph.json`: 24 tipos declarados, 24 con handler, 9 con cero ejecuciones históricas | 2026-08-03 |
| SQLite y Bodega | PARTIAL | `table_graph.json`: 279 tablas referidas en código, 107 vivas. 11 vivas sin lector, 31 con escritor y cero filas | 2026-08-03 |
| Aprendizaje y educación | DISCONNECTED | `neuron_education_applications` 0 filas con 6 lectores y 5 escritores: el ciclo educativo nunca se aplica | 2026-08-03 |
| Qualia y Cristal | UNPROVEN_ACTIVITY | `qualia_*` suman ~16 600 filas y ningún lector en el código: se escribe y no se consume | 2026-08-03 |
| CI y pruebas | PARTIAL | Suite completa ejecutada en este ciclo; `tests/test_internal_graphs.py` 13 pruebas. `schemas.sql` incompleto hace que el planner se pruebe truncado (F-011) | 2026-08-03 |

## Cadena vital medida

`LIFE_PULSE → necesidad → plan → tarea → cola → worker → ejecución → verificación
→ aprendizaje → Bodega → efecto futuro`

Diez de los once eslabones tienen filas y actividad en 24 h. El undécimo, `Bodega`,
es el que se estrecha: `episodic_memory` 241 filas y `semantic_memory` 0. Ese
estrechamiento es lo que se trabajó en este ciclo (F-002).

## Fase activa

Fase 2 cerrada (grafos verificables) y Fase 4 abierta (memoria y aprendizaje).

## Bloqueos actuales

- F-005: Qualia escribe ~16 600 filas que nadie lee. Bloquea afirmar que Qualia
  influye en el comportamiento.
- F-006: la educación neuronal no registra ni una aplicación.
- F-011: el esquema de pruebas no refleja la base viva, así que la suite puede
  pasar sobre rutas que en producción se comportan de otro modo.

## Aprendizaje a partir del error (F-018)

Aprobado por el operador el 2026-08-03. Seis estados terminales —`failed`,
`timeout`, `dead_letter`, `lease_lost`, `blocked`, `cancelled`— dejan un
candidato de aprendizaje con la causa dentro. `completed` y `skipped` no
enseñan nada y no ingestan.

El límite es la parte que sostiene el permiso: el candidato **nunca** es
evidencia. `PRODUCTION_STATES` sigue siendo `{evidence_verified, stable}`, así
que un error acumula hacia el umbral sin cambiar lo que Tríade responde hasta
que gane evidencia. Fijado por `tests/test_failures_become_knowledge.py`.

## Última mejora comprobada

F-002: `semantic_memory_governance` pasó de imposible a encolable. La compuerta
del planner contaba sobre una tabla retirada con 0 filas; ahora cuenta sobre el
almacén vivo, que tiene 186 documentos `candidate`. Verificado contra la base de
producción en solo lectura y con una prueba que falla sin el arreglo.

## Próximo paso verificable

Cerrar F-014 por el otro extremo: `bodega._search_semantic` sigue recuperando de
`semantic_memory` y por tanto devuelve siempre vacío. Son 11 lectores apuntando a
la tabla retirada; requieren mapeo de columnas (`key`/`value` frente a
`document_id`/`content`) y por eso no entraron en este ciclo.
