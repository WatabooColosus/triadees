# Triade Omega - Semantic Store 1.9A

## Fase

TRIADE_SEMANTIC_MEMORY_1.9A

## Objetivo

Construir la base persistente de memoria semantica para Tríade Ω sin afirmar aun que el sistema produce embeddings o recupera conocimiento por significado.

## Estado real de N Creadora y N Formadora

Antes de iniciar esta fase se verifico en Git que existen:

- `triade/core/neuron_creator.py`: contiene `NeuronCreator` y `NeuronSpec`.
- `triade/core/neuron_trainer.py`: contiene `NeuronTrainer` y `NeuronTrainingResult`.
- `triade/core/neuron_registry.py`: persiste neuronas y evaluaciones en SQLite.

Estas neuronas existen como modulos funcionales de creación, evaluacion y persistencia. Todavia no se activan automaticamente en cada run ni orquestan aprendizaje semantico.

## Archivos de 1.9A

- `triade/memory/migrations/001_9A_semantic_memory.sql`
- `triade/memory/semantic_store.py`
- `tests/test_semantic_store.py`
- `docs/STATUS_1_9A_SEMANTIC_STORE.md`

## Nuevas tablas

### semantic_documents

Almacena unidades documentales preparadas para vectorizacion:

- document_id
- content
- normalized_content
- content_hash
- domain
- source_type
- source_ref
- metadata
- status
- timestamps

### semantic_embeddings

Almacena vectores cuando una capa de embeddings los proporcione:

- document_id
- embedding_model
- vector_json
- dimensions
- vector_norm
- status
- timestamps

## Funcionalidad construida

`SemanticMemoryStore` permite:

- inicializar tablas semanticas mediante migracion propia;
- normalizar contenido;
- guardar documentos con metadata y procedencia;
- deduplicar contenido por hash normalizado;
- persistir un vector ya generado;
- validar que el vector no sea vacio, infinito o de norma cero;
- listar documentos y embeddings;
- diagnosticar documentos pendientes de embedding.

## Lo que no existe todavia

En 1.9A no se ha construido:

- generación automática de embeddings;
- integración con el endpoint de embeddings de Ollama;
- búsqueda por similitud coseno;
- uso de semantic_matches dentro del ciclo del Runner;
- consolidación automática de episodios como conocimiento semántico estable.

## Decisión arquitectónica

La memoria semántica se inicia como módulo separado sobre la misma base SQLite. Esto reduce riesgo sobre `Bodega`, `Crystal`, `Safety` y `Runner`, ya validados en fases anteriores.

Cuando los embeddings sean verificables, Bodega podrá consumir este almacén sin cambiar el significado de la memoria existente.

## Validación local

```bash
cd ~/triadees
git pull
source .venv/bin/activate
pytest
pytest tests/test_semantic_store.py -q
```

## Resultado esperado

La suite debe validar:

- creación de tablas;
- normalización y persistencia documental;
- deduplicación por contenido;
- persistencia de vectores entregados;
- validaciones de vectores inválidos;
- diagnóstico de documentos sin embedding.

## Siguiente microfase

`TRIADE_SEMANTIC_EMBEDDING_ENGINE_1.9B`

Objetivo:

- extender `OllamaClient` con embeddings locales;
- usar un modelo instalado como `nomic-embed-text:latest` o `qwen3-embedding:0.6b`;
- producir vectores reales para `semantic_documents`;
- guardar evidencia del modelo, dimensión, error o fallback;
- no integrar todavía recall semántico al Runner hasta validar calidad en 1.9C/1.9D.
