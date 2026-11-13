# Tríade Ω - Semantic Similarity Search 1.9C

## Fase

`TRIADE_SEMANTIC_SIMILARITY_SEARCH_1.9C`

## Objetivo

Permitir que Tríade consulte los documentos ya vectorizados por cercanía de significado, mediante similitud coseno, sin integrar todavía esa recuperación al ciclo cognitivo principal.

## Precondiciones

- `1.9A` creó `semantic_documents` y `semantic_embeddings`.
- `1.9B` conectó `OllamaClient.embed()` y `SemanticEmbeddingEngine` para producir vectores locales reales.

## Archivos

- `triade/memory/semantic_search.py`
- `apps/single_port_app.py`
- `tests/test_semantic_search.py`
- `tests/test_single_port_semantic.py`
- `docs/STATUS_1_9C_SEMANTIC_SIMILARITY_SEARCH.md`

## Motor de búsqueda

`SemanticSearchEngine.search()` ejecuta:

1. Normalización de la consulta.
2. Selección controlada de modelo embedding instalado.
3. Vectorización de la consulta con Ollama usando el mismo modelo seleccionado.
4. Lectura de embeddings almacenados.
5. Exclusión de vectores generados con otro modelo.
6. Exclusión de vectores con dimensiones diferentes.
7. Cálculo de similitud coseno.
8. Filtro opcional por dominio y similitud mínima.
9. Ranking descendente y entrega de resultados auditables.

## Regla de compatibilidad de vectores

La búsqueda solo compara vectores que cumplan simultáneamente:

- mismo `embedding_model` que la consulta;
- misma dimensión vectorial que la consulta.

Esto evita ordenar recuerdos usando espacios vectoriales incompatibles.

## Salida de búsqueda

La respuesta contiene:

- consulta normalizada;
- modelo embedding utilizado;
- dimensión del vector consulta;
- total de embeddings candidatos;
- candidatos compatibles;
- descartes por modelo o dimensión;
- resultados ordenados con `document_id`, `similarity`, `domain`, `content`, `source_ref` y `metadata`;
- marca explícita `runner_integration: pending_1.9D`.

## API aislada

### Endpoint

```bash
POST http://127.0.0.1:8010/api/semantic/search
```

### Payload ejemplo

```json
{
  "query": "Cómo se regula la estabilidad y continuidad interna",
  "model": "nomic-embed-text:latest",
  "limit": 5,
  "min_similarity": 0.3,
  "domain": "crystal"
}
```

## Alcance real de 1.9C

### Construido

- vectorización semántica de consultas;
- similitud coseno;
- ranking semántico;
- filtro por dominio;
- filtro por umbral mínimo;
- descarte verificable de modelos y dimensiones incompatibles;
- endpoint independiente para pruebas reales.

### Aún no construido

- `Bodega.recall()` usando resultados semánticos;
- `MemoryPacket.semantic_matches` alimentado por similitud;
- Central recibiendo recuerdos semánticos durante un run;
- política Safety para memorias semánticas no consolidadas;
- incorporación automática de episodios a la memoria vectorial.

## Validación local

Actualizar y ejecutar pruebas:

```bash
cd ~/triadees
git pull
source .venv/bin/activate
pytest

sudo systemctl daemon-reload
sudo systemctl restart triade-chat-ui
```

### Crear documentos vectorizados reales

```bash
curl -X POST http://127.0.0.1:8010/api/semantic/ingest-and-embed \
  -H "Content-Type: application/json" \
  -H "X-TRIADE-API-Key: hope0102" \
  -d '{"content":"El Cristal Morfológico regula ética, estabilidad y continuidad contextual entre runs.","domain":"crystal","source_type":"manual-test","source_ref":"validacion-1.9C-crystal","metadata":{"phase":"1.9C"},"model":"nomic-embed-text:latest"}'

curl -X POST http://127.0.0.1:8010/api/semantic/ingest-and-embed \
  -H "Content-Type: application/json" \
  -H "X-TRIADE-API-Key: hope0102" \
  -d '{"content":"La Bodega conserva documentos, vectores y recuerdos persistentes en SQLite.","domain":"memory","source_type":"manual-test","source_ref":"validacion-1.9C-memory","metadata":{"phase":"1.9C"},"model":"nomic-embed-text:latest"}'
```

### Buscar por significado

```bash
curl -X POST http://127.0.0.1:8010/api/semantic/search \
  -H "Content-Type: application/json" \
  -H "X-TRIADE-API-Key: hope0102" \
  -d '{"query":"órgano que controla estabilidad y evolución entre ejecuciones","model":"nomic-embed-text:latest","limit":5,"min_similarity":0.0}'
```

## Resultado esperado

La búsqueda debe retornar `status: ok`, usar `nomic-embed-text:latest` y ordenar en posición alta el documento del Cristal aunque la consulta no repita exactamente sus palabras.

## Estado

Código subido a `main`. Pendiente de validación local del usuario.

## Siguiente microfase

`TRIADE_SEMANTIC_RECALL_INTEGRATION_1.9D`

Objetivo:

- inyectar matches semánticos validados dentro de `MemoryPacket`;
- conectar `Bodega.recall()` con memoria semántica;
- dejar evidencia de qué memorias influyeron en cada run;
- aplicar umbrales y controles para no contaminar la respuesta con recuerdos débiles.