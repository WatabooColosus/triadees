# Deuda técnica vigente · Tríade Ω

Corte: 2026-07-29. Esta es la lista canónica de deuda abierta. Los reportes de
versiones anteriores son históricos.

## P0 · Continuidad y recuperación de memoria

- SQLite persiste episodios y memoria semántica, pero guardar no garantiza recordar.
- Falta extracción general de hechos, preferencias, correcciones y relaciones sin
  programar respuestas especiales.
- Falta identidad de usuario autenticada para aislar memoria en una web pública.
- Backup cifrado y prueba de restauración ya existen; falta configurar
  `TRIADE_BACKUP_KEY`, retención y ejecutar simulacros periódicos en producción.
- La promoción estable debe seguir exigiendo baseline, evidencia y reversibilidad.

## P0 · Veracidad de ejecución

- Central ya no usa `_simulate_step`: un paso sin ejecutor gobernado queda `blocked`,
  no consume presupuesto inventado y no puede cerrar como completado.
- Las rutinas autónomas legacy de mejora, creación/formación/verificación neuronal,
  documentación e investigación quedaron en cuarentena lógica (`blocked`) hasta que
  se conecten a sus pipelines gobernados. No crean artefactos ni aprendizaje falso.
- La rutina legacy de aprendizaje solo observa el número de nodos causales: no infiere
  causalidad por proximidad y no comprime memoria automáticamente.
- Pendiente: reemplazar esas rutas legacy por adaptadores explícitos a tareas con lease,
  evidencia, baseline, evaluación independiente y rollback.

## P0 · Operación pública y seguridad

- El modo público sin API key bloquea administración, pero no sustituye autenticación,
  cuotas, separación multiusuario ni protección antiabuso de producción.
- La URL pública depende del ciclo de vida del Cloudspace.
- Faltan dominio/ingress persistente, estrategia de secretos, backups y recuperación.

## P1 · Always-On y scheduler adaptativo

- `AdaptiveScheduler` separa ritmos y el runtime dispone de heartbeat, watchdog,
  leases y `ResourceLedger`; falta completar la atribución real de GPU, red, CPU y
  almacenamiento para todos los workers legacy.
- WorkerLoop conserva el productor legacy por compatibilidad, pero migra cada tarea
  a `autonomous_tasks`, exige lease v2 antes de ejecutar y cierra o reintenta allí.
  Falta retirar la tabla legacy después de una ventana productiva sin regresiones.
- El watchdog y la recuperación existen; falta una prueba prolongada con fallos reales
  de proceso, DB, Ollama y disco en el host de despliegue.
- Existe deduplicación textual/Jaccard y novedad básica; sigue pendiente usar embeddings
  calibrados y medir utilidad causal, presión térmica y recursos.

## P1 · Memoria emocional longitudinal

- Hipotálamo interpreta cada turno y produce PV-7, pero no conserva un estado
  emocional agregado y aislado por sesión.
- PV-7 ejecutable usa `[0,1]`; cualquier formulación bipolar pertenece a la teoría.

## P1 · Aprendizaje autónomo verificable

- El runtime crea, evalúa y marca candidatos como `internally_checked`; este estado no
  afirma verdad independiente y no toda conversación produce
  conocimiento útil ni debe hacerlo.
- Se eliminó el score 0.80 automático y se exige evidencia de run; falta convertir
  fallos de coherencia, correcciones y repetición en evaluaciones de
  mejora reproducibles, no solo más candidatos.
- La adquisición usa catálogo, resuelve el binario Ollama y persiste intentos, tamaños
  esperados y digest de recibo. Un timeout ahora cierra el intento original en vez de
  dejarlo `running` y duplicarlo. Verificar blobs completos sigue pendiente.
- Cada lección con material suficiente declara ahora una hipótesis pendiente en
  `learning_evidence`. No se puede afirmar aprendizaje consolidado hasta registrar
  evaluación independiente, aplicación, mejora contra baseline y ausencia de regresión.

## P1 · Instalación y LoRA gobernados

- Installer Worker crea un venv por objetivo, requiere aprobación, registra `pip
  freeze` y nunca activa en producción automáticamente. Falta una política de hashes
  obligatorios para cada wheel y cuarentena automática del venv fallido.
- LoRA real tiene split, deduplicación, filtro de secretos, OOD, prueba de olvido,
  firma opcional, presupuestos y cola. Falta un backend de serving que cargue PEFT en
  canary con tráfico real; hasta entonces el estado máximo es `trained_pending_canary`.

## P1 · Orquestación multi-modelo

- Hay router y asignaciones por rol, pero el Runner principal no despacha N modelos
  dinámicamente por subtarea/pensamiento.
- Faltan suites A/B por rol, métricas de calidad/latencia y política de descarga o
  descarga de GPU basada en recursos.
- `triade-omega` deriva de Qwen2.5 mediante Modelfile; no es entrenamiento fundacional propio.

## P1 · Federación real

- Existen contratos, firma, registro, Edge y Bodega Global federada.
- En el corte auditado no hay nodos remotos activos sostenidos.
- Faltan identidad persistente, reputación, revocación, expiración, cuarentena y
  pruebas prolongadas entre servidores/dispositivos reales.
- Android no aporta inferencia LLM real sin backend nativo y modelo instalado.

## P2 · Modularidad y mantenibilidad

- Runner delega preflight/investigación en `runner_preflight.py`; Bodega delega
  esquema/conexión/migraciones en `bodega_storage.py`; backup, LoRA y serving viven
  en rutas de gobernanza separadas. Aún conviene continuar reduciendo `api.py` por
  dominios, pero ya no concentra estas operaciones críticas.
- Se retiraron `api_app.py`, `chat_ui_app.py`, `chat_ui_router_app.py` y
  `ui_html.py`. Las dos URLs UI antiguas son redirecciones sin wrapper HTML.
- Los contratos mezclan dataclasses y Pydantic.
- Falta normalizar métricas históricas, latencias y causas de fallback por componente.
- La ruta canónica es `runs/`; los scripts y defaults internos ya fueron migrados.
- Ruff (reglas CI E/F/W) y `compileall` están verdes en el corte actual. Mypy global
  aún reporta 160 errores y no debe presentarse como verde; se requiere una campaña
  incremental por fronteras (DB, contratos, workers y seguridad).

## P2 · Serving y continuidad operativa cerrados

- `PeftCanaryServer` verifica hashes, carga PEFT de forma lazy en CUDA/CPU, registra
  generaciones canary, exige canary exitoso y aprobación nominal antes de activar,
  y conserva rollback. No se asigna tráfico automáticamente.
- `TRIADE_BACKUP_KEY` vive fuera de Git en `/etc/triade/triade.env` con modo 0600.
  WorkerLoop crea, verifica y aplica retención diaria/semanal a backups cifrados.
- La suite completa se ejecuta desde un cwd aislado y no escribe en la DB/runs de
  producción.

## P2 · Capacidades pendientes

- `gemma3:4b` permite comprensión visual compatible, no generación de imágenes.
- Falta un motor generativo visual separado y su evaluación de seguridad/recursos.
- Tríade OS es un plano de control sobre Linux; no tiene kernel, drivers ni aislamiento
  de procesos propio.

## Deuda resuelta que no debe reabrirse como pendiente

- SQLite, esquema y artefactos auditables por run existen.
- React SPA single-port, tests, Safety, QualiaBus, Ollama y Model Router existen.
- Central, Hipotálamo, Bodega, Cristal, Creadora y Formativa tienen implementación.
- `identity_core` está protegido y la memoria candidata no influye como verdad estable.
- Las operaciones seguras de archivos publican ahora en el bus operacional real y
  fallan explícitamente si no pueden conservar la auditoría; el rollback usa el
  manifiesto de backup correcto.

## Criterio para cerrar deuda

Una deuda solo se considera cerrada con código, pruebas, evidencia runtime,
documentación actualizada y una ruta de reversión. Actividad, número de ciclos o
cantidad de neuronas no sustituyen mejora demostrada.
