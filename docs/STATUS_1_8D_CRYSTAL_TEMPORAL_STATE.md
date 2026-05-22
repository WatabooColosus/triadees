# Triade Omega - Crystal Temporal State 1.8D

## Fase

TRIADE_CRYSTAL_TEMPORAL_STATE_1.8D

## Objetivo

Dar continuidad temporal al Cristal Morfologico. Cada run nuevo compara su Q_cristal y estabilidad con cristales anteriores persistidos para detectar mejora, estabilidad o degradacion.

## Archivos

- triade/core/contracts.py
- triade/core/crystal.py
- triade/core/bodega.py
- triade/core/runner.py
- triade/core/central.py
- triade/memory/schemas.sql
- tests/test_crystal_v2.py
- tests/test_crystal_db_migration.py

## Campos nuevos de CrystalPacket

- previous_q_crystal
- previous_stability
- q_delta
- stability_delta
- temporal_status
- temporal_alerts
- history_window

## Estados temporales

- baseline: primer estado sin historial comparable
- stable: continuidad dentro de umbrales operativos
- improving: mejora de Q y estabilidad respecto al estado anterior
- degrading: caida marcada o descenso contra promedio reciente
- critical: Q o estabilidad en umbral bajo

## Integracion del ciclo

Runner ahora ejecuta:

1. Input
2. Senales del Hipotalamo
3. Recuperacion de memoria
4. Recuperacion de los ultimos cristales persistidos
5. Regulacion actual con comparacion temporal
6. Persistencia de nuevo estado Crystal
7. Plan de Central condicionado por temporal_status
8. Safety, output, reporte e integridad

## Persistencia SQLite

crystal_states incorpora:

- previous_q_crystal REAL
- previous_stability REAL
- q_delta REAL
- stability_delta REAL
- temporal_status TEXT
- temporal_alerts TEXT
- history_window INTEGER

Bodega aplica migracion defensiva a bases existentes mediante ALTER TABLE.

## Influencia en Central

- degrading o critical: prudencia temporal reforzada y registro de alerta
- improving: sostiene mejora bajo control etico
- stable con Q alto: permite profundidad estable

## Evidencia por run

El estado temporal aparece en:

- crystal.json
- plan.json
- output.json
- memory_diff.json
- integrity.json
- SQLite crystal_states

## Validacion local

Ejecutar:

- git pull
- source .venv/bin/activate
- pytest
- sudo systemctl restart triade-chat-ui

Generar dos runs seguidos desde la UI o API y revisar:

- crystal.json del segundo run
- memory_diff.json del segundo run
- SQLite crystal_states

Consulta sugerida:

sqlite3 triade/memory/triade.db "SELECT run_id, q_crystal, stability, previous_q_crystal, q_delta, temporal_status, history_window FROM crystal_states ORDER BY id DESC LIMIT 5;"

## Siguiente fase sugerida

TRIADE_CRYSTAL_SAFETY_FEEDBACK_1.8E

Objetivo: enlazar degradacion temporal del Cristal con Verifier y Safety para generar advertencias y controles adicionales auditables antes de ejecutar acciones sensibles.