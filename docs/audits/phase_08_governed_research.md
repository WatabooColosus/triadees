# Fase 08 — research gobernado

Fecha UTC: 2026-07-29

Base: `c59b00a`

Estado: `completed`

## Implementación

`GovernedResearchWorker` solo acepta runs originados por gap, contradicción,
fallo repetido, necesidad de benchmark o decisión humana. Cada run persiste
question, trigger, scope, allowlist, mínimo de fuentes independientes,
procedencia, `fetched_at`, claims, contradicciones, preguntas abiertas,
confidence, fallos y evidence bundle.

La independencia exige hosts distintos y contenido accesible. Duplicados, URLs
fuera de allowlist, fuentes inaccesibles y contenido generado por el propio
sistema se excluyen y aparecen con razón explícita. Dos fuentes son el mínimo.

Estados terminales:

```text
insufficient_sources conflicting_sources unverifiable candidate_created
```

Un conflicto queda `unresolved`; no se resuelve por mayoría. Solo un bundle con
fuentes suficientes, claims y sin conflicto crea una entrada `candidate` en el
Learning Pipeline. Research nunca marca learning validado ni memoria estable.

## Evidencia runtime

```bash
python scripts/run_phase_08_governed_research.py
```

Se ejecutaron runs separados para una fuente, conflicto 1:1 y dos fuentes
independientes con un tercer fetch fallido. Los seis invariantes pasaron: fuente
única insuficiente, conflicto no resuelto, candidato con fuentes independientes,
fallo visible, sin learning validado y sin memoria estable.

## Evidencia

```text
artifacts/triade_verify/phase_08/governed_research.json
```

## Validaciones

```text
python -m compileall -q triade apps scripts tests       pass
ruff format --check .                                   pass (752 archivos)
ruff check archivos Fase 8                              pass
pytest -q tests/test_governed_research.py                5 pass
pruebas dirigidas research                              9 pass
pytest -q                                               pass
pytest -q tests/operational_truth                        18 pass
python scripts/run_runtime_concurrency_test.py           pass
ruff check .                                            fail (813)
mypy triade                                             fail (224 en 68 archivos)
```

## Migración y rollback

La migración 024 solo crea `governed_research_runs`. La ruta legacy permanece
para compatibilidad, pero no constituye la autoridad de runs gobernados. El
rollback consiste en desactivar este productor sin borrar bundles ni candidatos.

## Riesgos y deuda

- El benchmark usa proveedores inyectados deterministas, no valida disponibilidad
  real de Internet ni calidad editorial de dominios públicos.
- La extracción de claims depende del adapter del proveedor; snippets sin claim
  estructurado terminan `unverifiable`.
- La validación del candidato corresponde exclusivamente a la Fase 9.
