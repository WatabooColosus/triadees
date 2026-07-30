# Deuda técnica vigente · Tríade Ω

Corte: 2026-07-30. SHA documental base: `8f44814`. Esta lista es canónica;
los reportes anteriores son históricos cuando la contradicen.

## P0 — certificación local

- **Pendiente:** ejecutar desde el SHA final, sin compresión, las ventanas de
  24 h y 72 h. El runner ya mide disponibilidad, duplicados, pérdidas, falsos
  `completed`, corrupción, resultados tardíos, artifacts, rollback, reinicios,
  snapshots y RSS. `long_run_verified=false` hasta que ambos reportes pasen.
- **Verificado en runtime aislado:** chaos 15/15 con worker y API reales,
  reinicio de Ollama, ENOSPC, watchdog, GPU oculta, memoria limitada y los diez
  fallos restantes. Cero duplicados, pérdidas, falsos cierres, corrupción,
  tardíos y artifacts perdidos; rollback 100%. La disponibilidad se mide en
  24/72 h, no se inventa para chaos.
- **Cerrado localmente:** Ruff pasó de 271 incidencias a cero y mypy de 224
  errores a cero en 324 archivos fuente, sin desactivar reglas ni añadir
  ignores/noqa/skips/xfail.
- **Parcial:** GitHub Actions estuvo verde en `00a05aa` para Runtime Truth CI,
  Tríade Tests y Measurement Core. Cada commit posterior invalida ese gate; se
  requiere registrar los cuatro workflows obligatorios en verde sobre el SHA
  final mediante `scripts/record_ci_evidence.py`.
- **Pendiente:** regenerar TRIADE-VERIFY-v1 sobre el SHA final. El manifest de
  `2e186b4` fue `PARTIAL_SAFE`: `long_run_verified=false` y
  `ci_verified=false`.

## P1 — producción confiable

- **Verificado localmente:** A/B real multi-modelo por siete roles. El routing
  adoptado mejoró calidad de 0.6786 a 0.9643 con ratio de recursos 1.302 dentro
  del límite predefinido 2.0; tiene evidencia hash y rollback atómico.
- **Pendiente externo:** LoRA canary requiere aprobación humana nominal, tráfico
  controlado real y rollback observado durante serving. Entrenamiento no activa
  automáticamente el adaptador.
- **Pendiente externo:** federación sostenida entre dos hosts distintos. Dos
  procesos TCP reales en un host ya prueban firma, reproducción y revocación,
  pero no equivalen a hosts separados ni a operación offline/online prolongada.
- **Verificado localmente:** rate limiting y sesiones/revocaciones compartidas
  usan Redis con operación Lua atómica; dos réplicas SQLite contra un Redis real
  probaron cuota y revocación cruzadas. `public_guarded` falla cerrado sin Redis.
- **Pendiente externo:** evaluación adversarial independiente de prompt
  injection, abuso y egress. Los tests internos no se presentan como auditoría
  externa.
- **Pendiente temporal:** mantener una ventana productiva legacy y confirmar
  duplicados/pérdidas cero antes de bloquear definitivamente writes o retirar
  tablas. No se borró historial.
- **Verificado una vez / seguimiento pendiente:** restore drill cifrado real,
  identidad, SQLite, 455 refs de artifacts y estados de tareas correctos. El
  worker agenda drills semanales, pero aún faltan semanas de cumplimiento.
- **Verificado localmente:** 503 snapshots históricos quedaron recuperables en
  cuarentena y el volumen bajó de 35 GB a 5.1 GB. Continúa pendiente observar
  crecimiento durante semanas y fijar presupuesto productivo.
- **Pendiente externo:** dominio estable, TLS, ingress y supervisión fuera de
  Cloudspace. La URL actual HTTP 200 no demuestra infraestructura persistente.

## P2 — madurez y escalabilidad

- **Parcial:** continuar separando fronteras DB, contracts, runtime, workers,
  security, federation y learning. El gate estático está verde, pero el tamaño y
  acoplamiento arquitectónico siguen requiriendo reducción incremental.
- **Cerrado para el baseline estático:** se retiraron catches silenciosos y
  amplios detectados por Ruff con manejo específico. Nuevos catches requieren
  revisión semántica aunque Ruff permanezca verde.
- **Pendiente:** ampliar memoria longitudinal con corpus independiente del
  implementador, casos adversariales y múltiples idiomas.
- **Pendiente:** repetir aprendizaje autónomo con tareas más complejas, corpus
  retenido y controles explícitos contra sobreajuste.
- **Pendiente temporal:** medir utilidad autónoma durante semanas; heartbeat,
  pulse y maintenance siguen excluidos de mejora.
- **Parcial:** existe observabilidad runtime actual y métricas de long-run;
  faltan series históricas durables y alertas operacionales externas.
- **Condicional:** generación visual solo se añadirá con caso de uso, evaluación
  de seguridad y benchmark. `gemma3:4b` aporta comprensión, no generación.
- **Pendiente:** benchmark reproducible de capacidad máxima de usuarios, tareas,
  memoria y almacenamiento.
- **Pendiente:** aprobar SLO, RTO, RPO y presupuesto de error de producción con
  resultados de capacidad y 72 h; no se fijarán números como hechos sin medir.
- **Límite explícito:** Tríade OS es un plano de control sobre Linux, no un
  kernel ni un sistema operativo anfitrión independiente.

## Cerrado con evidencia local

- Ejecución con lease, fencing, postcondición, artifact, receipt y rollback.
- Identidad continua, traza causal triádica, memoria longitudinal y modulación
  relacional gobernada.
- Metacognición calibrada, research gobernado, aprendizaje con transferencia,
  persistencia y rollback, Utility Ledger y certificación neuronal.
- Autenticación/RBAC/sesiones, estado distribuido Redis, backup cifrado y
  federación TCP de dos procesos.

## Regla de cierre

Una deuda solo se cierra con código, pruebas, evidencia runtime, documentación y
ruta de recuperación. Actividad, persistencia o etiquetas no sustituyen efecto,
recuperación útil ni aprendizaje validado.
