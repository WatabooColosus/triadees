# Fase 01 · Cierre de veracidad operativa

Fecha: 2026-07-29 UTC

Base: `d85a815a6a22d4e844b1bad61874125ce4c2a573`

Estado: `completed` para el alcance de veracidad de ejecución de esta fase

## Objetivo verificado

Las rutas auditadas ya no pueden convertir observación, ausencia de evidencia,
dry-run, resultados sin estado o candidatos en ejecución completada. Un cierre
canónico exige ejecución explícita, recibo de efecto verificado y artefacto cuando
el contrato lo declara. Los efectos reversibles declaran y publican su referencia
de rollback.

Esto no demuestra aprendizaje autónomo, utilidad, identidad continua ni operación
prolongada; esas capacidades conservan sus fases y gates propios.

## Inventario de rutas

| Ruta | Autoridad / disposición tras la fase |
|---|---|
| Investigación | `goal_research` y research gobernado producen candidatos; `autonomous_research` legacy queda `blocked`. |
| Mejora | El productor `record_improvement` legacy queda retirado para nuevos writes; dirige al learning pipeline gobernado. |
| Documentación | `auto_documentation` legacy queda `blocked` hasta disponer de snapshot/evidencia. |
| Creación neuronal | `autonomous_neuron_creation` legacy queda `blocked`; no crea neuronas ni artefactos. |
| Formación neuronal | `autonomous_training` legacy queda `blocked`; educación canónica conserva gates de dataset/baseline/evaluación. |
| Verificación neuronal | `autonomous_verification` legacy queda `blocked`; tests generados no equivalen a evidencia ejecutada. |
| Aprendizaje | `autonomous_learning` legacy persiste como `observed`, nunca `completed`; un embedding no sustituye evaluación cognitiva. |
| Consolidación | Candidato, `no_evidence` y observación no completan goals; la consolidación estable conserva pipeline separado. |
| Operaciones de archivos | Escritura gobernada publica hash, postcondición, manifiesto de rollback y prueba de rollback. |
| Backup | El worker construye un recibo desde backup cifrado y prueba de restauración antes de poder cerrar. |
| Tareas autónomas | `autonomous_tasks` v2 conserva lease, heartbeat, fencing, artefactos, recibo y cierre atómico; legacy es espejo. |

## Cambios de contrato

- `EffectReceipt` incorpora `rollback_required` y rechaza efectos reversibles
  verificados sin `rollback_ref`.
- `ExecutionResult` rechaza `completed` sin artefacto cuando
  `artifact_required=true`.
- El adaptador canónico de workers marca el artefacto como obligatorio.
- Un handler sin `status` explícito se rechaza; no existe éxito por defecto.
- Dry-run se persiste como `dry_run`, no `completed`.
- La isla `AutonomousRoutines` fue retirada el 2026-08-28 al demostrarse que no
  tenía tablas ni consumidores vivos; las garantías canónicas permanecen en
  `ExecutionResult`, receipts y workers.
- `GoalOrchestrator` no completa goals desde `candidate_created`, `no_evidence`,
  `observed`, `skipped` o `dry_run`.
- El learning pipeline exige Ollama Blood o aprobación humana nominal para evaluar;
  embeddings locales no se presentan como evaluadores.
- Bodega en ausencia de Ollama Blood no anuncia semantic learning ni vector recall
  canónico disponible; conserva la degradación segura/keyword.

## Invariantes ejecutadas

El runner reproducible es:

```bash
python scripts/run_phase_01_execution_truth.py
```

El bundle original conservó 9/9 checks. Tras retirar la isla legacy, el runner
actual reproduce los seis invariantes canónicos que siguen vigentes:

- `completed_requires_receipt = true`
- `completed_requires_artifact_when_declared = true`
- `reversible_requires_rollback_ref = true`
- `timeout_rejects_late_effect = true`
- `stale_fencing_cannot_publish = true`
- `reversible_effect_has_receipt_and_rollback = true`

Bundle: `artifacts/triade_verify/phase_01/execution_truth.json`

SHA-256 del bundle ejecutado:
`dd92f2617074655f0cca61671d950921e4274d38e6cbab543c9589c3ad278eb1`.

La ejecución usó una DB SQLite temporal, un proceso hijo real cancelado por timeout,
rotación real de lease generation y una escritura real revertida mediante
cuarentena/rollback. No modificó la DB de producción ni `identity_core`.

## Pruebas

Pruebas focales ejecutadas inicialmente: 58 aprobadas. Incluyeron:

- `tests/operational_truth`
- `tests/test_no_simulated_autonomy.py`
- `tests/test_capability_goal_orchestrator.py`
- `tests/test_effect_receipts.py`
- `tests/test_governed_capability_rollback.py`
- `tests/test_governed_text_artifact_e2e.py`
- `tests/test_atomic_completion.py`
- `tests/test_lease_fencing.py`
- `tests/test_p0_p1_runtime_governance.py`

Las suites de política de modelo, Ollama Blood, aprendizaje background y heartbeat
que fallaban en el baseline se volvieron a ejecutar juntas y quedaron verdes. La
suite completa `pytest -q` alcanzó 100 % con exit code 0. `compileall` también pasó.

`tests/operational_truth` quedó en 18 pruebas aprobadas. El runner de concurrencia
se ejecutó nuevamente con 101 tareas: 90 `completed`, 11 `dead_letter`, 0 efectos
duplicados, 0 artefactos ausentes, un lease recuperado, todas las tareas
contabilizadas e integridad SQLite `ok`.

La primera repetición de concurrencia encontró un defecto del propio harness: el
directorio default reutilizaba una DB de una ejecución anterior y no podía volver a
reclamar la tarea de crash. Se corrigió para crear un subdirectorio nuevo cuando ya
existe `concurrency.db`, conservando evidencia previa. La prueba automatizada ejecuta
ahora dos validaciones consecutivas sobre el mismo output root.

Gates estáticos medidos al cierre:

- `ruff format --check .`: aprobado, 721 archivos.
- `ruff check .`: pendiente, 824 incidencias (548 `EXE002`, 250 `BLE001`, 26 `S110`).
- `mypy triade`: pendiente, 213 errores en 69 archivos.

Ruff/mypy no se presentan como verdes; su cierre global corresponde a Fase 18 y
permanece en deuda explícita.

## Rollback

Rollback de código: revertir el commit atómico de Fase 1.

Rollback funcional de escritura gobernada: cargar el JSON señalado por
`effect_receipt.rollback_ref` y ejecutar
`GovernedFileWriteCapability.rollback_from_spec`; la prueba E2E y el runner
verifican que el target recupera el estado previo o pasa a cuarentena si antes no
existía.

No se borraron datos históricos ni tablas legacy.

## Límites y deuda que permanece

- La cola legacy aún existe; su retiro controlado corresponde a Fase 2.
- Ruff, mypy y CI global permanecen pendientes; pytest, compileall, operational
  truth y concurrencia están verdes en el cierre local de esta fase.
- Un `completed` de observación significa que una sonda real terminó y conserva
  recibo; no significa efecto, utilidad o aprendizaje.
- Investigación candidata sigue sin equivaler a conocimiento validado.
- La operación real de 24/72 horas continúa pendiente.
