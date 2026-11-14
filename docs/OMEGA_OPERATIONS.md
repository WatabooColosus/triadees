# Operación local de Tríade Ω

Estado de esta auditoría: **FULL NO CERTIFICADO** (captura 2026-11-14T00:35:43.967085+00:00).

## Fuente de verdad

- Raíz Git: `app/triadees`, rama `triade-local`, commit `059d4322`.
- Bodega: `triade/memory/triade.db`; respaldada antes de cambios y `PRAGMA integrity_check = ok`.
- API local: `http://127.0.0.1:8010`; Ollama: `http://127.0.0.1:11434`.

## Arranque seguro

Usar el entorno Python portable y `INICIAR_TRIADE.ps1` desde una sesión de usuario. Mantener `observe_only` hasta demostrar heartbeat, watchdog, workers y recuperación. No crear tareas administrativas ni exponer puertos.

## Evidencia actual

Los JSON en `artifacts/audits/` registran observaciones reproducibles. La API y Ollama responden; SQLite está íntegra. Hay ciclos metabólicos y eventos históricos, pero no se demostró continuidad del proceso ni ejecución de tareas en la ventana actual.

## Compuertas pendientes

1. Consultar endpoints de runtime y registrar `background_thread_alive`, heartbeat y workers.
2. Ejecutar una prueba controlada de reinicio del proceso, sin tocar la Bodega, y verificar recuperación sin duplicados.
3. Reparar o regenerar el insumo de `check_debt.py` de forma reversible.
4. Ejecutar probe neuronal y evaluación independiente antes de cualquier afirmación de aprendizaje o LoRA.
5. Repetir integridad SQLite y revisar métricas de recursos.

No se autoriza declarar FULL mientras alguna compuerta falle.
