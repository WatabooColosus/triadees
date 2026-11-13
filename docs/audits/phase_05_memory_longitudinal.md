# Fase 05 — memoria longitudinal gobernada

Fecha UTC: 2026-07-29

Base: `1156426`

Estado: `completed`

## Implementación

La migración idempotente `021_longitudinal_memory.sql` añade un registro
canónico separado de la memoria semántica legacy. Cada memoria incluye tipo,
clave, valor normalizado, estado, procedencia, confianza, temporalidad y scope
obligatorio por usuario, sesión, proyecto y dominio.

Tipos admitidos:

```text
fact preference correction relationship decision restriction project temporal
```

Estados gobernados:

```text
observed candidate verified stable contradicted expired quarantined
```

Una observación solo nace `observed` o `candidate`; por tanto, un candidato no
influye en recall. La promoción requiere actor, razón y referencia de evidencia.
El recall solo devuelve `verified`/`stable`, filtra todos los scopes en SQL y
explica términos coincidentes, scope, estado, procedencia y orden de ranking.

Conflictos de valor en la misma clave y scope contradicen la versión anterior y
enlazan la nueva mediante `supersedes_id`/`contradiction_of_id`. Expiración y
decay son explícitos y auditados. El decay se aplica a candidate/verified con
half-life configurable; stable no decae automáticamente.

El extractor determinista reconoce enunciados explícitos en español o inglés.
No usa un modelo y no pretende extraer hechos implícitos de lenguaje abierto.

## Benchmark longitudinal

```bash
python scripts/run_phase_05_memory_longitudinal.py
```

Corpus inicial: cinco memorias verificadas y cinco consultas entre dos usuarios,
dos proyectos y sesiones independientes. Incluye corrección contradictoria,
cambio temporal, reinicio de proceso, backup y restore sandbox.

| Métrica | Resultado | Umbral | Gate |
|---|---:|---:|---|
| precision | 1.00 | >= 0.95 | pass |
| recall | 1.00 | informativa | pass |
| hallucinated memory rate | 0.00 | < 0.01 | pass |
| cross-user contamination | 0.00 | = 0 | pass |
| contradiction detection | 1.00 | >= 0.90 | pass |
| restore fidelity | 1.00 | = 1.0 | pass |

El resultado prueba este corpus determinista inicial. No demuestra todavía esos
valores sobre conversación libre, idiomas no cubiertos o un corpus de producción.

## Restore y rollback

El backup usa la API de backup de SQLite. El restore solo acepta un destino
sandbox inexistente, ejecuta `PRAGMA integrity_check` y compara un fingerprint
semántico que incluye contenido, estados, scopes, procedencia, expiración y
relaciones de supersesión. El resultado observado fue `verified`, integridad
`ok`, fingerprint idéntico y `production_overwritten=false`.

La migración 021 solo crea tablas e índices. No elimina ni reescribe memoria
legacy. El rollback funcional es dejar de usar el nuevo store; la recuperación
de datos se realiza desde el backup verificado sin sobrescritura automática.

## Validaciones

```text
python -m compileall -q triade apps scripts tests       pass
ruff format --check .                                   pass (739 archivos)
ruff check archivos Fase 5                              pass
pytest -q tests/memory_longitudinal                      5 pass
pruebas dirigidas memoria/identidad                      22 pass
pytest -q                                               pass
pytest -q tests/operational_truth                        18 pass
python scripts/run_runtime_concurrency_test.py           pass
ruff check .                                            fail (813)
mypy triade                                             fail (224 en 68 archivos)
```

Concurrencia: 101 tareas, 90 `completed`, 11 `dead_letter`, cero efectos
duplicados, cero artefactos faltantes e integridad SQLite `ok`.

## Evidencia

```text
artifacts/triade_verify/phase_05/memory_longitudinal.json
```

## Riesgos y deuda

- El store longitudinal aún no sustituye automáticamente todos los productores
  semánticos legacy; su adopción debe ser explícita para evitar contaminación.
- La extracción es conservadora y explícita. La evaluación de lenguaje abierto
  requiere un corpus independiente futuro.
- El backup no está cifrado en esta fase; cifrado, retención y procedimiento de
  producción pertenecen a la Fase 16.
- Ruff y mypy globales permanecen como deuda de la Fase 18.
