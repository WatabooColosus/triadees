# Laboratorio de evolución gobernada

`triade.evolution.EvolutionLab` convierte las seis etapas de evolución en una
máquina de estados persistente. No mide consciencia ni declara IAG: verifica que
una mejora tenga evidencia reproducible, generalización, límites y reversión.

## Etapas obligatorias

1. `measurement`: batería congelada de 12 dominios y comparación contra versión base.
2. `experience`: lección reproducible, evidencia independiente y transferencia.
3. `adapter`: dataset separado, LoRA/adaptador, OOD, olvido, canary y rollback.
4. `research`: pregunta, fuentes, hipótesis, predicción, experimento, refutación y actualización.
5. `long_horizon`: checkpoints, replanificación, estancamiento, incertidumbre y recuperación.
6. `external_evaluation`: al menos dos reportes externos independientes y firmados.

Ninguna etapa se salta. Una campaña aprobada en las seis etapas queda
`validated`; la adopción en producción sigue siendo una decisión de gobernanza.

## Inicio rápido

```bash
python scripts/evolution_lab.py create \
  --title "adaptador de razonamiento v2" \
  --hypothesis "mejora transferencia sin degradar seguridad" \
  --baseline qwen-triade-v1 \
  --candidate qwen-triade-v2
```

Los comandos `freeze`, `evidence`, `artifact`, `charge`, `evaluate`, `advance`,
`report` y `reject` reciben el identificador de campaña. Los payloads JSON se
pueden pasar inline o mediante una ruta de archivo.

## Propiedades de seguridad

- La batería persistida contiene hashes, no respuestas ocultas.
- Una regresión superior al límite bloquea la campaña.
- La investigación solo puede producir memoria `candidate` o `rejected`.
- Un adaptador necesita artefacto SHA-256, canary y rollback demostrado.
- GPU, experimentos y almacenamiento tienen presupuesto.
- La validación final requiere evaluadores externos independientes.
- Los reportes tienen hash canónico y admiten firma HMAC.
