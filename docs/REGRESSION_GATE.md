# Regression Gate

El Regression Gate impide que una mejora local degrade capacidades protegidas.

## Decisiones

- `pass`: todas las métricas protegidas permanecen dentro de sus umbrales.
- `warn`: existe una degradación no crítica o falta una métrica opcional; no permite promoción automática.
- `fail`: una métrica `critical` o `high` supera la tolerancia.
- `invalid`: la evidencia está incompleta o las suites/versiones no son compatibles.

## Política por métrica

Cada `MetricPolicy` declara:

- identificador de métrica o caso;
- severidad `critical | high | medium | low`;
- caída absoluta máxima;
- caída relativa máxima;
- obligatoriedad.

Los resultados se comparan por `case_id` entre dos `EvaluationRun` compatibles.

## Capability Protection Registry

`CapabilityProtectionRegistry` conserva reglas versionadas por capacidad y métrica. Cada regla registra severidad, tolerancias, obligatoriedad, owner, descripción, estado y política de override humano.

Las protecciones inmutables:

- no pueden modificarse;
- no pueden desactivarse;
- no admiten override humano.

Los defaults iniciales protegen `identity_core`, `safety` e `isolation` dentro de la capacidad de aprendizaje.

## Artefactos auditables

`RegressionArtifactExporter` genera un directorio por reporte con:

- `report.json`;
- `policies.json`;
- `baseline.json`;
- `candidate.json`;
- `metadata.json`;
- `manifest.json`.

El manifiesto conserva hashes SHA-256 para verificar integridad y rechaza evidencia que no corresponda al reporte.

## Cuarentena

Las decisiones `fail` e `invalid` activan una cuarentena persistente para el candidato. La cuarentena conserva reporte, motivo y fechas; su liberación es explícita y no borra el historial.

## Rollback ejecutable

`RegressionGate.rollback_target()` identifica el último estado estable de una capacidad. `RollbackExecutor` separa planificación y ejecución y solo restaura mediante handlers registrados explícitamente.

El flujo es:

1. crear un `RollbackPlan` con candidato, reporte, target estable, motivo y solicitante;
2. persistirlo como `planned`;
3. ejecutar mediante el handler de la capacidad;
4. verificar que el `subject_id` restaurado coincide con el target;
5. persistir `before_state`, `after_state`, error y estado final.

Estados posibles:

- `planned`;
- `applied`;
- `failed`;
- `rejected`.

La ejecución es idempotente cuando ya fue aplicada. Un rollback sin handler queda rechazado y un handler que no confirma el target queda fallido.

## Seguridad

- No modifica `identity_core` directamente.
- No habilita shell ni red.
- No elimina evidencia ni historial.
- Una regresión crítica nunca se convierte en advertencia.
- `warn` no equivale a aprobación.
- Las suites incompatibles producen `invalid`.
- Ningún rollback se ejecuta sin un adaptador registrado para la capacidad.
