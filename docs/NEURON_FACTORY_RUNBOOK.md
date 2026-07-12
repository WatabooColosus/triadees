# Neuron Factory · Runbook

## Flujo

1. Registrar y validar `NeuronSpecification`.
2. Pasar a `specified`.
3. Crear candidato aislado.
4. Ejecutar configuración declarativa.
5. Registrar baseline, candidato y comparación.
6. Exigir mejora y Regression Gate en `pass`.
7. Promover y registrar capacidades demostradas.
8. Exportar el ciclo completo con SHA-256.

## Cuarentena y rollback

Poner en cuarentena ante regresión, evidencia inconsistente, dependencia bloqueada o incumplimiento de contrato. El rollback exige una razón, bloquea las capacidades aportadas, mueve la especificación a `quarantined`, marca el candidato como `rolled_back` y conserva toda la evidencia.

## Auditoría mínima

La exportación incluye especificación, historial, candidato, ejecuciones, evidencia, capacidades y estado final. Nunca reactivar una capacidad sin una nueva evaluación completa.
