# Auditoría del runtime vivo · 2026-07-31

Auditoría de sistema **en ejecución**, no de código. El objetivo era encontrar
componentes colgados, detenidos en silencio o **afirmando actividad falsa** —
esto último resultó ser lo más frecuente y lo más difícil de ver.

- Rama: `feat/governed-concurrency-and-self-improvement`
- `main`: `7988ae3` (**intacta**)
- PR: [#62](https://github.com/WatabooColosus/triadees/pull/62), abierto, **sin fusionar**
- Evidencia: `runs/live-runtime-audit/20260731-190605/`

## Estado inicial

| Componente | Estado | Postcondición verificada |
|---|---|---|
| API (`uvicorn`, pid 157039) | viva, 13 hilos, 356 MB | `HTTP 200` en 15 ms |
| Ollama (pid 9880) | vivo, 16 hilos | 6 modelos listados |
| Workers | activos, `full_local_guarded` | `last_cycle_at` avanza |
| Cabina Viva | responde | `HTTP 200` en 5,0 s |
| SQLite | 106,6 MB, WAL, `busy_timeout=10000` | `integrity_check: ok` |
| Process lock | presente, dueño **vivo** (157039) | no huérfano |

## Observación en tiempo real

Dos ventanas, snapshots cada ~20 s.

| Señal | PRE (28 snaps, 10 min) | POST (19 snaps, 6 min) | Veredicto |
|---|---|---|---|
| Cabina Viva `HTTP 200` | 28/28 | 19/19 | **sin un solo cuelgue** |
| Latencia media | 4,82 s | **3,97 s** | mejora |
| Latencia máxima | 10,4 s | **5,8 s** | mejora |
| Ciclos distintos | 10 | 7 | scheduler **avanza** |
| Tareas completadas | +8 | +5 | runtime **progresa** |
| Locks huérfanos | 0 | 0 | — |

Carga bajo prueba: 10 llamadas secuenciales (todas 200, 3,8–6,2 s) y 5
concurrentes (todas 200, ~17 s, se serializan). Tras la carga, `health/live`
respondió en **1,8 ms**: el pool de FastAPI se recupera.

## Defectos encontrados

| Sev | Defecto | Evidencia | Causa | Reparación | Test |
|---|---|---|---|---|---|
| **P0** | Cabina Viva colgada indefinidamente | 50 hilos del pool en el mismo frame; sin respuesta en 120 s | `ensure_workers_alive` pedía `_WORKER_LOCK` y llamaba dentro a `build_workers_always_on_status`, que lo vuelve a pedir. `Lock` no reentrante → se esperaba a sí mismo **sin soltarlo** | sacar la llamada del `with` | `test_worker_autostart_deadlock.py` |
| **P0** | 12 tareas en `completion_uncertain` hasta 20 h | 4 creadas 10 min antes del snapshot | recuperación las aparca sin artefacto; `reconcile_uncertain_completions` hacía `failed += 1` **sin transicionar** | cierre como `dead_letter` con razón | `test_uncertain_completion_leak.py` |
| **P0** | Promoción estable **sin aprobación humana** | `update_status(name,"stable")` tras umbrales; cero `human`/`approval` en la ruta | el gate nunca existió ahí | `stable_promotion_gate` exige firma nominal | `test_stable_promotion_human_gate.py` |
| **P1** | El gate humano bloqueaba lo reversible | proponer exigía firma; circuito inerte | gate en G1 en vez de G3 | G1 automático | ídem |
| **P1** | Run se declaraba `completed` con tareas vivas | — | shutdown solo reportaba `still_running` | espera dura + `completed_with_active_tasks` + **conserva el lock** | `test_controlled_shutdown_live.py` |
| **P1** | Test de deadlock pasaba **sin ejecutar la función** | `PytestUnhandledThreadExceptionWarning` | `TypeError` por firma; el helper solo miraba "¿terminó?" | re-lanzar la excepción | ídem |
| **P2** | La auditoría buscaba el lock donde no está | "no hay lock" en 28 snapshots | el lock vive en `runs_dir` | rutas corregidas | — |

Lo más instructivo: **tres de los siete defectos eran mentiras del sistema sobre
sí mismo**, no caídas. Un servicio caído se ve; uno que dice estar bien, no.

## Hallazgos estructurales (no reparados, y por qué)

### El aprendizaje no puede consolidarse: falta el productor de evidencia

- **620** candidatos en `learning_queue`, **todos** en `internally_checked`
- **16 superan** el umbral `MIN_RUN_USES=3`; uno con **44 usos y score 0,934**
- Ninguno progresa: `require_improvement()` exige evidencia Measurement Core
- `learning_evidence`: **1 fila** para 620 candidatos

Los únicos productores de esa evidencia (`neuron_factory`, `self_improvement`,
`lora_trainer`) operan sobre **candidatas neuronales**, no sobre candidatos de
conversación. Ese eslabón **no tiene productor cableado**.

No se reparó bajando el gate: eso convertiría 620 lecciones no verificadas en
conocimiento estable, que es exactamente el éxito falso que este runtime existe
para impedir. Construir el productor es una capacidad nueva, no un arreglo.

### El circuito de automejora está conectado pero vacío

`improvement_proposals` **no existe** en la base: cero propuestas en toda la
historia. El motor de evaluación funciona; no tiene nada que evaluar. Falta un
productor automático de propuestas.

### El canary atribuye por tiempo, no por causa

Declarado explícitamente (`causal_attribution: "temporal_only"`). Sin enrutado
por candidata no se puede demostrar que la candidata sirviera esas respuestas.
Por eso el canary solo puede mantener, declarar elegible o **revertir** — nunca
promover.

## Gobernanza: dónde quedó el gate humano

| Nivel | Qué | Decisión |
|---|---|---|
| G0 Observación | diagnóstico, métricas | automática |
| G1 Experimental | investigar, currículo, **proponer**, candidata, sandbox | automática |
| G2 Reversible | evaluación, canary, observación, rollback | automática gobernada |
| **G3 Estable** | **promover a estable** | **firma humana nominal** |
| G4 Crítico | `identity_core`, constitución, privilegios | prohibido |

Estaba invertido en G1 y G3. Ahora:

```bash
TRIADE_STABLE_PROMOTION_APPROVED_BY=<nombre>   # para promover a estable
TRIADE_SELF_IMPROVEMENT_AUTO_APPROVE=0         # para volver a exigir firma al proponer
```

## Concurrencia

Verificada con `TRIADE_WORKER_CONCURRENCY=1` sobre copia de la base real:
**19/19**, incluidas exclusión por `candidate_id`, serialización de
`critical_mutation`, no-doble-cierre y 72 escrituras desde 6 hilos sin
`database is locked`.

**Sigue apagada por defecto.** El fallo de CI que obligó a apagarla no se
reprodujo ni limitando a 2 CPU ni sin Ollama: **no está entendido**. No se activa
por defecto una capacidad cuyo modo de fallo no se comprende.

## Riesgos restantes

**Verificado:** deadlock resuelto; tareas fantasma cerradas; gate en G3; lock
conservado con tareas vivas; SQLite sin bloqueos; runtime progresa.

**Inferido:** estabilidad a 24 h — la ventana fue de 16 minutos en total.

**No verificado:** el circuito completo propuesta → candidata → sandbox → canary
ejecutado de principio a fin; el comportamiento de la concurrencia bajo carga
real sostenida.
