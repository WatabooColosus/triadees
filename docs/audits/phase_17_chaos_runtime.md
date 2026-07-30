# Fase 17 — chaos y operación prolongada

Fecha UTC: 2026-07-30

Base: `7e5af4a`

Estado: `partial`

Se crearon los runners de 24h y 72h con duración wall-clock real. Sus defaults
son exactamente 86,400 y 259,200 segundos; no aceleran ni comprimen tiempo. Una
prueba corta separada comprueba web, Ollama e integridad SQLite.

El chaos corto inyecta los quince escenarios en recursos aislados. Para los
cinco fallos antes pendientes usa: un servidor Ollama real en un puerto temporal
que se termina y arranca de nuevo; `/dev/full` para obtener `ENOSPC`; el watchdog
real contra una SQLite temporal con snapshot y reinicio; un proceso con
`CUDA_VISIBLE_DEVICES=-1`; y un proceso limitado por `RLIMIT_AS` que confirma
`MemoryError`. No mata la web ni Ollama productivos.

El runner prolongado registra en cada checkpoint disponibilidad, integridad,
duplicados por idempotency key, tareas baseline desaparecidas, falsos
`completed`, pérdida de artifacts y recuperaciones de workers. Al inicio y al
final ejecuta probes aislados de fencing tardío y rollback SQLite. El reporte
también conserva crecimiento de snapshots y RSS del propio monitor. El gate
terminal exige cero duplicados, pérdidas, falsos `completed`, corrupción,
resultados tardíos y artifacts perdidos, rollback 100% y disponibilidad mínima
99%.

## Reproducción

```bash
python scripts/run_triade_chaos_validation.py
python scripts/run_24h_runtime_validation.py
python scripts/run_72h_runtime_validation.py
```

Evidencia corta: `artifacts/triade_verify/phase_17/chaos_short.json` y
`runtime_short.json`.

Estado: `implementation_complete`, `long_run_pending`. Los quince escenarios
aislados pasaron. Sus métricas tienen scope `isolated_short_scenarios`; la
disponibilidad queda explícitamente `null`. Todavía no se verifica availability
24/72h ni que todos los umbrales se mantengan durante ambas ventanas completas.

## Validación ejecutada

```text
pytest -q tests/test_runtime_long_run.py tests/test_runtime_watchdog.py PASS (8)
python scripts/run_triade_chaos_validation.py                    PASS subset
24h runner --duration-seconds 10 (short separado)                PASS
pytest -q tests/operational_truth                               PASS (18)
python scripts/run_runtime_concurrency_test.py                  PASS
ruff check (archivos de fase) / format                          PASS
```

La ventana corta duró al menos 10.0 segundos reales, seis checkpoints, 100% de
availability, DB corruption 0, web 200 y Ollama 200. Esto no sustituye 24h.

Una primera ejecución prolongada iniciada el 2026-07-30 fue invalidada tras
detectar que su versión del runner solo medía disponibilidad e integridad. Sus
horas transcurridas no se reutilizan. Las ventanas certificables deben comenzar
desde cero con el runner que incluye todas las métricas anteriores.

Ejecución adicional 2026-07-30: los 15/15 escenarios chaos aislados pasaron;
duplicate effects 0, lost tasks 0, false completed 0, DB corruption 0, late
results accepted 0, artifact loss 0 y rollback 100% dentro de ese scope. Tras
la inyección, web local, web pública y Ollama respondieron HTTP 200.
