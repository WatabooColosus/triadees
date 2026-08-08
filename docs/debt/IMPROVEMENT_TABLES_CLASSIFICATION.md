# Las tablas de automejora: por qué están vacías

Fecha: 2026-08-08 · `main` en `25cb74d` · bloque A del [plan de deuda](DEBT_TRIAGE_PLAN.md).

Ocho de los 28 elementos de `tables_with_writer_and_no_rows` pertenecen al
subsistema `triade/self_improvement/`. **Ninguna es tabla muerta**: todas tienen
escritor y lector en módulos de producción, medido sobre `table_graph.json`.

| tabla | escritor | lector | filas |
|---|---|---|---|
| `improvement_signals` | `store.py` | `store.py` | 0 |
| `improvement_proposals` | `store.py`, `bridge.py` | `bridge.py`, `mission_planner.py` | 0 |
| `improvement_history` | `store.py`, `bridge.py` | `store.py` | 0 |
| `improvement_candidate_links` | `bridge.py` | `bridge.py`, `orchestrator.py` | 0 |
| `improvement_canaries` | `canary.py` | `canary.py`, `canary_observation.py` | 0 |
| `improvement_canary_observations` | `canary.py` | `canary.py` | 0 |
| `improvement_canary_consumed_reports` | `canary_observation.py` | `canary_observation.py` | ausente |
| `improvement_failure_lessons` | `failure_learning.py` | `failure_learning.py` | ausente |

## Clasificación: `HUMAN_GATED`, no `BROKEN_WRITER`

Las ocho cuelgan del mismo punto y por diseño: **una propuesta aprobada por un
humano**. `bridge.create_candidate` exige que la propuesta esté `approved`, y
`approve()` exige un `approved_by` no vacío. El handler
`_self_improvement_evaluation` lo dice en su propio docstring: *"un humano decide
qué dirección se intenta; la máquina hace la verificación rigurosa"*.

Cero filas significa, literalmente, que **nadie ha propuesto todavía una mejora**.
No que el circuito esté roto.

Que el circuito es alcanzable está demostrado: desde `c317010` existen las rutas
`/api/governance/improvement/{signals,proposals,proposals/{id}/approve,status}`,
y `tests/test_self_improvement_door.py` recorre señal → propuesta → firma humana
y comprueba que sin firma válida no se aprueba nada.

## Por qué siguen contando como deuda

Y está bien que cuenten. El detector no puede distinguir «vacía porque nadie la
usó» de «vacía porque está rota» sin saber qué evento la llenaría, y **inventar
esa excepción por nombre de tabla sería justo lo prohibido**: escondería una
rotura real el día que la hubiera.

La regla general que sí cerraría estos ocho —y cualquier otro caso equivalente—
es declarar la condición que produce filas y comprobarla:

    una tabla vacía cuyo escritor es alcanzable y cuya condición de escritura
    es un gate humano documentado no es deuda mientras el gate no se haya
    ejercido nunca

Eso exige que la condición esté declarada en algún sitio que el detector pueda
leer, no adivinada. No existe hoy, y construirlo es una decisión de diseño
—dónde vive esa declaración— que no se debe tomar de pasada.

## Nota de procedencia

Seis de estas tablas no existían en la base viva hasta el 2026-08-08. Las creó
una primera versión del endpoint de estado que instanciaba el store dentro de un
`GET`, corregida en `61e0f71`: consultar el estado no puede crear esquema. Las
filas no se han fabricado; lo que se creó fue el esquema vacío, y ahí sigue.

## Veredicto

`HUMAN_GATED` las ocho. Ninguna acción de código. Se llenarán cuando alguien
ejerza el gate — que es exactamente lo que debe pasar y ahora, por fin, se puede.
