# Tríade Ω - Semantic Memory Governance 1.9E

## Fase

`TRIADE_SEMANTIC_MEMORY_GOVERNANCE_1.9E`

## Motivo de la fase

La validación real de `1.9D` confirmó que Central recibió recuerdos vectoriales, pero también reveló un riesgo:

- documentos en estado `candidate` influyeron en una respuesta de Central;
- el modelo introdujo una procedencia no contenida literalmente en la memoria (`proyecto Neurón`) mientras el contexto real era `triade-local` + `cristal`.

La memoria semántica no puede considerarse segura únicamente porque tenga alta similitud. Debe poseer estado, fuente, aprobación y evidencia.

## Objetivo

Controlar qué recuerdos semánticos pueden influir en Central y Cristal mediante una política auditable de estados y transiciones.

## Estados de memoria

- `candidate`: contenido recién ingresado o aún no evaluado. Puede recuperarse para inspección, pero no puede influir.
- `experimental`: contenido en evaluación. Solo influye si el run autoriza explícitamente memoria experimental.
- `stable`: contenido verificado con `source_ref`. Puede influir por defecto cuando semantic recall está activo.
- `rejected`: contenido descartado. No puede influir.

## Transiciones permitidas

```text
candidate    → experimental | rejected
experimental → stable | candidate | rejected
stable       → rejected
rejected     → candidate
```

Una memoria no puede pasar directamente de `candidate` a `stable`.
Una memoria no puede pasar a `stable` sin `source_ref`.
Toda transición registra razón, aprobador, evidencia y timestamp.

## Archivos

- `triade/memory/semantic_governance.py`
- `triade/memory/semantic_store.py`
- `triade/core/runner.py`
- `triade/core/central.py`
- `triade/core/safety.py`
- `triade/core/verification.py`
- `apps/single_port_app.py`
- `tests/test_semantic_governance.py`
- `tests/test_semantic_recall_integration.py`
- `tests/test_single_port_semantic_recall.py`
- `docs/STATUS_1_9E_SEMANTIC_MEMORY_GOVERNANCE.md`

## Órgano de gobierno

`SemanticMemoryGovernance` incorpora:

- `transition_document()`: promueve, devuelve o rechaza documentos con trazabilidad;
- `govern_memory()`: separa recuerdos recuperados de recuerdos autorizados;
- `list_events()`: consulta historial de decisiones;
- `doctor()`: muestra política activa y conteo de documentos por estado.

## Política de influencia

### Por defecto

```text
stable       → autorizado para Central y Cristal
experimental → cuarentena
candidate    → cuarentena
rejected     → cuarentena
```

### Con autorización experimental explícita

```text
stable       → autorizado
experimental → autorizado
candidate    → cuarentena
rejected     → cuarentena
```

## Corrección de influencia indirecta

En `1.9D`, una memoria vectorial recuperada elevaba `memory.confidence` antes de pasar por política. Como Crystal usa `memory.confidence` para calcular profundidad, relación, estabilidad y `Q_cristal`, un documento candidato podía influir indirectamente aunque no se mostrara como hecho.

En `1.9E`, si existen matches vectoriales y ninguno está autorizado:

- se retira el refuerzo de confianza vectorial;
- la memoria queda visible como `quarantined_matches`;
- no entra a `MemoryPacket.semantic_matches` autorizado;
- no eleva el Cristal mediante confianza;
- Safety y Verifier generan advertencia auditable.

## Protección de reingestión

`SemanticMemoryStore.upsert_document()` conserva el estado ya gobernado de documentos duplicados. Reingresar el mismo texto como `candidate` no degrada un documento `stable`.

Si se intenta sobrescribir el contenido de una memoria gobernada con un texto diferente, debe crearse un nuevo documento candidato en lugar de reemplazar silenciosamente conocimiento ya evaluado.

## Central

Central ahora recibe únicamente `semantic_matches_authorized_only` y una instrucción de atribución literal:

- no inventar origen, proyecto, neurona, fuente o estado;
- usar únicamente `source_ref`, `document_id`, `document_status` o `input_context` presentes en el paquete;
- reconocer insuficiencia si no hay memoria autorizada.

## Safety y Verifier

Si hay recuerdos recuperados pero en cuarentena:

- Safety agrega `semantic_memory_unverified`;
- eleva el riesgo mínimo a `medium`;
- impide tratarlos como hechos consolidados;
- Verifier cambia el reporte a `warning`;
- reduce `memory_score` y recomienda promoción auditable.

## API Single Port

### Diagnóstico de gobierno

```bash
GET http://127.0.0.1:8010/api/semantic/governance/doctor
```

### Transición de documento

```bash
POST http://127.0.0.1:8010/api/semantic/documents/{document_id}/transition
```

Payload:

```json
{
  "new_status": "experimental",
  "reason": "Documento confirmado durante validación de memoria semántica.",
  "approved_by": "santiago",
  "evidence": {"phase": "1.9E"}
}
```

### Parámetro de run

`POST /api/run` acepta adicionalmente:

```json
{
  "semantic_allow_experimental": false
}
```

El valor recomendado en operación normal es `false`.

## Validación local

### 1. Actualizar y ejecutar suite

```bash
cd ~/triadees
git pull
source .venv/bin/activate
pytest
sudo systemctl daemon-reload
sudo systemctl restart triade-chat-ui
```

### 2. Consultar política

```bash
curl http://127.0.0.1:8010/api/semantic/governance/doctor
```

Los documentos creados en `1.9B/1.9C` deberían aparecer inicialmente como `candidate`.

### 3. Probar cuarentena antes de promover

```bash
curl -X POST http://127.0.0.1:8010/api/run \
  -H "Content-Type: application/json" \
  -H "X-TRIADE-API-Key: hope0102" \
  -d '{"text":"Qué órgano regula la estabilidad y continuidad entre ejecuciones","source":"api-test-governance","use_ollama":false,"semantic_recall_enabled":true,"semantic_model":"nomic-embed-text:latest","semantic_limit":3,"semantic_min_similarity":0.55,"semantic_domain":"crystal","context":{"project_id":"triade-local","active_neuron":"cristal","context_scope":"project_neuron"}}'
```

Resultado esperado antes de promover:

- `semantic_recall.matches_count >= 1` porque la memoria fue recuperada;
- `semantic_recall.authorized_matches_count = 0`;
- `governance.quarantined_vector_matches >= 1`;
- `memory_diff.semantic_recall.authorized_matches = []`;
- `safety.risk_types` incluye `semantic_memory_unverified`;
- `report.status = warning`.

### 4. Promover el documento principal del Cristal

Documento confirmado en validación previa:

```text
sem-32a9c4889e154e37
```

Primera transición:

```bash
curl -X POST http://127.0.0.1:8010/api/semantic/documents/sem-32a9c4889e154e37/transition \
  -H "Content-Type: application/json" \
  -H "X-TRIADE-API-Key: hope0102" \
  -d '{"new_status":"experimental","reason":"El contenido coincide con la función implementada y validada del Cristal en fases 1.8A-1.8F.","approved_by":"santiago","evidence":{"phase":"1.9E","validated_by":"local-run"}}'
```

Segunda transición:

```bash
curl -X POST http://127.0.0.1:8010/api/semantic/documents/sem-32a9c4889e154e37/transition \
  -H "Content-Type: application/json" \
  -H "X-TRIADE-API-Key: hope0102" \
  -d '{"new_status":"stable","reason":"Memoria verificada contra implementación y evidencia de continuidad contextual del Cristal.","approved_by":"santiago","evidence":{"phase":"1.9E","source_ref":"validacion-1.9C-crystal"}}'
```

### 5. Probar memoria autorizada

```bash
curl -X POST http://127.0.0.1:8010/api/run \
  -H "Content-Type: application/json" \
  -H "X-TRIADE-API-Key: hope0102" \
  -d '{"text":"Explica qué órgano regula continuidad y estabilidad usando solo memoria autorizada.","source":"api-test-governance","use_ollama":true,"semantic_recall_enabled":true,"semantic_model":"nomic-embed-text:latest","semantic_limit":3,"semantic_min_similarity":0.55,"semantic_domain":"crystal","semantic_allow_experimental":false,"context":{"project_id":"triade-local","active_neuron":"cristal","context_scope":"project_neuron"}}'
```

Resultado esperado después de promover:

- el documento `sem-32a9c4889e154e37` aparece con `document_status=stable`;
- `authorized_matches_count >= 1`;
- Central puede usar ese recuerdo;
- la respuesta no debe inventar `proyecto Neurón` ni procedencias ajenas al paquete.

## Estado

Código subido a `main`. Pendiente de validación local del usuario.

## Siguiente bloque recomendado

Al validar `1.9E`, la memoria semántica base queda cerrada. El siguiente bloque estructural recomendado será:

`TRIADE_NEURON_ORCHESTRATION_2.0A`

Objetivo: activar N Creadora y N Formadora dentro del ciclo real, con gobierno, misión, evaluación posterior al run y memoria semántica autorizada.