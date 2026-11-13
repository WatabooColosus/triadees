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

- WorkerLoop migra cada tarea legacy a `autonomous_tasks` con clave idempotente,
  adquiere un lease v2 antes de ejecutarla y conserva retry/dead-letter/recovery.
  La cola legacy se mantiene como productor compatible durante la migración.
- El watchdog tiene entrypoint y persistencia; falta exponerlo en Cabina Viva y efectuar un simulacro prolongado.
- Los units son plantillas `/opt/triade`; deben adaptarse y revisarse antes de instalar.

## No implementado todavía

- CuriosityEngine y KnowledgeGapStore.
- Investigación multifuente completa y extracción de claims.
- Máquina unificada de conocimiento.
- La educación declara una hipótesis trazable en `learning_evidence`; evaluación
  independiente, transferencia y aplicación medida siguen siendo gates pendientes,
  por lo que una lección preparada nunca se presenta como aprendizaje.
- Benchmark de memoria y olvido completamente reversible.
- Flujo LoRA completo solicitado.
- Creación de las diez neuronas funcionales.
- Cabina Viva completa y E2E punta a punta nuevo.
- Cierre de los errores mypy globales del baseline.

Por tanto, Tríade aún no satisface el criterio final completo. Esta fase establece las garantías de supervivencia y recursos necesarias para continuar.
# Actualización 2026-07-29 — núcleo vivo event-driven

- Implementado heartbeat operacional de 5 s, CPU-only y sin LLM.
- Implementado scheduler monotónico con priority queue, jitter y wake event.
- La cola legacy despierta el WorkerLoop cuando entra trabajo.
- El sleep productivo del WorkerLoop baja de 60 s a despacho configurable de 20 s.
- Añadidos benchmarks reproducibles y simulación acelerada de 24 horas.
- Añadido perfil declarativo para 31 GiB RAM / NVIDIA L4 23.034 MiB.
- Pendiente: enforcement de ActivityBudget, backpressure completo, GPUResourceManager y separación de workers.
- Pytest, compileall, Ruff y frontend build están verdes en el corte local. Mypy
  global continúa rojo como deuda P2 explícita; no se desactivó, filtró ni presentó
  como verde. La publicación P0/P1 fue solicitada expresamente por el operador.
- `npm audit` queda en cero vulnerabilidades tras actualizar la dependencia
  transitiva vulnerable de PostCSS y reconstruir el frontend.
- Pytest completo y frontend build pasan; npm conserva una vulnerabilidad alta preexistente.
- Despliegue pendiente: systemd rechazó el reinicio por permisos, y el proceso activo aún ejecuta el código anterior.

## Auditoría de actividad real

La auditoría posterior detectó actividad autorreferencial histórica: 300 evidencias
de misión creadas por workers, cero evidencias externas de misión, 125 activaciones
sintéticas y 523 candidatos detenidos en `internally_checked`. Se corrigió el
planificador para no despachar esos ciclos como trabajo útil. Los pulsos sintéticos
ya no crean memoria, aprendizaje o Qualia, y el canary sintético queda desactivado
por defecto. Véase `SYSTEM_TRUTH_AUDIT_2026_07_29.md`.

## Plan de ejecución por PR

1. Baseline, perfil de hardware y métricas (incluido en esta rama).
2. Heartbeat ligero y scheduler event-driven (incluido en esta rama).
3. Renovación y recuperación de leases v2.
4. ActivityBudget, ResourceLedger por ventana y backpressure.
5. ModelWorker y GPUResourceManager con reserva y preemption.
6. Separación progresiva de workers especializados.
7. Pipeline de investigación y fallback gobernado.
8. Cabina Viva basada únicamente en eventos reales.
