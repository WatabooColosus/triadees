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

## Cuarentena

Las decisiones `fail` e `invalid` activan una cuarentena persistente para el candidato. La cuarentena conserva reporte, motivo y fechas; su liberación es explícita y no borra el historial.

## Rollback lógico

El gate registra el último `EvaluationRun` estable por capacidad. `rollback_target()` devuelve el subject, evaluación, suite y versión a restaurar. Esta primera implementación identifica el objetivo; la aplicación efectiva del rollback se integrará posteriormente con `LearningPipeline`.

## Seguridad inicial

- No modifica `identity_core`.
- No habilita shell ni red.
- No elimina evidencia ni historial.
- Una regresión crítica nunca se convierte en advertencia.
- `warn` no equivale a aprobación.
- Las suites incompatibles producen `invalid`.
