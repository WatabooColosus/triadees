# Learning Evidence Bridge · Tríade Ω

La Fase 2 conecta `LearningPipeline` con Measurement Core.

## Regla central

Un candidato no puede pasar a `validated_in_runs` ni consolidarse como memoria estable solo por acumular usos o recibir scores altos. Debe demostrar una mejora reproducible frente a un baseline compatible.

## Flujo

```text
candidato verified
→ hipótesis de mejora
→ baseline
→ intervención/candidato
→ evaluación candidate
→ comparación
→ improved | neutral | regressed | invalid
→ gate de promoción
```

## Política

- `improved`: puede continuar si también cumple fuente, riesgo, usos y outcome score;
- `neutral`: permanece `verified`;
- `regressed`: bloqueado;
- `invalid`: bloqueado;
- ausencia de evidencia: bloqueado;
- cualquier regresión crítica: bloqueado.

## Persistencia

La tabla `learning_evidence` conserva:

- candidato;
- hipótesis;
- capacidad;
- subject evaluado;
- baseline completo;
- candidate evaluation completa;
- comparación;
- decisión;
- regresiones críticas;
- referencia al artefacto.

## Orden de validación

La consolidación mantiene el orden de gates existente:

1. estado del candidato;
2. fuente trazable;
3. riesgo permitido;
4. usos mínimos;
5. outcome score mínimo;
6. evidencia Measurement Core con decisión `improved`;
7. aprobación humana o trust suficiente.

Esto preserva diagnósticos claros y evita que la ausencia de evidencia oculte errores previos de estado, fuente o score.

## Compatibilidad de pruebas

Las suites heredadas que esperan promoción deben adjuntar evidencia `improved`. Los casos sin evidencia deben comprobar que el candidato permanece `verified`, incluso si ya alcanzó tres usos y un promedio suficiente.

Las pruebas de autoconsolidación por trust y las revisiones estables de workers también deben pasar por el mismo bridge. El trust autoriza la decisión final, pero no sustituye la demostración de mejora.

Los escenarios E2E neuronales siguen la misma regla: tres usos y un promedio suficiente solo habilitan la promoción cuando la hipótesis tiene baseline, evaluación posterior y comparación `improved` asociada al mismo candidato.

## Garantías

- no modifica `identity_core`;
- no habilita shell ni red;
- no consolida memoria por sí sola;
- no reemplaza las reglas de fuente, riesgo, modelo, trust o usos mínimos;
- añade una condición necesaria, no una vía alternativa de promoción.
