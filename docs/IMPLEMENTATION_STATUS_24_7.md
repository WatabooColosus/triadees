# Estado de implementación 24/7

## Implementado en la primera fase

- Auditoría reproducible de `aa001f3`.
- Migración aditiva `009_runtime_resilience.sql`.
- Cola autónoma v2 con idempotencia, claim `BEGIN IMMEDIATE`, ownership, renovación, backoff, dead-letter y recuperación de lease.
- ResourceLedger y degradación por presupuesto.
- Sondas de progreso y estados de salud.
- Recuperación con snapshot, auditoría y presupuesto.
- Unit files separados para API, workers, watchdog y backup.
- Instalador systemd dry-run por defecto; no instala, habilita ni arranca automáticamente.
- Ciclo continuo de educación neuronal con currículo, competencias, procedencia, independencia mínima y repetición espaciada.
- Investigación primaria inicial autorizada para visión mediante documentación OpenCV y Pillow.
- Estado observable en `/api/governance/education/status`.

## Parcial

- WorkerLoop legacy consulta el ledger y registra resultados, pero aún no consume la cola v2.
- El watchdog tiene entrypoint y persistencia; falta exponerlo en Cabina Viva y efectuar un simulacro prolongado.
- Los units son plantillas `/opt/triade`; deben adaptarse y revisarse antes de instalar.

## No implementado todavía

- CuriosityEngine y KnowledgeGapStore.
- Investigación multifuente completa y extracción de claims.
- Máquina unificada de conocimiento.
- Evaluación educativa independiente, transferencia y aplicación medida en runs.
- Benchmark de memoria y olvido completamente reversible.
- Flujo LoRA completo solicitado.
- Creación de las diez neuronas funcionales.
- Cabina Viva completa y E2E punta a punta nuevo.
- Cierre de los errores Ruff/mypy y vulnerabilidad npm del baseline.

Por tanto, Tríade aún no satisface el criterio final completo. Esta fase establece las garantías de supervivencia y recursos necesarias para continuar.
