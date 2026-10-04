# Stack OSS low-resource

La arquitectura de Tríade permanece por encima del motor. `Central`,
`Hypothalamus` y `Bodega` hablan con el contrato de proveedor; los modelos y
servidores externos no son neuronas.

El camino mínimo usa Python, SQLite y un único proveedor generativo (`ollama`
o `llama.cpp`). CPU es el fallback; la GPU es opcional. Embeddings son bajo
demanda. PyTorch, Transformers, PEFT, Accelerate y Redis son extras.

Selecciona el proveedor con `TRIADE_MODEL_PROVIDER`. `llama.cpp` usa
`TRIADE_LLAMA_CPP_URL` para un servidor HTTP compatible o
`TRIADE_LLAMA_CPP_MODEL` + `TRIADE_LLAMA_CPP_BIN` para un proceso local.

Para 8 GB se recomienda un GGUF pequeño, contexto de 2048 tokens y
concurrencia 1. El Resource Governor sigue siendo la autoridad que degrada o
bloquea trabajo.

Ejecuta `python scripts/benchmark_low_resource_stack.py` para obtener hardware,
proveedor, modelo, RSS, latencia, tokens y errores observados.
