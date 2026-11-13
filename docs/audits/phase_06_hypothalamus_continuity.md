# Fase 06 — continuidad de modulación relacional

Fecha UTC: 2026-07-29

Base: `215f1d8`

Estado: `completed`

## Terminología y límites

La capacidad se denomina exclusivamente `relational modulation state`. Es un
vector funcional PV-7 por usuario/sesión; no representa sentimientos humanos,
conciencia ni experiencia subjetiva. El payload expone siempre
`subjective_emotion_claimed=false`.

## Implementación

La migración aditiva e idempotente `022_relational_modulation.sql` crea estados
por clave compuesta `(user_id, session_id)` y un log append-only de eventos. El
estado contiene baseline, PV-7 actual, contador y timestamps.

Los eventos admitidos están enumerados y cada tipo tiene un delta máximo. El
estado, además, no puede alejarse más de 0.25 del baseline ni salir de `[0, 1]`.
Cada cambio guarda before/requested/applied/after, explicación y procedencia.
El decay exponencial acerca el vector al baseline. Solo el evento activo más
reciente puede revertirse, evitando que un rollback antiguo sobrescriba cambios
posteriores.

`Hypothalamus.analyze()` consume este estado cuando el `InputPacket.context`
incluye `user_id` y `session_id`. En ese modo no carga el mood global legacy,
evitando contaminación entre sesiones. La contribución al PV-7 se mezcla de
forma explícita (75 % señal actual, 25 % estado relacional) y queda anotada sin
claim subjetivo.

## Evidencia runtime

```bash
python scripts/run_phase_06_relational_modulation.py
```

Resultado 8/8:

```text
evento modifica estado
input extremo queda limitado
aislamiento de usuario
persistencia tras reinicio
decay hacia baseline
rollback restaura estado anterior
restore sandbox verificado
sin claim subjetivo
```

Restore: SQLite `ok`, fingerprint idéntico y
`production_overwritten=false`.

## Protección de identidad

La prueba compara todas las filas de `identity_core` antes y después de evento,
reinicio y rollback. No hubo cambios. La migración 022 tampoco referencia
`identity_core`.

## Validaciones

```text
pytest -q tests/test_relational_modulation.py            5 pass
pytest -q tests/test_hypothalamus_state.py               26 pass
python scripts/run_phase_06_relational_modulation.py     8/8 pass
pytest -q                                               pass
pytest -q tests/operational_truth                        18 pass
python scripts/run_runtime_concurrency_test.py           pass
ruff format --check .                                   pass (744 archivos)
ruff check .                                            fail (813)
mypy triade                                             fail (224 en 68 archivos)
```

Concurrencia: 101 tareas contabilizadas, cero efectos duplicados, cero
artefactos faltantes e integridad SQLite `ok`.

## Evidencia

```text
artifacts/triade_verify/phase_06/relational_modulation.json
```

## Rollback

Existe rollback por evento con actor y razón, además de backup SQLite y restore
solo a sandbox inexistente con fingerprint. La migración es aditiva; desactivar
el consumo en `Hypothalamus` devuelve el comportamiento previo sin borrar el
historial.

## Riesgos y deuda

- La mezcla 75/25 es una política inicial fija; requiere calibración longitudinal
  futura, no se presenta como óptima.
- Los productores deben emitir eventos gobernados explícitos; actividad normal
  no se convierte automáticamente en modulación.
- El cifrado y restore de producción corresponden a la Fase 16.
- Ruff y mypy globales permanecen como deuda de la Fase 18.
