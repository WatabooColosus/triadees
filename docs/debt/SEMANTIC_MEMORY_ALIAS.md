# `semantic_memory` → `semantic_documents`: el lector que apuntaba al gemelo

**Fecha de la medición:** 2026-08-09 · **Base:** `triade/memory/triade.db`
**PR:** #93 · **Rama:** `fix/semantic-memory-alias-search`

## Lo medido, no lo supuesto

| Tabla | Filas | Por estado | Primera / última escritura |
|---|---|---|---|
| `semantic_memory` | **0** | — | ninguna |
| `semantic_documents` | **299** | `candidate` 299 | 2026-07-28 → 2026-08-08 |
| `semantic_embeddings` | **299** | — | — |
| `semantic_governance_events` | **0** | — | ninguna |

La tabla vieja no está «desactualizada»: está **vacía**. La viva recibe
escrituras hasta el día anterior a esta medición.

## El corte

`Bodega._search_semantic()` —la búsqueda por palabras clave de la memoria
semántica, que corre en **todos** los runs, con recall vectorial o sin él—
consultaba `semantic_memory`. Con 0 filas devolvía `[]` para cualquier consulta.
El canal existía, se ejecutaba y no podía acertar.

| | |
|---|---|
| **Tabla vieja** | `semantic_memory` (key, value, domain, source_ref, confidence, status) |
| **Tabla viva** | `semantic_documents` (document_id, content, domain, source_ref, status, …) |
| **Writer vivo** | `SemanticMemoryStore.upsert_document()` |
| **Reader roto** | `Bodega._search_semantic()` |
| **Evento** | cada `Runner.run()` → `Bodega.recall()` |
| **Alcanzabilidad** | alcanzable siempre: `recall()` no depende de `semantic_recall_enabled` |
| **Gate** | ninguno antes; ahora la política 1.9E en SQL **y** en gobierno |
| **Efecto** | 0 coincidencias por texto en todo run desde que los documentos dejaron de escribirse en la tabla vieja |
| **Decisión** | **MIGRATE_READER** (uno: `_search_semantic`), no retirada de la tabla |

## Gobierno: el filtro no podía ser `stable + experimental`

La primera versión de esta reparación filtraba
`status IN ('stable','experimental')`. Eso contradice la política 1.9E, que
`SemanticMemoryGovernance.doctor()` publica como contrato:

```
stable        → influye por defecto
experimental  → sólo si el run lo autoriza (semantic_allow_experimental=true)
candidate     → nunca
rejected      → nunca
```

Y el agujero era doble, porque `govern_memory()` marcaba **todo** match no
vectorial con `governance_note="legacy_keyword_no_governance"` y
`allowed_to_influence=True`. Un documento `experimental` influía en cualquier run
por el solo hecho de coincidir por texto, sin que nadie lo autorizara, y el
propio rastro de auditoría lo declaraba autorizado.

**Reparado sin crear un segundo sistema de gobierno:**

- La política vive en un único sitio, `influence_allowed_statuses()` en
  `triade/memory/semantic_governance.py`. Los dos canales la llaman; ninguno
  repite la lista de estados.
- La autorización ya viajaba de la API al gobierno vectorial
  (`semantic_allow_experimental`: `apps/services.py` → `apps/routes/api.py` →
  `TriadeRunner.run()` → `govern_memory()`). Sólo faltaba el tramo
  `Runner → Bodega.recall() → _search_semantic()`; ese es el añadido.
- El estado se filtra **en SQL**, no después de recuperar. El canal de palabras
  clave corre también con el recall vectorial apagado, y entonces el run no pasa
  nunca por `govern_memory()`: dejar entrar `experimental` «porque luego alguien
  gobierna» sería confiar en un paso opcional.
- `govern_memory()` juzga ahora los dos canales con el mismo gate y el mismo
  `GovernanceDecision`, ahora con campo `channel`.

## Veredicto por consumidor de `semantic_memory`

La tabla **no queda retirada**. Tenía un escritor vivo y alcanzable, y el resto
de sus lectores no son de este PR.

| Consumidor | Rol | Alcanzable | Veredicto |
|---|---|---|---|
| `Bodega._search_semantic()` | reader | sí, todo run | **MIGRADO** a `semantic_documents` |
| `triade/evaluation/triadic_ablation.py:_seed()` | **writer** | sí (`scripts/run_phase_04_triadic_causality.py`, `tests/test_triadic_cycle_trace.py`) | **MIGRADO**: siembra un documento vivo `stable` |
| `triade/memory/compression.py:deduplicate_semantic()` | reader + deleter | **no**: ningún llamador en el repo | **DEAD_CODE**. Su contrato (`key`/`value`/`confidence`) no existe en `semantic_documents`; migrarlo sería inventarle un consumidor. Se decide aparte. |
| `triade/core/learning_journal.py` | reader | sí (`GET /runtime/learning_journal`) | **KEEP_WITH_REASON**: informa actividad, no alimenta al modelo. Reporta 0, que es la verdad. |
| `triade/core/qualia.py` | reader | sí | **YA MIGRADO**: `has_stable_semantic_memory` sale de `semantic_documents`; `semantic_memory_by_status` es residuo informativo. |
| `triade/os/autonomous_routines.py:_memory_organization()` | reader | sí | **KEEP_WITH_REASON**: sólo diagnostica duplicados y nunca borra. |
| `triade/memory/encrypted_backup.py` | reader (recuento) | sí | **FUERA DE ALCANCE**: integridad de backup es el PR #92. No se toca aquí. |
| `scripts/audit_runtime_truth.py` | reader | script manual | **KEEP_WITH_REASON** |
| `observability_view`, `conversation_analyzer`, `system_pulse_builder`, `runtime_graph` | listas de tablas | sí | **KEEP_WITH_REASON**: nombran la tabla para contarla, no para leer memoria. |

**Decisión global: `MIGRATE_READERS` parcial y gobernada.** Se migra el lector
que producía el efecto (`_search_semantic`) y el escritor que dejó de medir lo
que decía medir (el benchmark ablativo). No se migran en bloque los demás: uno
es código muerto con otro contrato, otro pertenece a un PR abierto, y el resto
sólo cuenta filas. Retirar la tabla exige cerrar antes esos frentes.

## La regresión que este PR estuvo a punto de dejar

`triadic_ablation._seed()` escribía una fila `stable` en `semantic_memory` y el
benchmark de causalidad medía, con la variante `without_semantic_recall`, que
quitar la memoria semántica cambia el resultado. Al reapuntar el lector, esa
fila dejó de verse: `recall.semantic` pasó de **1 a 0** en todas las variantes y
la dimensión `recall` bajó de **3 diferencias a 0**. El test seguía en verde
—`planning` y `crystal` aún diferían—, así que la pérdida era silenciosa.

Sembrando el documento vivo `stable` el benchmark vuelve a **3 diferencias en
`recall`** y, de paso, se convierte en evidencia de que un documento autorizado
llega hasta Central por el camino real.

## Causalidad demostrada

| | ANTES | DESPUÉS |
|---|---|---|
| documento `stable` en `semantic_documents` | 0 coincidencias (`_search_semantic` miraba la tabla vacía) | coincidencia con `document_id` + `source_ref`, autorizada por gobierno |
| documento `candidate` | 0 coincidencias | 0 coincidencias: recuperable por otros canales, **no influye** |
| documento `experimental`, run sin autorización | **influía** (filtro `stable+experimental` y sello `allowed_to_influence=True`) | **no influye** |
| documento `experimental`, run con `semantic_allow_experimental=true` | — | influye, y el gobierno lo registra con `channel="keyword"` |
| fila `stable` en `semantic_memory` | se leía | ya no se lee |

Pruebas: `tests/test_semantic_memory_alias_search.py` (10),
`tests/test_semantic_schema_parity.py` (3),
`tests/test_semantic_recall_integration.py`, `tests/test_semantic_governance.py`,
`tests/test_triadic_cycle_trace.py`.

## Nota sobre la base viva

En `triade/memory/triade.db` los 299 documentos están en `candidate` y no hay
ningún evento de gobierno. Por tanto **hoy esta reparación no hace aparecer
ninguna coincidencia nueva en producción**: hace que el canal deje de ser
imposible y que, cuando exista el primer documento promovido a `stable`, llegue.
Lo contrario —contar 299 documentos como memoria recuperada— es justo lo que la
política 1.9E prohíbe.

## Esquema base

`semantic_documents` y `semantic_embeddings` sólo nacían por la migración
`001_9A_semantic_memory.sql`, es decir cuando alguien instanciaba
`SemanticMemoryStore`. Ahora están también en `triade/memory/schemas.sql`, que se
reejecuta en cada arranque. Dos fuentes para la misma tabla derivan en silencio,
así que `tests/test_semantic_schema_parity.py` compara las dos bases resultantes
columna a columna, índice a índice y clave foránea a clave foránea —incluido el
`ON DELETE CASCADE`—, no que las tablas «existan».
