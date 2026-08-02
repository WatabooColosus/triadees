# TRIADE · Matriz de capacidades

**Corte: 2026-08-02**, rama `audit/triade-continuous-learning-runtime`.
Sustituye al corte anterior del mismo día, archivado como
[`TRIADE_CAPABILITY_MATRIX_20260802_integral.md`](TRIADE_CAPABILITY_MATRIX_20260802_integral.md) —
**histórico**, no vigente.

Estados: **VERIFIED** (observado en runtime real, extremo a extremo) ·
**PARTIAL** · **DISCONNECTED** · **BROKEN** · **NOT_OBSERVED** ·
**BLOCKED_BY_ENVIRONMENT**.

Una clase, archivo, endpoint, handler o prueba unitaria **no** constituye por sí
solo una capacidad funcional.

| # | Capacidad | Impl. | Conect. | Probada | Observada | Persist. | Recuper. | Trazable | Autónoma | Riesgo | Estado | Evidencia |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Proceso always-on | sí | sí | sí | sí | sí | sí | sí | sí | bajo | **VERIFIED** | ciclos metabólicos continuos; `workers_active: true` |
| 2 | Encolado autónomo | sí | sí | sí | sí | sí | sí | sí | sí | bajo | **VERIFIED** | 24 tipos, 12 con ejecución real; planner por consulta SQL |
| 3 | Lease v2 con fencing | sí | sí | sí | sí | sí | sí | sí | sí | bajo | **VERIFIED** | `autonomous_tasks` + `lease_generation` |
| 4 | Recuperación de leases vencidos | sí | sí | sí | sí | sí | sí | sí | sí | era crítico | **VERIFIED** | P0 cerrado; recuperación <30 s bajo fallo inyectado |
| 5 | Reconciliación al arrancar | sí | sí | sí | sí | sí | sí | sí | sí | bajo | **VERIFIED** | 2 tareas colgadas → `completion_uncertain` |
| 6 | No-éxito-falso | sí | sí | sí | sí | — | — | sí | sí | bajo | **VERIFIED** | «efecto sin recibo verificable» → `retry_wait`; `failed: 0` |
| 7 | Concurrencia gobernada | sí | sí | sí | parcial | sí | sí | sí | sí | medio | **PARTIAL** | 24 políticas declaradas; no forcé saturación de carriles |
| 8 | Renovación de lease | sí | sí | sí | **no** | — | — | parcial | sí | medio | **NOT_OBSERVED** | I-1: 3 filas del 30-jul; causa sin determinar |
| 9 | Aprendizaje desde conversación | sí | sí | sí | sí | sí | sí | sí | sí | medio | **VERIFIED** | run → tarea → worker → candidato, en producción |
| 10 | Extracción atómica | sí | sí | sí | sí | sí | — | sí | sí | bajo | **VERIFIED** | proposición sola, no transcripción; ≤1 candidato/mensaje |
| 11 | Filtro de seguridad en extracción | sí | sí | sí | sí | — | — | sí | sí | medio | **VERIFIED** | ataque a identidad → `inseguro:blocked:gate_bypass` |
| 12 | Filtro de seguridad en recuperación | sí | sí | sí | sí | — | — | sí | sí | bajo | **VERIFIED** | `classify(malicioso) → blocked` |
| 13 | Deduplicación | sí | sí | sí | sí | sí | sí | sí | sí | bajo | **PARTIAL** | 428 ejecuciones; no verifiqué corrección de los grupos |
| 14 | Evidencia causal control/tratamiento | sí | sí | sí | sí | sí | sí | sí | sí | medio | **VERIFIED** | control 0.0 · tratamiento 1.0 · `improved`, inferencia real |
| 15 | Consolidación a saber verificado | sí | sí | sí | sí | sí | — | sí | sí | medio | **VERIFIED** | 1 → 2, encolada por el planner solo |
| 16 | Inyección en respuesta posterior | sí | sí | sí | sí | sí | — | sí | sí | bajo | **VERIFIED** | P1-03 cerrado: el saber aparece en la respuesta |
| 17 | Registro de autonomía | sí | sí | sí | sí | — | — | sí | sí | bajo | **VERIFIED** | gobierna el despacho del worker; 61 pruebas; sello `autonomy_precleared` para no duplicar gobierno |
| 18 | Doctor de aprendizaje continuo | sí | sí | sí | sí | — | — | sí | — | bajo | **VERIFIED** | `doctor continuous-learning` → `healthy` con procedencia |
| 19 | Educación neuronal → lección | sí | sí | sí | sí | sí | sí | sí | sí | bajo | **PARTIAL** | 7 sesiones en `lesson_prepared` |
| 20 | Educación neuronal → resolver y revertir | sí | sí | sí | parcial | sí | sí | sí | sí | medio | **PARTIAL** | resolutor conectado al ciclo; verificado en copia de producción. Falta el productor de `neuron_education_applications`: sin runs medidos devuelve `insufficient_evidence`, que es lo honesto |
| 21 | Canary: productor de observación | sí | sí | sí | **no** | sí | sí | sí | sí | medio | **PARTIAL** | P1-02 cerrado en código; sin canary abierto que observar |
| 22 | Memoria semántica | sí | sí | sí | sí | sí | sí | sí | sí | bajo | **VERIFIED** | heredado: control 0.00 → tratamiento 1.00 |
| 23 | Observabilidad con procedencia | sí | sí | sí | sí | — | — | sí | — | bajo | **VERIFIED** | endpoints cuadran con SQL; ventana declarada |
| 24 | Persistencia tras reinicio | sí | sí | sí | sí | sí | sí | sí | sí | bajo | **VERIFIED** | varios reinicios sin pérdida ni duplicación |
| 25 | Degradación sin Ollama | sí | sí | sí | **no** | — | — | sí | sí | medio | **NOT_OBSERVED** | no inyectado: habría degradado el runtime del usuario |
| 26 | Suite y CI | sí | sí | — | sí | — | — | — | — | bajo | **VERIFIED** | **1.910 pruebas, 0 fallos** |
| 27 | Long-run 2 h / 24 h / 72 h | sí | sí | — | **en curso** | — | — | sí | — | medio | **NOT_OBSERVED** | ventana de 2 h lanzada; 24 h y 72 h pendientes |

---

## Porcentaje por subsistema

| Subsistema | VERIFIED | PARTIAL | DISCONNECTED | NOT_OBSERVED | % verificado |
|---|---|---|---|---|---|
| Runtime always-on y recuperación (1-8) | 6 | 1 | 0 | 1 | **75 %** |
| Aprendizaje continuo (9-16) | 7 | 1 | 0 | 0 | **88 %** |
| Gobierno y diagnóstico (17-18) | 2 | 0 | 0 | 0 | **100 %** |
| Educación neuronal y canary (19-21) | 0 | 3 | 0 | 0 | **0 % verificado, 0 desconectado** |
| Memoria y observabilidad (22-24) | 3 | 0 | 0 | 0 | **100 %** |
| Entorno y certificación (25-27) | 1 | 0 | 0 | 2 | **33 %** |

Sin porcentaje global: sería un número inventado.

**El aprendizaje continuo pasó de 11 % a 88 %** en dos iteraciones. Los tres
eslabones que faltaban eran, por orden de descubrimiento: el control contaminado
por la ruta antigua, el filtro de seguridad ausente en la extracción, y la rama
de auditoría del prompt que descartaba el saber.

**La educación neuronal sigue en 0 %** y es el bloqueo principal para declarar
Tríade completa.

---

## Veredicto

### OPERATIVO CON LIMITACIONES

El circuito de **aprendizaje desde conversaciones está cerrado y verificado en
producción**, de la conversación al uso posterior. El runtime always-on se
recupera solo. La observabilidad declara su procedencia.

**No se puede declarar OPERATIVO** porque:

1. **Falta el productor de `neuron_education_applications`.** El resolutor
   existe, decide y revierte, pero sin runs medidos devuelve
   `insufficient_evidence` — que es la respuesta honesta, no un éxito. El
   circuito de la §16 del encargo no está cerrado hasta que algo registre cómo
   le fue a la neurona en runs posteriores.
2. Las ventanas de 24 h y 72 h no se han cumplido (§28).
3. `neuron_education_applications` sigue con **0 filas** en producción. La
   decisión `improved` está probada en aislamiento y sobre copia, **no
   observada en runtime real**.
