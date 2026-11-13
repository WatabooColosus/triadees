# Triade Omega - Crystal DB Migration 1.8B

## Fase

TRIADE_CRYSTAL_DB_MIGRATION_1.8B

## Objetivo

Persistir las metricas extendidas de Crystal v2 en SQLite, no solo en crystal.json.

## Archivos

- triade/memory/schemas.sql
- triade/core/bodega.py
- tests/test_crystal_db_migration.py

## Columnas nuevas en crystal_states

- pv7_score REAL DEFAULT 0.5
- stability REAL DEFAULT 0.5
- intensity REAL DEFAULT 0.5
- q_crystal REAL DEFAULT 0.0
- ethics_vector TEXT
- regulation_notes TEXT

## Migracion defensiva

Bodega._init_db ejecuta _migrate_crystal_v2.

Si una base existente no tiene estas columnas, las agrega con ALTER TABLE.

Esto evita romper triade/memory/triade.db existente.

## Persistencia

Bodega.store_crystal ahora guarda:

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

## Doctor

Bodega.doctor ahora incluye crystal_quality:

- avg_q_crystal
- avg_stability
- avg_intensity
- avg_pv7_score

## Validacion local

Ejecutar:

- git pull
- source .venv/bin/activate
- pytest

Luego un run real y consultar SQLite:

sqlite3 triade/memory/triade.db "PRAGMA table_info(crystal_states);"
sqlite3 triade/memory/triade.db "SELECT run_id, pv7_score, stability, intensity, q_crystal FROM crystal_states ORDER BY id DESC LIMIT 5;"

## Siguiente fase sugerida

TRIADE_CRYSTAL_Q_FORMULA_1.8C

Objetivo: refinar Q_cristal para acercarla mas a la formula teorica oficial y usarla activamente en plan/respuesta.
