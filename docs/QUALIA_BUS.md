# QualiaBus

`QualiaBus` es la capa circulatoria entre neuronas y órganos de Tríade. No reemplaza a Central, Hipotálamo, Bodega ni QualiaEngine: toma experiencias neuronales y las convierte en paquetes seguros para cada órgano.

## Flujo

1. Una neurona o subsistema produce una `NeuronExperience`.
2. `QualiaRouter` deriva:
   - `QualiaSignal` para modulación interna del Hipotálamo.
   - `CentralKnowledgePacket` para contexto/hypótesis de Central.
   - `StorageMemoryPacket` para trazabilidad en Bodega/SQLite.
   - candidato de `LearningPipeline` si existe `proposed_learning`.
3. `QualiaStore` persiste todo en tablas `qualia_*`.
4. `QualiaBus.compute_state()` actualiza `QualiaState` por run.

## Reglas

- Las neuronas no escriben memoria estable.
- Los paquetes de almacenamiento quedan como `candidate`, `unverified`.
- Central recibe un resumen autorizado, no el bus crudo.
- Hipotálamo solo modula señales internas por umbral y deja notas.
- LearningPipeline recibe candidatos `source_type=qualia_bus`, nunca consolidación automática.
- `identity_core` no se modifica desde QualiaBus.

## Tablas

- `qualia_experiences`
- `qualia_signals`
- `qualia_central_packets`
- `qualia_storage_packets`
- `qualia_states`

La migración es aditiva y usa `CREATE TABLE IF NOT EXISTS`.

## CLI

```bash
python triade_digimon.py qualia publish-test --proposed-learning "Aprender una pauta verificable"
python triade_digimon.py qualia state
python triade_digimon.py qualia experiences
python triade_digimon.py qualia report
```

## API

```bash
curl http://127.0.0.1:8010/qualia/state
curl http://127.0.0.1:8010/qualia/experiences
curl http://127.0.0.1:8010/qualia/signals
curl http://127.0.0.1:8010/qualia/central-packets
curl http://127.0.0.1:8010/qualia/storage-packets
curl -X POST http://127.0.0.1:8010/qualia/publish-test -H 'content-type: application/json' -d '{"run_id":"demo","proposed_learning":"candidato"}'
```

## Runner

Cada run crea artefactos:

- `qualia_experiences.json`
- `qualia_signals.json`
- `qualia_central_packets.json`
- `qualia_storage_packets.json`
- `qualia_state.json`

`memory_diff` incluye contadores y `qualia_state`.
