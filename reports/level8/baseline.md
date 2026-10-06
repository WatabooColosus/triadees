# Tr?ade ? ? baseline nivel 8

Generado: 2026-10-06T01:31:31.942534+00:00
SHA: `46728d2a3dbb8e5221ee160dbad3ce3ab4c148e8`
Rama: `main`
origin/main: `46728d2a3dbb8e5221ee160dbad3ce3ab4c148e8`

## Estado Git
```
?? android/triade-node/java_pid2484.hprof
?? reports/debt-current.json
?? reports/level8_autonomy_snapshot.json
?? reports/level8_edge_snapshot.json
?? reports/level8_neuron_snapshot.json
?? reports/level8_pip.txt
?? reports/level8_runtime_snapshot.json
?? reports/level8_stable_snapshot.json
?? triade/memory/live_runtime.db
```

## SQLite
- Base: `triade\memory\triade.db`
- Integridad: **ok**
- Tablas: 107
- Learning queue: 34 ({'evidence_verified': 1, 'internally_checked': 33})

## Superficie inspeccionada
- triade: presente
- apps: presente
- scripts: presente
- tests: presente
- docs: presente
- audit: presente
- reports: presente
- artifacts: presente
- android: presente

## Clasificaci?n inicial
- **REAL/ejecutado:** API, heartbeat, workers y Ollama tienen observaciones HTTP/runtime recientes.
- **PARCIAL:** aprendizaje: 1 `evidence_verified`, 1 ruta neuronal; uso productivo acumulado de cola a?n 0.
- **NO DEMOSTRADO:** educaci?n E2E productiva, canary medido, rollback productivo, reinicio con continuidad, dos nodos federados, ventana longitudinal.
- **ROTO/ bloqueado:** ninguno cr?tico observado en la auditor?a puntual.
- **RUNTIME STATE:** `triade/memory/*.db` y heap dumps; excluidos de Git.

## Bloqueos prioritarios
1. Cerrar uso causal posterior y medici?n de `run_use_count`.
2. Ejecutar educaci?n neuronal en runtime normal y registrar aplicaci?n.
3. Probar restart continuity sin duplicar tareas ni perder receipts.
4. Probar dos nodos federados independientes.
5. Reparar/documentar CI rojo con evidencia de causa.
