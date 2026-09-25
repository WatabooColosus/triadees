# Panel, workers y publicación de tareas en Windows

Se contrastó el panel adjunto con código y observaciones de solo lectura del 2026-09-21. Rama main, HEAD 9c1fd1187760e42335f58dbfa0bbe153fd52fc01; referencias actualizadas, diferencia con origin/main 0/0. Se preservaron cambios previos; no se modificaron manualmente colas, resultados, locks ni claves.

## Hallazgos

- A las 21:30:43 UTC la API respondía, el metabolismo avanzaba, pero no había un nuevo worker run. Existían reservas del proceso anterior; a las 21:37:46 quedaba `pulse_check` hasta 21:39:07 UTC. No se forzó su vencimiento.
- RAM disponible medida 0,36 GB. El governor exige 2 GB disponibles para salir de cooldown. Que Ollama responda no habilita por sí solo aprendizaje, consolidación ni ejecución pesada.
- `service_supervision.py` infería supervisión y autoarranque a partir de la mera existencia de la tarea `TriadeOmega`. No verificaba su habilitación, trigger ni pertenencia del proceso. La API de esta sesión fue iniciada por un supervisor manual; existencia de una tarea no demuestra esa relación.
- El 100/100 de deuda técnica corresponde a comprobaciones del repositorio (build, rutas, módulos), no a disponibilidad ni aprendizaje. Se aclaró ese alcance en la tarjeta.
- Último evento `mission_planner.backup_key_missing`: **20:43:26 UTC**, anterior al reinicio de 21:23. El archivo de clave existe y hay una tarea de backup marcada completada por recuperación a 21:23:37. No se leyó ni mostró la clave; esto tampoco certifica una restauración del backup.

## Reparaciones

1. Supervisión Windows consulta XML de tareas para comprobar habilitación y trigger de arranque. No certifica que el proceso pertenezca al programador de tareas sin evidencia de esa relación; devuelve `service_managed=null`. La UI distingue «sin verificar» de «no».
2. La reserva vigente conserva su motivo y vencimiento desde el almacén de tareas hasta el estado del worker. La tarjeta muestra `motivo_espera` y `reserva_hasta`, en vez de presentar una salida por reserva como ciclo completado. Se corrigió además la carrera que podía sobrescribir el estado final de un hilo que ya había terminado.
3. **Fallo funcional reproducido:** `test_uncertain_with_valid_artifact_completes` fallaba con PermissionError en `os.open(directorio, os.O_RDONLY)`, después de publicar el directorio. La publicación canónica aplicaba una sincronización POSIX incompatible con Windows. Se usa ahora `MoveFileExW` con `MOVEFILE_WRITE_THROUGH`, sin reemplazar evidencia existente, y se verifica que staging y destino tengan el mismo directorio padre. La implementación sigue [Moving Directories de Microsoft](https://learn.microsoft.com/en-us/windows/win32/fileio/moving-directories). Los archivos ya se sincronizaban individualmente. La ruta POSIX conserva su fsync de directorio.
4. El panel identifica el último error como registrado y aclara que la disponibilidad de modelos puede estar limitada por los recursos.

No se bajaron umbrales de RAM ni de aprobación, ni se activó aprendizaje para fabricar actividad. El fallo reproducido explica una vía real para dejar resultados inciertos; no demuestra que todos los registros históricos tengan esa causa.

## Validación

- Inicialmente: 22 pruebas de supervisión/workers pasaron; ampliación encontró 1 fallo preexistente de Windows y 36 pruebas correctas.
- Tras reparar publicación: **68 pruebas correctas** de publicación canónica, recuperación, leases, supervisión y ciclo de workers. Ruff sin errores en los archivos revisados.
- `npm.cmd --prefix frontend run build` completado. GET `/` sirvió `/assets/index-4i7t8JGd.js`: el frontend actualizado está publicado.
- Cambios Python pendientes de la recarga solicitada. No se atribuye al proceso existente el comportamiento probado en procesos nuevos.
- A las **21:40:10 UTC**, observación posterior al vencimiento: nuevo worker run iniciado a **21:39:51 UTC**, estado running, `system_debt_scan` en curso con actualización a 21:40:08. El watchdog recuperó el arranque sin intervención manual en la cola. Esto no certifica todavía finalización sostenida de tareas ni aplicación de la nueva publicación Windows. Evidencia: `artifacts/audit-20260921/panel-after-lease-expiry.json`.

Diff de código: `artifacts/audit-20260921/panel-recovery.patch`; incluye una línea anterior de integración del sandbox en worker_loop. El build reemplaza el bundle versionado de frontend/dist y actualiza index.html.

Persisten la presión de RAM, la búsqueda web con respaldo, y la falta de evidencia calibrada para certificar estabilidad automática al 96%. La autorización de instalar herramientas o la ausencia de firmas pendientes no elimina esos límites técnicos.
