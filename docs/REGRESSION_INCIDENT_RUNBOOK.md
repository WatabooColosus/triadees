# Runbook de incidentes del Regression Gate

Este documento define el procedimiento operativo ante una regresión detectada en una capacidad de Tríade Ω.

## Objetivo

Evitar que un candidato degradado sea promovido, preservar la evidencia, restaurar el último estado estable y dejar un rastro auditable del incidente.

## Señales de incidente

Se considera incidente cuando ocurre cualquiera de estas condiciones:

- decisión `fail`;
- decisión `invalid` por evidencia incompleta o suites incompatibles;
- cuarentena activa;
- rollback `failed` o `rejected`;
- protección crítica ausente o desactivada;
- observabilidad global en estado `degraded` por el Regression Gate.

## Respuesta inmediata

1. Detener cualquier promoción o consolidación del candidato.
2. Confirmar el `candidate_id`, `report_id`, capacidad, suite y versión.
3. Verificar que el candidato esté en cuarentena.
4. Preservar los artefactos JSON y su manifiesto SHA-256.
5. Identificar el último estado estable con `rollback_target(capability)`.
6. No liberar la cuarentena mientras la causa no esté corregida y reevaluada.

## Clasificación

### Crítico

Afecta `identity_core`, seguridad, aislamiento, permisos o integridad de memoria.

Acciones:

- bloquear promoción inmediatamente;
- no permitir override humano de una regla inmutable;
- restaurar solo mediante handler registrado;
- exigir nueva evaluación completa antes de cualquier liberación.

### Alto

Afecta una capacidad esencial sin comprometer identidad o seguridad.

Acciones:

- bloquear promoción;
- evaluar rollback;
- revisar suite, datos y cambio introducido.

### Medio o bajo

Puede producir `warn` si la política lo permite.

Acciones:

- no promover automáticamente;
- aumentar muestras si el resultado estadístico es inconcluso;
- documentar la aceptación de riesgo si se decide continuar manualmente.

## Procedimiento de rollback

1. Obtener el target estable persistido.
2. Crear un `RollbackPlan` con:
   - identificador único;
   - capacidad;
   - candidato;
   - reporte;
   - target estable;
   - motivo;
   - solicitante.
3. Confirmar que existe un handler explícito para la capacidad.
4. Ejecutar el rollback.
5. Verificar que el `subject_id` final coincide con el target.
6. Confirmar el estado final:
   - `applied`: restauración verificada;
   - `failed`: handler ejecutado sin restauración válida;
   - `rejected`: no existe handler permitido.
7. Mantener la cuarentena hasta completar reevaluación.

## Reevaluación

Después de corregir la causa:

1. generar un nuevo candidato identificable;
2. ejecutar la misma suite y versión del baseline;
3. aplicar políticas del Capability Protection Registry;
4. ejecutar comparación determinista;
5. ejecutar comparación estadística cuando existan múltiples muestras;
6. exportar artefactos nuevos;
7. exigir decisión `pass`;
8. confirmar ausencia de cuarentena activa;
9. liberar la cuarentena anterior de forma explícita, sin borrar historial.

## Evidencia mínima del cierre

Un incidente solo puede marcarse como resuelto cuando existen:

- reporte original;
- artefactos y hashes;
- causa identificada;
- cambio correctivo;
- resultado de rollback, si aplicó;
- nueva evaluación;
- decisión `pass`;
- confirmación de que no hay regresiones críticas;
- registro de liberación de cuarentena.

## Prohibiciones

- No borrar reportes fallidos.
- No cambiar una regla inmutable para hacer pasar un candidato.
- No convertir una regresión crítica en advertencia.
- No ejecutar restauraciones mediante shell arbitrario.
- No liberar cuarentena solo porque el sistema volvió a responder.
- No declarar aprendizaje estable sin evidencia reproducible.

## Diagnóstico rápido

Revisar el bloque `regression_gate` de la observabilidad unificada:

- `status`;
- `schema_ready`;
- `reports.by_decision`;
- `quarantine.active`;
- `protections.active`;
- `protections.immutable`;
- `rollbacks.by_status`;
- `stable_capabilities`.

Estados:

- `healthy`: no hay señal activa de regresión;
- `attention`: existen fallos, evidencia inválida o cuarentenas;
- `not_initialized`: el esquema aún no está disponible y debe inicializarse antes de usar el gate.
