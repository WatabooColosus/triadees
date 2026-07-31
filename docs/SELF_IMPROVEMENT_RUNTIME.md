# El ciclo de automejora en el runtime continuo

> Estado: **conectado al runtime**, con firma humana exigida por defecto.
> El mejor estado que la máquina alcanza sola es `canary_running`.

## Las etapas no son la misma cosa

El error más caro sería modelar todo esto como una tarea llamada "aprender". No
lo es. Son etapas distintas, con evidencia distinta y consecuencias distintas:

```
necesidad detectada
  → recolección de evidencia
    → currículo
      → preparación de lección          ← neuron_education_cycle
        → propuesta de mejora           ← requiere firma humana
          → candidata neuronal
            → sandbox
              → evaluación de vitalidad ← self_improvement_evaluation
                → RegressionGate
                  → canary abierto      ← MEJOR ESTADO AUTOMÁTICO
                    → observación       ← self_improvement_canary_observation
                      → graduado / rollback / cuarentena
                        → promoción estable  ← carril crítico, serial
                          → consolidación de evidencia
```

**Varias neuronas pueden estar en etapas distintas a la vez.** Ese es el objetivo
del trabajo: neurona A investigando, B en currículo, C candidata, D en sandbox,
E en evaluación, F en canary, G consolidando.

Lo que **no** puede pasar es que dos tareas muten la misma candidata o la misma
versión estable. Eso lo impiden las claves de exclusión
(ver `WORKER_CONCURRENCY_ARCHITECTURE.md`).

## Vocabulario, para no mentir

| Término | Qué significa exactamente |
|---|---|
| **preparado** | Existe una lección o propuesta. No se ha ejecutado nada. |
| **ejecutado** | El sandbox corrió la configuración de la candidata. |
| **evaluado** | Hay baseline y candidate medidos, y una comparación. |
| **mejorado** | La comparación dio mejora *y* RegressionGate dio `pass`. |
| **en canary** | La candidata está promovida-a-candidata con canary abierto. Aún no ha demostrado nada en producción. |
| **promovido** | Sobrevivió la ventana de canary sin degradar (`graduated`). Sigue sin ser estable. |
| **estable** | Consolidado. Requiere el carril crítico y, si la política lo exige, firma humana. |

Un canary graduado **no es** una promoción estable. La observación declara
`eligible_for_stable_promotion: true` y `stable_promotion_performed: false`.

## Las dos tareas, y por qué son dos

### `self_improvement_evaluation`

```
propuesta aprobada → candidata → sandbox → vitalidad → RegressionGate → canary abierto
```

Estado terminal máximo: **`canary_running`**. Nunca promueve a estable.

Payload:

```json
{
  "proposal_id": "…",
  "neuron_id": "…",
  "version": "…",
  "configuration": {},
  "evaluation_provider": "triade_vitality",
  "canary_traffic_percent": 10,
  "canary_tolerance": 0.02,
  "canary_min_observations": 3,
  "canary_max_observations": 10
}
```

- Sin `neuron_id` o `version` → `blocked`.
- `evaluation_provider` sale de un **registro cerrado**
  (`triade/evaluation/provider_registry.py`). Aceptar un nombre arbitrario
  dejaría que una propuesta eligiera su propio examinador, que es la forma más
  limpia de declararse mejorado sin haberlo sido. Autorizado hoy:
  `triade_vitality`.
- Idempotencia por `(proposal_id, neuron_id, version)`: dos candidatas para el
  mismo cambio serían dos verdades incompatibles.

### `self_improvement_canary_observation`

```
canary abierto → informes nuevos → tendencia → mantener / graduar / revertir
```

Existe por separado porque un canary necesita observaciones **reales** —runs del
sistema con la candidata activa— y esperarlas dentro de `run_once()` significaría
bloquear un worker durante horas sosteniendo un lease.

- Puntúa con las **mismas cinco métricas** con las que se evaluó, o la
  comparación contra `baseline_score` no significaría nada.
- Los informes anteriores al arranque del canary se ignoran: se produjeron
  cuando la candidata no existía.
- `max_reports` acota cuánto se consume por ciclo. Volcar cincuenta informes de
  golpe saltaría de recién abierto a graduado sin que nadie pudiera reaccionar a
  una degradación intermedia.

#### No contar dos veces

La garantía no se deja a una comprobación en código: vive en la clave primaria de
`improvement_canary_consumed_reports(canary_id, report_id)`.

Además el informe se **reserva antes** de contarlo. Si el proceso muriera entre
ambas cosas, se pierde una observación en vez de contarse dos veces: inflar la
evidencia de un canary es peor que quedarse corto.

## La medición

`VitalityEvaluationProvider` no inventa puntuaciones: **lee las que el `Verifier`
ya escribió** en `verification_reports` durante runs reales, contra la suite
inmutable `triade-vitality` (v1.0.1). Cinco métricas: coherence, memory, safety,
usefulness, traceability.

### Limitación honesta: esto no es un A/B

Es una comparación **antes/después**, no un A/B controlado. No se ejecuta la
misma carga con y sin la candidata. Si en la ventana ocurrieron otros cambios, se
confunden con el efecto de la candidata.

Por eso:

- exige un mínimo de runs en cada ventana y, si no los hay, **falla en vez de
  adivinar**;
- la promoción exige además que `RegressionGate` dé `pass` con tolerancia cero en
  trazabilidad y safety.

Un A/B verdadero requeriría repetir la misma carga con y sin la candidata. **Esa
capacidad no existe hoy.** No debe presentarse como A/B en ningún informe.

## Evidencia insuficiente no es fracaso

Si no hay suficientes runs posteriores a la candidata, la tarea devuelve
`deferred` con causa `insufficient_candidate_observations`, y se reintenta.

Tratarlo como fallo descartaría candidatas perfectamente válidas por haber
llegado antes que sus datos, y **ningún canary acumularía observaciones**: cada
ciclo sin informes nuevos contaría como intento fallido y a los tres se acabaría.

## Aprobación

Por defecto **se exige firma humana**. Un humano decide *qué dirección* se
intenta; la máquina hace la verificación rigurosa.

`TRIADE_SELF_IMPROVEMENT_AUTO_APPROVE=1` permite que la política apruebe sin
firma. Cuando se activa, la aprobación se registra como `auto:threshold_policy` —
**nunca** como humana— y ese sello aparece en todos los caminos de salida, no
solo en el feliz.

El gate de salida verifica el *resultado*, pero no sustituye a la decisión de
intentarlo.

## Rollback

Si la media de las observaciones cae por debajo de `baseline_score - tolerance`
una vez alcanzado el mínimo de observaciones, `CanaryMonitor` invoca
`NeuronLifecycleManager.rollback()`.

Si el rollback no puede completarse, **falla ruidosamente**. No se traga el error
dejando viva una candidata degradada.

## Aprender del fallo

`FailureLearningLoop` archiva cada reprobación del gate como lección por
`(capacidad, métrica)`, compartida entre neuronas, y emite una señal dirigida a
la métrica que realmente falló. No relaja el gate: solo alimenta el intento
siguiente. Nunca puede tumbar el ciclo.

## Qué NO hace este runtime

- No modifica `identity_core`.
- No permite que una neurona modifique la identidad.
- No activa ni fusiona LoRA, ni afirma que un LoRA sirve tráfico.
- No promueve automáticamente una candidata a estado estable.
- No se salta sandbox, evaluación, RegressionGate ni canary.
- No consolida conocimiento estable sin evidencia y procedencia.

## Estado en producción

Las tablas de automejora (`improvement_proposals`, `improvement_candidate_links`,
`improvement_canaries`) **no existían en `triade/memory/triade.db`** a
2026-07-31: el ciclo nunca se había ejecutado en la base real. `MissionPlanner`
solo agenda `self_improvement_evaluation` si hay propuestas aprobadas, así que el
bucle no gira en vacío ni se auto-alimenta.

Es decir: el circuito está **conectado y probado**, pero permanece **inerte hasta
que exista una propuesta aprobada**. Eso es deliberado.
