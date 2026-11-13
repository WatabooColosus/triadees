# LoRA real, continuidad e investigación autónoma

Tríade conserva la identidad operativa y la Bodega SQLite entre sesiones y reinicios. La ventana de contexto no es la memoria: los datos duraderos viven en la Bodega y se recuperan selectivamente. Una compuerta posterior a la generación corrige afirmaciones falsas de memoria efímera.

Ante una pregunta factual para la que la memoria autorizada no ofrece evidencia suficiente, el motor de investigación puede consultar la web con cuota diaria. Filtra consultas sensibles, conserva URL, extracto, hash y contradicciones, y crea únicamente candidatos en `learning_queue`; una fuente web nunca entra directamente en memoria estable.

El entrenador de `triade/training/lora_trainer.py` usa Transformers, PEFT y CUDA de verdad. Filtra secretos, deduplica, congela un split determinista, entrena solo parámetros LoRA, mide validación, fuera de distribución y olvido, guarda `adapter_model.safetensors`, manifiesto con hashes y rollback. Nunca activa automáticamente un adaptador recién entrenado.

Entrenamiento gobernado:

```bash
python scripts/train_lora.py data/lora/triade_continuity_smoke.jsonl \
  --ood data/lora/triade_ood_smoke.jsonl \
  --forgetting data/lora/triade_forgetting_smoke.jsonl \
  --output artifacts/adapters/triade-continuity-canary
```

Canary de carga reversible:

```bash
python scripts/verify_lora_adapter.py artifacts/adapters/triade-continuity-canary
```

Para un adaptador de producción, el modelo base debe coincidir exactamente con el backend que lo servirá. El smoke de 0.5B prueba la ruta técnica; no constituye evidencia de generalidad ni autoriza sustituir el modelo estable de 3B.
