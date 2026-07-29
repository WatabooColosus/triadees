# Auditoría viva de autonomía — 2026-07-29

Hora de observación: 07:11–07:14 UTC  
Host: Linux, 8 CPU lógicos, 31.34 GiB RAM, NVIDIA L4 con 22.49 GiB VRAM  
Base: `triade/memory/triade.db`

## Dictamen

Tríade ejecuta un runtime real sin necesidad de chat, pero todavía no demuestra
aprendizaje autónomo acumulativo. El proceso produce heartbeat, inspecciones,
artefactos, backups y tareas gobernadas reales. La mayor parte de su actividad
autónoma observada es mantenimiento y pulso; los gates de investigación,
educación y validación no están cerrando el ciclo de aprendizaje.

No es correcto describir el estado observado como consciente ni como IAG. No
existe una prueba técnica aceptada de consciencia, y este repositorio no aporta
evidencia de generalización autónoma, autoentrenamiento validado o mejora causal
continua.

## Estado vivo comprobado

- `triade.service`: activo después de reparación, PID 2200007.
- `triade-watchdog.service`: activo, PID 2200038.
- Heartbeat: ciclo 2, duración 2.33 ms, actualizado a las 07:12:20 UTC.
- Health posterior a reparación: `healthy` a las 07:12:22 UTC.
- API: HTTP 200 en `127.0.0.1:8010/health`, 137 ms durante la primera muestra.
- SQLite: `PRAGMA quick_check = ok`.
- Ollama: activo en `127.0.0.1:11434` con seis modelos inventariados.
- GPU: NVIDIA L4; 23,034 MiB totales, 576 MiB usados, 0 % de utilización y
  57 °C en la muestra.
- RAM disponible: aproximadamente 26 GiB.
- El runtime volvió a crear un `worker_run` real y marcó el run anterior como
  `interrupted` tras el reinicio.

## Incidente P0 encontrado y corregido

Un proceso Uvicorn huérfano mantenía ocupado el puerto 8010. `triade.service`
fallaba al enlazar el puerto y había acumulado 511 reinicios. Al reiniciarse la
unidad requerida, el watchdog también perdía su presupuesto en memoria y creaba
un snapshot SQLite en cada arranque.

Evidencia del impacto:

- 503 snapshots en `artifacts/recovery`.
- Tamaño lógico agregado observado: 37 GiB.
- Cada snapshot medía aproximadamente 77.6 MB.
- El heartbeat observado por el watchdog tenía más de 6,800 segundos de edad.
- La recuperación se declaraba exitosa aunque no arrancaba workers ni verificaba
  un heartbeat nuevo mediante callback; usaba el valor por defecto `True`.

Acción ejecutada:

1. Se detuvo temporalmente el watchdog con systemd.
2. Se envió `SIGTERM` únicamente al PID huérfano previamente identificado.
3. Se reinició `triade.service`.
4. Se arrancó de nuevo el watchdog.
5. Se verificaron un único listener en 8010, heartbeat nuevo y health `healthy`.

No se borraron snapshots. El código incorpora además un cooldown persistido para
impedir una nueva tormenta de snapshots aunque el proceso watchdog se reinicie.

## Actividad autónoma real en la base

`autonomous_tasks` contenía 375 filas en la muestra:

| Tipo | Estado | Cantidad | Interpretación |
|---|---:|---:|---|
| `pulse_check` | completed | 333 | Pulso/observación real, no aprendizaje |
| `system_debt_scan` | completed | 30 | Inspección, no corrección autónoma |
| `research_curriculum` | completed | 6 | Ciclo ejecutado; no prueba aprendizaje |
| `encrypted_backup` | completed | 4 | Efecto real con artefacto |
| `neuron_education_cycle` | completed | 1 | Ciclo ejecutado; resultado formativo insuficiente |
| `system_debt_scan` | observed | 1 | Observación correctamente no presentada como ejecución |

Todos los 374 `completed` tenían `result_ref` existente en la base. Ninguno
declaraba `rollback_ref`; esto es aceptable para observaciones, pero debe
revisarse para capacidades con efectos.

## Aprendizaje y neuronas: evidencia encontrada

- `neuron_education_sessions`: 8 sesiones históricas; 2 terminaron en
  `lesson_prepared` y 6 en `material_insufficient`. No hay sesiones validadas.
- `learning_evidence`: 5 `candidate_created` y 54 `no_evidence`; no hay mejora
  validada mediante baseline, aplicación y regresión.
- `autonomous_research_runs`: cero filas. No existe evidencia de investigación
  autónoma multifuente persistida en esta tabla.
- `semantic_documents`: 76 documentos, todos en estado `candidate`; cero
  documentos `stable` en esta tabla.
- `trainable_adapters`: 2 adaptadores en estado `evaluated`; no existe estado de
  serving PEFT activo.
- Neuronas: 15 registradas, 13 `stable` y 2 `experimental`. Esta etiqueta no
  demuestra por sí misma competencia o aprendizaje reciente.
- El ciclo autónomo sí volvió a progresar después de la reparación, pero la
  carga observada continúa dominada por `pulse_check`.

## Lo que hace realmente

- Mantiene un proceso API y un loop Always-On.
- Emite heartbeat y snapshots observables.
- Usa SQLite y conserva memoria entre sesiones.
- Ejecuta tareas v2 con leases, fencing token y artefactos con hashes.
- Consulta Ollama y dispone de modelos locales reales.
- Ejecuta chequeos, análisis de deuda y backups cifrados.
- Registra candidatos, actividad neuronal y estados de evaluación.
- Recupera runs interrumpidos y verifica integridad SQLite.

## Lo que todavía no hace de forma demostrada

- No investiga autónomamente de forma continua: la tabla canónica de research
  estaba vacía.
- No convierte investigación en conocimiento contrastado y validado en runs.
- No demuestra educación neuronal completa: no hay sesiones validadas.
- No demuestra mejora antes/después ni ausencia de regresiones para aprendizaje.
- No activa LoRA/PEFT en canary ni serving real.
- No corrige automáticamente la deuda detectada; `system_debt_scan` observa.
- No posee rollback registrado para tareas con efectos ya completadas.
- No tiene una prueba real de 24 horas completada.
- No tiene CI verde: permanecen 284 errores Ruff y 215 errores mypy en el último
  corte local.
- No tiene separación systemd completa para API y workers; la instalación usa
  `triade.service` más watchdog y timer de backup.
- El límite de backups autónomos requiere revisión: se observaron ejecuciones
  aproximadamente cada 30 minutos, más frecuentes que el presupuesto diario
  documentado.
- La API observada tenía `api_key_required=false`; el modo `public_guarded` no
  sustituye autenticación si el puerto se expone públicamente.

## Trabajo obligatorio restante para aprendizaje autónomo veraz

1. Hacer que `ResearchWorker` cree runs canónicos únicamente desde gaps reales,
   con mínimo de fuentes independientes y estados de procedencia.
2. Conectar resultados de research al currículo sin marcar `completed` como
   sinónimo de aprendido.
3. Exigir evaluación independiente, baseline, aplicación en runs, medición
   posterior, regresión y rollback antes de `validated`.
4. Impedir promoción neuronal estable basada únicamente en actividad interna.
5. Activar el scheduler por utilidad y presupuesto; reducir pulsos persistidos
   que no aporten transición ni evidencia.
6. Corregir el presupuesto de backups y añadir retención para recovery snapshots.
7. Completar Ruff y mypy sin ocultar fallos.
8. Ejecutar concurrencia nuevamente sobre el commit publicado.
9. Ejecutar 24 horas reales y publicar métricas; no sustituir por simulación.
10. Proteger el endpoint público con clave persistente y probar 401/200.

## Criterio honesto de autonomía

El runtime es autónomo en disponibilidad y mantenimiento básico. El aprendizaje
es todavía **candidato y no validado**. Solo podrá declararse aprendizaje
autónomo cuando aparezca repetidamente este encadenamiento auditable:

`gap → research run → fuentes independientes → candidato → lección → evaluación
independiente → aplicación → mejora contra baseline → regresión verde → rollback
probado → validación`.

En la muestra de esta auditoría no existía ningún ciclo completo con esa cadena.
