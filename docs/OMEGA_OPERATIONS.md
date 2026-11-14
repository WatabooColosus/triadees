# Operacion local de Tríade Ω

Estado operativo: **FULL NO CERTIFICADO**.

## Fuente de verdad

- Repositorio: `D:\TRIADE_PORTABLE_V0_1\app\triadees`.
- Rama: `triade-local`.
- SQLite: `triade/memory/triade.db`.
- API: `http://127.0.0.1:8010`.
- Ollama: `http://127.0.0.1:11434`.
- Supervisor: `scripts/start_triade_windows.ps1` y `scripts/triade_service_worker.ps1`.

## Arranque y continuidad

El supervisor de usuario mantiene una sola cadena API → Always-On → workers. Usa lock, backoff y logs en `artifacts/service_logs`. El runtime debe permanecer en `full_local_guarded`; si el worker pierde una lease, el watchdog y el recuperador deben registrar la transición antes de reintentar.

## Recursos

El gobernador adaptativo mide CPU, RAM, disco, energía, Ollama y GPU. Perfil seguro actual: dos tareas globales, dos tareas ligeras y una inferencia generativa. Ollama mantiene un solo modelo residente y una sola inferencia. La Intel Iris Xe está inventariada, pero su uso por Ollama no está demostrado.

## Fase 3

La cadena educativa es:

```text
misión → material → baseline → sesión → probes → comparación → assignment → holdout → validated_in_runs → canary → promoción
```

La evidencia `improved` no autoriza promoción por sí sola. Cada candidato necesita holdout específico, regresión independiente y canario reversible.

Estado conocido: assignments experimentales y aplicaciones reales existen; `validated_in_runs` y canarios siguen en cero. Mantener la promoción estable bloqueada.

## Auditoría y recuperación

Consultar los JSON de `artifacts/audits/`, especialmente:

- `omega_debt_report.json`
- `omega_phase4_worker_audit.json`
- `omega_phase3_traceability.json`
- `omega_phase3_candidate_validation_requests.json`
- `omega_adaptive_resources.json`
- `omega_phase6_service_health.json`

No borrar ni reinicializar la Bodega. Antes de cualquier migración, crear copia consistente y ejecutar `PRAGMA integrity_check` y `PRAGMA foreign_key_check`. No declarar FULL mientras falten validación independiente, canario y rollback verificables.
