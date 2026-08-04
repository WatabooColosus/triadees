# Fase 4 — Workers end-to-end

## Identidad y objetivo

- SHA base: `e0bedfe3d0caa7db981d55f60ba78b96985e95a7`
- Rama: `phase/04-workers-end-to-end`
- Objetivo: demostrar el circuito `planner → scheduler → queue → lease → handler → effect → evidence → completion` y cerrar contratos incompletos sin activar subsistemas nuevos.

## Estado inicial y hallazgo

El código existente ya contenía 24 tipos de tarea, cola SQLite con leases, fencing, handlers, políticas de autonomía, carriles de concurrencia, artefactos y rollback. Esas piezas eran alcanzables y varias tenían pruebas aisladas. No constituían todavía una capacidad demostrada como arquitectura completa: los handlers vivían en un diccionario local de `WorkerLoop`, no había relación canónica productor↔handler y faltaba declarar por tipo timeout, reintento, cooldown, idempotencia y evidencia.

La prueba end-to-end encontró además un fallo reproducible: `defer_unstarted()` devolvía la tarea a la cola y descontaba el intento —correcto para saturación transitoria—, pero podía hacerlo para siempre. Era un livelock persistente observable.

## Causa

Los contratos se habían acumulado en registros independientes, cada uno protegido por pruebas parciales. Ningún gate componía esas fuentes para exigir los 14 campos globales. El aplazamiento de despacho no tenía un presupuesto separado del número de intentos del handler.

## Cambios

- `triade/workers/architecture.py`: contrato canónico compuesto desde tipos, autonomía, concurrencia y cooldown existentes; declara productor, handler, idempotencia, evidencia, timeout y retry por los 24 tipos.
- `triade/runtime/task_leases.py`: guardia de livelock; después de 20 aplazamientos de despacho, cierra en `dead_letter` con `dispatch_livelock_guard` y transición auditable.
- `tests/test_worker_architecture_contract.py`: gate que falla ante un tipo incompleto, handler huérfano, productor huérfano u operación sin policy.
- `tests/test_workers_end_to_end_real.py`: usa SQLite temporal y efectos reversibles reales; no modifica la base ni el repositorio productivo.
- `scripts/run_phase_4_worker_audit.py`: auditoría reproducible y artefacto JSON versionado.

No hay migraciones. No se tocó `identity_core`, secretos, permisos ni fronteras de seguridad.

## Evidencia antes/después

| Medida | Antes | Después |
|---|---:|---:|
| tipos conocidos | 24 | 24 |
| contratos globales de 14 campos | 0 | 24 |
| correspondencia productor↔handler demostrada | no | 24/24 |
| operaciones con policy demostradas | parcial/separada | 24/24 |
| aplazamientos de despacho máximos | sin límite | 20 |
| livelock reproducible por aplazamiento | sí | no; termina auditado en `dead_letter` |

## Pruebas y resultados

Suite de contrato y regresión de workers ejecutada:

```text
pytest -q tests/test_worker_architecture_contract.py \
  tests/test_workers_end_to_end_real.py \
  tests/test_worker_concurrency_policy.py \
  tests/test_worker_concurrency_pool.py \
  tests/test_worker_loop_concurrency_integration.py \
  tests/test_orphaned_task_recovery.py \
  tests/test_governed_capability_rollback.py

110 passed; 4.618 s; 0 failed; 0 errors
```

Casos demostrados: éxito con artefacto, bloqueo, aplazamiento, deduplicación, lease vencido, caída y reinicio del worker, handler desconocido, operación no declarada, cooldown, guardia de livelock, dead letter y rollback real de fichero.

Los gates globales y sus resultados finales se registran en el PR; la fase no se recomienda para merge si alguno falla.

## Criterio de cierre

- 24/24 task types con contrato completo: cumplido.
- 0 handlers sin productor: cumplido.
- 0 productores sin handler: cumplido.
- 0 operaciones sin policy: cumplido.
- 0 livelocks reproducibles del despacho: cumplido mediante límite probado.

Esto demuestra el contrato y el circuito representativo ejecutado en una base temporal. No demuestra que cada uno de los 24 handlers haya producido un efecto real en producción, ni que todos los servicios externos estén disponibles.

## Riesgos, rollback y deuda restante

El límite de 20 aplazamientos prioriza terminar con diagnóstico frente a esperar indefinidamente. Un operador puede reencolar manualmente tras corregir la presión. Rollback del código: revertir los commits de esta fase. Rollback operacional: no hay migración ni mutación de datos productivos; las pruebas usan directorios temporales.

Deuda restante: medir en operación prolongada la frecuencia de `dispatch_livelock_guard`; calibrar el límite sólo con evidencia; demostrar individualmente los handlers que dependen de Ollama, GPU, backup o aprobación humana.

## Recomendación

Recomendar merge únicamente si la suite específica, los cinco gates globales y CI terminan en verde. No fusionar automáticamente este PR.
