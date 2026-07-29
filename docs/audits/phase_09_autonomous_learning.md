# Fase 09 — aprendizaje autónomo gobernado demostrable

Fecha UTC: 2026-07-29

Base: `8cc2633`

Estado: `completed`

## Capacidad aprendida

La demostración usa una deficiencia reproducible del intérprete de comandos:
entradas Unicode full-width válidas no se reconocían. Un artifact declarativo,
derivado de evidencia de normalización Unicode, habilita NFKC y colapso de
whitespace. No contiene respuestas por input ni valores del benchmark.

El consumidor `CommandInterpreter` carga artifacts `active`/`consolidated` desde
SQLite tras cada arranque. El generador del change set y el evaluador son clases
separadas; el evaluador solo recibe pares input/expected.

## Ciclo ejecutado

```text
gap
→ research_ref
→ candidate artifact
→ baseline
→ independent evaluation
→ canary/active application
→ five post measurements
→ regression
→ rollback
→ rollback measurement
→ consolidation
→ restart evaluation
→ learning_receipt
```

La promoción exige delta positivo, cinco repeticiones iguales, transferencia
positiva, regresión 1.0 y rollback que reproduzca exactamente baseline.

## Tres demostraciones

### A — Corrección de comportamiento

`ｓｔａｔｕｓ` pasó de score 0.0 a 1.0 después del artifact. El mismo resultado se
repitió cinco veces.

### B — Transferencia

El caso `ｉｄｅｎｔｉｔｙ　ｖｅｒｉｆｙ`, no usado como input de creación, obtuvo 1.0. Los
sets de creación y transferencia se registran y son disjuntos.

### C — Persistencia

Tras construir una nueva instancia de `CommandInterpreter` desde SQLite, tanto
el caso original como el transferido conservaron score 1.0.

La regresión contiene comandos ASCII válidos y un comando desconocido; score
1.0. El rollback desactivó el artifact y devolvió el caso original exactamente
al baseline; luego el gate permitió consolidación.

## Ejecución y evidencia

```bash
python scripts/run_phase_09_autonomous_learning.py
```

```text
artifacts/triade_verify/phase_09/autonomous_learning.json
artifacts/triade_verify/learning/lr-*.json
```

El segundo archivo es el `learning_receipt` con observaciones, separación de
benchmarks, rollback y decisión.

## Migración y rollback

La migración 025 crea tablas de artifacts y receipts. No modifica código ni
`identity_core` automáticamente. Cada artifact tiene `rollback_ref`; la acción
probada cambia su estado a `rolled_back`. Un resultado no reproducible,
regresivo, sin transferencia o sin rollback termina `rejected`.

## Validación ejecutada

```text
python -m compileall -q triade apps scripts tests          PASS
ruff format --check .                                     PASS (756 files)
pytest -q tests/test_autonomous_learning_cycle.py          PASS (3)
pytest -q tests/test_learning_e2e_stable.py tests/test_learning_canary.py
                                                            PASS (6)
pytest -q                                                  PASS
pytest -q tests/operational_truth                          PASS (18)
python scripts/run_runtime_concurrency_test.py             PASS
```

La concurrencia produjo 101 filas terminales (`90 completed`, `11
dead_letter`), sin duplicados ni tareas perdidas, e integridad SQLite `ok`.
El repositorio conserva deuda preexistente: `ruff check .` reporta 813 errores
y `mypy triade` reportaba 224 antes de esta fase. El módulo nuevo se comprobó
sin errores focales; estos gates globales no se presentan como aprobados.

## Riesgos y deuda

- Es una demostración real pero acotada a una capacidad determinista. No prueba
  aprendizaje abierto, modelos autoentrenados ni mejora general de inteligencia.
- La investigación se representa por una referencia de evidencia; el runner de
  fase no consulta Internet. La independencia de fuentes se demuestra en Fase 8.
- La significancia aquí es repetición determinista, no inferencia estadística
  sobre datos ruidosos.
- No se afirma AGI, conciencia ni autosuficiencia.
