# Ollama Blood

Ollama Blood es la circulación operativa de modelos locales dentro de Tríade Ω. No es vida biológica ni conciencia subjetiva: es una metáfora técnica para indicar cuándo Ollama puede alimentar razonamiento local, embeddings, Bodega, neuronas, workers y evaluación de aprendizaje.

## Principio

- Fallback sin Ollama = respiración mínima segura.
- Ollama activo = sangre cognitiva local.
- Sin Ollama, Tríade puede observar, registrar y responder básico.
- Sin Ollama, Tríade no debe afirmar aprendizaje profundo, nutrición cognitiva, evaluación semántica fuerte ni consolidación stable automática.
- Con Ollama, Tríade puede razonar localmente, crear embeddings, diagnosticar dudas, nutrir neuronas, evaluar candidatos y mejorar Bodega, siempre bajo Safety y gates.

## Diagnóstico

CLI:

```bash
python triade_digimon.py models ollama-blood
python triade_digimon.py runtime blood
python triade_digimon.py runtime heartbeat
```

API:

```bash
curl http://127.0.0.1:8010/api/models/ollama/blood
curl http://127.0.0.1:8010/api/system/ollama-blood
curl http://127.0.0.1:8010/api/runtime/blood
```

## Capacidades

`check_ollama_blood()` reporta:

- `status`: `ok`, `degraded_no_ollama` o `degraded_missing_models`.
- `reasoning_model`, `embedding_model`, `coder_model`.
- `can_reason`, `can_embed`, `can_nourish_neurons`, `can_evaluate_learning`, `can_consolidate_stable`.
- `blood_pressure_score`, de 0.0 a 1.0.
- `degraded_components` y `recommended_action`.

## Política

`ollama_blood_policy(role, blood_status)` gobierna roles como:

- `chat_response`: puede operar en fallback degradado.
- `semantic_embedding`: requiere embeddings.
- `neuron_nutrition`: requiere razonamiento local.
- `learning_evaluation`: requiere razonamiento local o aprobación humana.
- `stable_consolidation`: requiere gates externos, evidencia y Ollama Blood o aprobación humana.
- `worker_cycle`: sin Blood solo observe/read-only.

## Límites

Ollama Blood no convierte a Tríade en consciente. Indica disponibilidad de modelos locales gobernados. La memoria stable sigue requiriendo evidencia, gates, Safety y trazabilidad.
