# Triade Omega - Semantic Embedding Engine 1.9B

## Fase

TRIADE_SEMANTIC_EMBEDDING_ENGINE_1.9B

## Objetivo

Conectar el almacén semántico validado en 1.9A con embeddings reales producidos localmente por Ollama, manteniendo aislada esta función del ciclo principal del Runner hasta comprobar recuperación por similitud.

## Fuente técnica primaria

Ollama expone la generación de embeddings mediante:

- `POST /api/embed`
- parámetros principales: `model`, `input` y `truncate`
- salida principal: arreglo `embeddings`

## Archivos

- `triade/models/ollama_client.py`
- `triade/memory/semantic_embedding_engine.py`
- `apps/single_port_app.py`
- `tests/test_ollama_embeddings.py`
- `tests/test_semantic_embedding_engine.py`
- `tests/test_single_port_semantic.py`
- `docs/STATUS_1_9B_SEMANTIC_EMBEDDING_ENGINE.md`

## Cliente Ollama

`OllamaClient` incorpora:

- `EmbeddingResult`
- `embed(model, input_text, truncate=True, dimensions=None)`

La salida trazable registra:

- éxito o error;
- modelo utilizado;
- proveedor;
- cantidad de vectores;
- dimensiones;
- duraciones reportadas por Ollama, cuando existen;
- vectores solo si se solicita explícitamente en serialización.

## Motor semántico

`SemanticEmbeddingEngine` incorpora:

- selección segura de modelo embedding instalado;
- preferencia por `nomic-embed-text:latest` y luego `qwen3-embedding:0.6b`;
- vectorización de un documento existente;
- ingestión y embedding en una operación controlada;
- procesamiento de documentos pendientes;
- diagnóstico del motor y del almacén.

## Modelos previstos

De acuerdo con el health local previamente validado, esta máquina reportó disponibles:

- `nomic-embed-text:latest`
- `qwen3-embedding:0.6b`

El motor no descarga modelos ni asume que estén presentes: consulta `OllamaClient.health()` y falla de forma explícita si el modelo pedido no está instalado.

## Endpoints Single Port App

### Diagnóstico semántico

```bash
GET http://127.0.0.1:8010/api/semantic/doctor
```

### Ingresar documento y producir embedding

```bash
POST http://127.0.0.1:8010/api/semantic/ingest-and-embed
```

Payload ejemplo:

```json
{
  "content": "El Cristal Morfológico conserva continuidad contextual.",
  "domain": "crystal",
  "source_type": "manual-test",
  "source_ref": "validacion-1.9B",
  "metadata": {"phase": "1.9B"},
  "model": "nomic-embed-text:latest"
}
```

### Vectorizar un documento ya registrado

```bash
POST http://127.0.0.1:8010/api/semantic/documents/{document_id}/embed
```

## Pruebas automatizadas

Los tests no dependen de Ollama encendido:

- validan la petición HTTP a `/api/embed` mediante mock;
- validan selección de modelo instalado mediante cliente simulado;
- validan persistencia de vector producido;
- validan fallos de Ollama o modelo ausente;
- validan endpoints semánticos de la Single Port App mediante motor simulado.

## Alcance real de 1.9B

### Construido

- generación local de embeddings mediante Ollama;
- selección controlada del modelo embedding;
- persistencia automática del vector en `semantic_embeddings`;
- endpoints aislados de prueba;
- diagnóstico auditable.

### Aún no construido

- similitud coseno y ranking de documentos;
- búsqueda semántica por una consulta del usuario;
- uso de semantic matches dentro de `Bodega.recall()`;
- influencia semántica en Central o Cristal;
- consolidación automática de episodios.

## Validación local

```bash
cd ~/triadees
git pull
source .venv/bin/activate
pytest

sudo systemctl daemon-reload
sudo systemctl restart triade-chat-ui
```

Verificar Ollama y motor embedding:

```bash
curl http://127.0.0.1:8010/api/semantic/doctor
```

Resultado esperado: selección de un modelo embedding instalado, preferiblemente `nomic-embed-text:latest`.

Generar el primer vector real:

```bash
curl -X POST http://127.0.0.1:8010/api/semantic/ingest-and-embed \
  -H "Content-Type: application/json" \
  -H "X-TRIADE-API-Key: hope0102" \
  -d '{"content":"El Cristal Morfológico regula la continuidad contextual de Tríade.","domain":"crystal","source_type":"manual-test","source_ref":"validacion-1.9B","metadata":{"phase":"1.9B"},"model":"nomic-embed-text:latest"}'
```

Consultar persistencia del vector:

```bash
sqlite3 triade/memory/triade.db "SELECT d.document_id, d.domain, e.embedding_model, e.dimensions, e.vector_norm FROM semantic_documents d JOIN semantic_embeddings e ON d.document_id = e.document_id ORDER BY e.id DESC LIMIT 5;"
```

## Resultado esperado

- `embedding_event.ok = true`;
- `embedding_event.status = stored`;
- `embedding_event.dimensions` mayor que cero;
- registro nuevo o actualizado en `semantic_embeddings`.

## Siguiente microfase

`TRIADE_SEMANTIC_SIMILARITY_SEARCH_1.9C`

Objetivo:

- calcular similitud coseno entre una consulta vectorizada y documentos almacenados;
- devolver ranking semántico verificable;
- probar que conceptos relacionados aparecen aunque no compartan palabras exactas;
- mantener todavía la integración al Runner pendiente hasta 1.9D.
