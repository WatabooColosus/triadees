# Semantic Continuity

Fecha: 2026-06-05

## Problema

La memoria semántica no puede ser un adorno. Si no crea documentos ni embeddings, Tríade solo tiene memoria episódica temporal y un panel que informa estado, pero no continuidad semántica real.

## Solución

Cada run puede crear ahora:

- un documento en `semantic_documents`
- un embedding en `semantic_embeddings`
- estado `candidate`
- `source_ref = run:<run_id>`
- metadata con fuente, intención, Q_crystal, estabilidad y modelos

Esto vuelve la memoria continua sin saltarse gobierno:

- no modifica `identity_core`
- no consolida `stable` automáticamente
- no convierte candidatos en verdad estable
- sí deja rastro semántico real y vectorizable

## Embeddings

Tríade usa dos rutas:

- Ollama embeddings cuando se piden explícitamente desde el motor semántico.
- `triade-local-hash:64` como embedding local verificable para continuidad mínima siempre disponible.

El embedding local evita que la memoria quede vacía cuando Ollama no responde o cuando el sistema corre tests/offline.

## CLI

Diagnóstico:

```bash
python triade_digimon.py semantic-continuity doctor
```

Backfill de runs recientes:

```bash
python triade_digimon.py semantic-continuity backfill-runs --limit 50
```

Backfill solo con hash local:

```bash
python triade_digimon.py semantic-continuity --no-ollama-embed backfill-runs --limit 50
```

## Relación Con Qualia

Qualia lee la memoria semántica y la alinea con Pulso Vivo:

- si hay documentos candidatos, informa que hay memoria candidata;
- si hay stable, informa memoria semántica consolidada;
- si no hay documentos, informa que el pulso vivo sigue percibiendo estado actual, pero la Bodega semántica necesita continuidad.

## Estado De Gobierno

Los documentos creados por continuidad son `candidate`. Para volverse memoria estable deben pasar por evaluación, verificación y aprobación humana.
