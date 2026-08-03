# Estado actual del supervisor externo

> Este archivo describe el proyecto desde fuera. No es memoria interna de Tríade.

## Identificación

- Rama: `main`
- Commit del ciclo: `b43db93`
- Fecha de auditoría: 2026-08-03
- Runtime: reiniciado a las 08:00 UTC con `.env` cargado. Watchdog en proceso
  (latido cada 60 s), governor de recursos por ciclo, backup diario activo.
- Entorno: Lightning Studio, NVIDIA L4 24 GB · 8 CPU · 31 GB RAM. Ollama en
  11434; app en 8010 bajo `nohup uvicorn`; base viva `triade/memory/triade.db`
  abierta siempre en `mode=ro` para auditar.

## Cómo leer la deuda sin engañarse

`/api/internal-graphs/debt`, o:

    python scripts/build_internal_graphs.py --output artifacts/internal_graphs

Tres reglas antes de citar la cifra:

1. **Comprobar la edad.** La estructura sale de artefactos. Desde D-009 la
   lectura los regenera sola al pasar de 15 min, pero *esa misma respuesta*
   describe la generación anterior: es la siguiente la que trae lo nuevo. El
   campo `refresh` dice si está al día, caducado o reconstruyéndose.
2. **Un descenso no es una mejora.** `debt_items_total` baja también al borrar un
   escritor o un fichero. Explicar por categoría antes de celebrar.
3. **Una subida tampoco es un empeoramiento.** El 2026-08-03 pasó de 56 a 111 al
   dejar de esconder dos categorías, y de ahí a 63 al corregir tres defectos de
   medición. La deuda no se movió tanto como la honestidad del contador.

## Deuda medida — 63 elementos (2026-08-03, grafos regenerados)

| categoría | n | naturaleza |
|---|---|---|
| tables with writer and no rows | 20 | Órganos completos que **nunca se han ejercitado**: todas tienen lector *y* escritor (1–3 cada una). `goals`, `kg_*`, `capability_registry`. No es código muerto: es capacidad sin estrenar |
| entrypoints without launcher | 17 | Herramientas de auditoría reales (86–335 líneas) que nadie sabe ejecutar sin leer el código |
| tables without reader or writer | 9 | Todas con 0 filas. Contrato pendiente: `benchmark_*` es el banco de pruebas que bloquea la autoevolución |
| task types never executed | 8 | Con handler cableado. Falta que se cumpla su precondición, no código |
| tables written never read | 5 | Se mide y nadie consume la medida |
| modules without importer | 3 | 554 líneas, cero referencias. Por decisión del operador (D-017) **no se borran: se conectarán** |
| declared services not running | 0 | Se mide por efecto desde F-052 |
| backup protection gaps | 0 | Clave rotada y copia verificada el 2026-08-03 |
| vital chain gaps | 1 | El eslabón `plan` sin escrituras desde el 1 de agosto (F-056) |

## Lo que se reparó en este ciclo

| # | qué estaba roto | prueba de que ya no |
|---|---|---|
| F-033 | El panel de deuda servía artefactos de horas como medición actual | Regeneración en segundo plano, no bloqueante: 0,4 s la petición, 55 s la reconstrucción |
| F-037/F-038 | El planner elegía 1 candidato de 665 y lo reintentaba para siempre | 20 evidencias nuevas en 40 min, sobre candidatos distintos |
| F-040 | El watchdog llevaba 3 días sin ejecutarse | Latido cada 60 s desde el reinicio |
| F-042 | Un `sqlite3.Error` abortaba todo `_plan_baseline` en instalación nueva | Prueba sobre base recién creada |
| F-043 | El worker gastaba sin consultar al metabolismo | Señal `worker_cycle_governor` por ciclo |
| F-046/F-047 | Cuatro días sin backup, en silencio, y clave perdida | Clave rotada, copia verificada con simulacro de restauración |
| F-050 | `/api/runtime/build` informaba del repo, no del código cargado | `code_matches_repo` en la respuesta |
| F-052 | Tres defectos de medición contaban deuda inexistente | 68 → 63 |
| F-053 | El sandbox declaraba límites que no aplicaba | Consumo medido y comparado; `sandbox_replay` con filas |

## Lo abierto, por riesgo

1. **F-055 (Alta)** — `federated_inference_probe` y `browser_benchmark` devuelven
   `random.randint()` como si fuera medición, por el mismo camino que un
   resultado real.
2. **F-056 (Alta)** — el eslabón `plan` no escribe desde el 1 de agosto: el
   sistema ejecuta sin replanificar.
3. **F-039 (Media)** — `improvement_proposals` e `improvement_canaries` no
   existen como tablas: `create_proposal` sólo lo llaman los tests.
4. **F-045 (Media)** — `metabolic_signals` tiene 3 escritores y ningún lector.
5. **F-044 (Media)** — `deploy/systemd/` declara servicios que aquí se cumplen
   en proceso; las unidades describen un despliegue que no existe.
6. **F-051 (Media)** — una conexión SSE abierta impide el cierre ordenado
   indefinidamente.
7. **F-054 (Baja)** — los `False` de red y escrituras del sandbox son ciertos por
   construcción, sin instrumentación que lo respalde.

## Cadena vital medida

`LIFE_PULSE → necesidad → plan → tarea → cola → worker → ejecución → verificación
→ aprendizaje → Bodega → efecto futuro`

Todos los eslabones escriben en el último minuto salvo **plan** (F-056).
`semantic_memory` y `neuron_education_applications` siguen a 0 filas: la Bodega
recibe episodios pero no consolida semántica, y el ciclo educativo no se aplica.
