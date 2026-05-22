# Tríade Ω - Semantic Recall Integration 1.9D

## Fase

`TRIADE_SEMANTIC_RECALL_INTEGRATION_1.9D`

## Objetivo

Integrar la búsqueda semántica validada en 1.9C dentro del ciclo cognitivo real de Tríade, de manera opcional, explícita y auditable.

A partir de esta fase, un run puede solicitar memoria vectorial y recibir recuerdos semánticos en `MemoryPacket.semantic_matches`, antes de que el Cristal regule y Central responda.

## Precondiciones validadas

- `1.9A`: almacén persistente de documentos y embeddings.
- `1.9B`: generación real de embeddings mediante Ollama.
- `1.9C`: búsqueda semántica real por similitud coseno, validada localmente con `nomic-embed-text:latest`, vectores de 768 dimensiones y ranking correcto del documento del Cristal.

## Principio de integración segura

El recall semántico queda **desactivado por defecto**.

Esto garantiza que:

- los runs normales continúen funcionando sin depender del servicio de embeddings;
- la memoria vectorial solo influya cuando se solicita expresamente;
- los errores del motor semántico no bloqueen el ciclo principal;
- cada influencia semántica quede registrada y revisable.

## Archivos

- `triade/core/contracts.py`
- `triade/core/bodega.py`
- `triade/core/runner.py`
- `apps/single_port_app.py`
- `tests/test_semantic_recall_integration.py`
- `tests/test_single_port_semantic_recall.py`
- `docs/STATUS_1_9D_SEMANTIC_RECALL_INTEGRATION.md`

## Contrato de memoria

`MemoryPacket` incorpora:

- `semantic_recall`: evidencia del proceso de recuperación vectorial.

El campo registra:

- si el recall estaba activado;
- estado del proceso (`disabled`, `ok`, `failed`, `unavailable`);
- modelo embedding usado;
- límite y umbral solicitado;
- dominio filtrado;
- cantidad de matches;
- mayor similitud encontrada;
- dimensiones de consulta y descartes, cuando aplica;
- error, cuando existe.

## Bodega

`Bodega.recall()` ahora puede recibir:

- `semantic_recall_enabled`
- `semantic_model`
- `semantic_limit`
- `semantic_min_similarity`
- `semantic_domain`

La Bodega mantiene diferenciadas dos fuentes:

- `retrieval_type=legacy_keyword`: coincidencias textuales anteriores.
- `retrieval_type=vector_similarity`: coincidencias recuperadas por embeddings.

Los matches vectoriales se colocan primero en `semantic_matches`, para que Central pueda observar los recuerdos semánticamente más relevantes cuando el modo está activo.

## Runner

`TriadeRunner.run()` acepta parámetros de recall semántico y, cuando se activa:

1. crea o reutiliza `SemanticSearchEngine` sobre la misma base SQLite;
2. solicita a Bodega la recuperación vectorial antes del Cristal;
3. entrega `MemoryPacket.semantic_matches` a Cristal y Central dentro del flujo normal;
4. registra evidencia en los artefactos del run.

## Evidencia por run

El recall semántico queda visible en:

- `memory.json`: `semantic_matches` y `semantic_recall`;
- `memory_diff.json`: bloque `semantic_recall` con matches utilizados;
- `integrity.json`: bloque `semantic_recall`;
- respuesta de `/api/run`: bloque `semantic_recall`.

## API Single Port

`POST /api/run` incorpora los parámetros:

```json
{
  "semantic_recall_enabled": true,
  "semantic_model": "nomic-embed-text:latest",
  "semantic_limit": 3,
  "semantic_min_similarity": 0.55,
  "semantic_domain": "crystal"
}
```

## Influencia real sobre la respuesta

### Con `use_ollama=false`

El recall semántico se recupera y queda auditado en los artefactos y en la respuesta JSON del run. La respuesta por plantilla no redacta contenido utilizando los matches recuperados.

### Con `use_ollama=true`

Los `semantic_matches` entran en el paquete de memoria que Central incorpora a su prompt. Esto permite que el modelo central responda considerando los recuerdos semánticos recuperados, dejando evidencia de cuáles fueron usados como contexto disponible.

## Alcance construido

- recuperación semántica opcional dentro del ciclo real;
- matches vectoriales en `MemoryPacket`;
- configuración por run y por API;
- evidencia auditable completa;
- fallo no destructivo cuando embeddings/Ollama no están disponibles;
- compatibilidad con runs normales sin memoria vectorial.

## Aún no construido

- activación automática de recall según intención;
- umbrales adaptativos por neurona/proyecto;
- validación de confiabilidad/consolidación del recuerdo antes de usarlo;
- incorporación automática de episodios recientes al almacén vectorial;
- controles Safety específicos para memorias semánticas experimentales;
- indicador UI para activar el recall desde el chat visual.

## Validación local

```bash
cd ~/triadees
git pull
source .venv/bin/activate
pytest

sudo systemctl daemon-reload
sudo systemctl restart triade-chat-ui
```

Probar un run con memoria semántica activa, reutilizando los documentos ya generados en 1.9C:

```bash
curl -X POST http://127.0.0.1:8010/api/run \
  -H "Content-Type: application/json" \
  -H "X-TRIADE-API-Key: hope0102" \
  -d '{"text":"Qué órgano regula la estabilidad y continuidad entre ejecuciones","source":"api-test-semantic-run","use_ollama":false,"semantic_recall_enabled":true,"semantic_model":"nomic-embed-text:latest","semantic_limit":3,"semantic_min_similarity":0.55,"semantic_domain":"crystal","context":{"project_id":"triade-local","active_neuron":"cristal","context_scope":"project_neuron"}}'
```

Resultado esperado:

- `semantic_recall.enabled = true`;
- `semantic_recall.status = ok`;
- `semantic_recall.matches_count >= 1`;
- al menos un match con `retrieval_type = vector_similarity`;
- match del documento del Cristal con similitud superior al umbral;
- `memory.json` del run contiene ese mismo match.

Consulta del artefacto:

```bash
RUN_ID="<run_id_devuelto>"
cat "runs/$RUN_ID/memory.json"
cat "runs/$RUN_ID/integrity.json"
```

Prueba posterior con Central-modelo activa:

```bash
curl -X POST http://127.0.0.1:8010/api/run \
  -H "Content-Type: application/json" \
  -H "X-TRIADE-API-Key: hope0102" \
  -d '{"text":"Explica qué órgano de Tríade regula continuidad y estabilidad, usando la memoria disponible.","source":"api-test-semantic-run","use_ollama":true,"semantic_recall_enabled":true,"semantic_model":"nomic-embed-text:latest","semantic_limit":3,"semantic_min_similarity":0.55,"semantic_domain":"crystal","context":{"project_id":"triade-local","active_neuron":"cristal","context_scope":"project_neuron"}}'
```

## Estado

Código subido a `main`. Pendiente de validación local del usuario.

## Siguiente microfase recomendada

`TRIADE_SEMANTIC_MEMORY_GOVERNANCE_1.9E`

Objetivo:

- clasificar memoria semántica como experimental o estable;
- incorporar reglas Safety/Verifier para evitar que recuerdos no verificados influyan indebidamente;
- definir consolidación, confianza, fuente y promoción de documentos semánticos.