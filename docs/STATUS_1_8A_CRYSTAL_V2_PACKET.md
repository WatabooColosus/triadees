# Triade Omega - Crystal v2 Packet 1.8A

## Fase

TRIADE_CRYSTAL_V2_1.8A

## Objetivo

Extender el Cristal Morfologico para que sus metricas profundas sean campos reales del CrystalPacket y no solo texto dentro de decision_notes.

## Archivos

- triade/core/contracts.py
- triade/core/crystal.py
- tests/test_crystal_v2.py

## Campos nuevos en CrystalPacket

- pv7_score
- stability
- intensity
- q_crystal
- ethics_vector
- regulation_notes

## Comportamiento

Crystal.regulate ahora calcula y entrega:

- ethics
- depth
- creativity
- relation
- pv7_score
- stability
- intensity
- q_crystal
- ethics_vector
- regulation_notes
- decision_notes

## q_crystal

Se agrego una aproximacion operativa inicial de Q_cristal.

No cierra todavia la formula filosofica completa, pero crea una metrica verificable para regular el ciclo.

## Evidencia

El archivo crystal.json de cada run ahora debe contener los campos extendidos.

## Validacion local

Ejecutar:

- git pull
- source .venv/bin/activate
- pytest

Prueba de run:

- ejecutar un mensaje desde UI o CLI
- revisar runs/<run_id>/crystal.json

## Siguiente fase sugerida

TRIADE_CRYSTAL_DB_MIGRATION_1.8B

Objetivo: extender crystal_states en SQLite para guardar estos campos como columnas reales, no solo dentro del JSON de artefacto.
