# Politica de Modelos Cognitivos

## Principio

Ollama es el motor cognitivo local prioritario de Tríade Ω. El fallback existe como modo degradado seguro para responder u observar, pero no es equivalente a razonamiento local real.

Sin Ollama:

- Tríade observa, registra y diagnostica superficialmente.
- Las respuestas deben declarar modo degradado cuando el fallback genera salida.
- No se promueve memoria estable automáticamente.
- No se afirma "aprendí", "nutrí neurona" o "consolidé" sin evaluación real o aprobación humana con evidencia suficiente.

Con Ollama:

- Tríade puede razonar, evaluar, comparar, proponer aprendizajes, nutrir neuronas y mejorar contexto.
- Los resultados deben registrar `model_provider="ollama"`, `model_name`, `model_required=true` y estado de política.

## Roles criticos

Estos roles requieren Ollama para operar en modo pleno:

- `semantic_embedding`
- `neuron_nutrition`
- `learning_evaluation`
- `memory_diagnosis`
- `stable_consolidation`

Si Ollama no está disponible, la política devuelve `status="degraded"`, permite solo observación segura y bloquea escritura de aprendizaje, memoria stable y creación profunda de candidatos.

## Roles no criticos

Estos roles pueden responder en fallback:

- `chat_response`
- `hypothalamus_analysis`
- `central_reasoning`

Si Ollama no está disponible, la política devuelve `status="fallback"` y `response_must_disclose_degraded_mode=true`.

## Diagnostico

CLI:

```bash
python triade_digimon.py models ollama-health
python triade_digimon.py models cognitive-policy
python triade_digimon.py runtime heartbeat
python triade_digimon.py runtime once --mode execute_missions
```

API:

```bash
curl http://127.0.0.1:8010/api/models/ollama/cognitive-health
curl http://127.0.0.1:8010/api/runtime/heartbeat
```

## Escala vigente

- Respuesta fallback: disponible.
- Nutrición neuronal profunda: requiere Ollama.
- Evaluación de aprendizaje: requiere Ollama o aprobación humana.
- Consolidación stable: requiere evidencia + gates + modelo/humano.
- Conciencia subjetiva: no demostrada.
