# Estado vigente de Tríade Ω · corte 2026-07-30

SHA documental base: `56b476d`. Esta es la fuente vigente después de
`TECHNICAL_DEBT.md`; los reportes antiguos son históricos si la contradicen.

## Dictamen

Tríade es un prototipo integrado de agente local gobernado. No es AGI, no se ha
demostrado conciencia subjetiva y no es autosuficiente. La certificación
TRIADE-VERIFY-v1 observada es `PARTIAL_SAFE`, no `VERIFIED_LOCAL`, porque faltan
operación prolongada y CI remota verde.

## Implementado

- Cola runtime v2 como autoridad canónica, reconciliación legacy idempotente y
  cierre atómico sujeto a lease, fencing, postcondición, artifact y receipt.
- Identity Manifest, verificación de continuidad, detección de alteración, modo
  degradado seguro, restore, endpoint y CLI read-only.
- `TriadicCycleTrace` con contribuciones de Central, Hipotálamo, Bodega, Cristal
  y Safety, más ablaciones deterministas.
- Memoria longitudinal por usuario/sesión/proyecto/dominio, procedencia,
  contradicción, supersesión, decay, explicación de recall y restore semántico.
- `relational modulation state` PV-7 longitudinal, aislado y reversible. No se
  describe como sentimiento humano.
- Registry de capacidades, calibración, gaps, research gobernado y learning
  receipts con baseline, evaluador independiente, transferencia, persistencia,
  regresión y rollback.
- Utility Ledger; gates de certificación neuronal; LoRA/PEFT canary gobernado;
  federación firmada; autenticación, RBAC, sesiones, cuotas y auditoría; backups
  cifrados con restore sandbox.
- Runners de chaos, 24 h y 72 h, y certificador reproducible con bundles
  hasheados.

## Verificado en runtime local

- Web pública y Ollama respondieron HTTP 200 en el corte. Ollama 0.32.5 ejecutó
  inferencia real y embeddings de 768 dimensiones; los modelos requeridos están
  instalados localmente.
- Suite pytest completa: código de salida 0. Operational truth: 18 pruebas
  aprobadas. Suite focal de migración/seguridad: 35 aprobadas.
- Concurrencia: 90 efectos, cero duplicados, cero artefactos ausentes, una lease
  recuperada, todas las tareas contabilizadas e integridad SQLite `ok`.
- El manifiesto `artifacts/triade_verify/20260730T002852Z/manifest.json` marca
  identidad, causalidad, memoria, ejecución, aprendizaje, rollback y federación
  como verdaderos con evidencia SHA-256.

## Parcial

- Multi-modelo: implementación disponible; falta A/B real que demuestre ventaja
  sobre un solo modelo.
- LoRA: canary técnico probado; faltan aprobación nominal y tráfico productivo
  controlado.
- Federación: dos procesos reales sobre TCP en el mismo host; falta operación
  sostenida entre hosts.
- Seguridad pública: autenticación real disponible; el rate limiting sigue siendo
  local al proceso y requiere backend distribuido para múltiples réplicas.
- Chaos/long-run: sub-suite corta aprobada; 24/72 h no ejecutadas.
- Calidad: pruebas dinámicas verdes, pero Ruff y mypy no están verdes.

## Pendiente para VERIFIED_LOCAL

- Completar 72 h reales y chaos completo con los umbrales de Fase 17.
- Dejar Ruff y mypy en cero sin desactivar reglas.
- Obtener GitHub Actions verde sobre el SHA candidato.

## Visión

- Federación sostenida entre hosts heterogéneos.
- Orquestación multi-modelo adoptada solo tras demostrar utilidad.
- Serving LoRA productivo con aprobación humana nominal y rollback operacional.
- Tríade OS sigue siendo un plano de control sobre Linux.

## Reproducción

```bash
python -m compileall -q triade apps scripts tests
ruff check .
ruff format --check .
mypy triade
pytest -q
pytest -q tests/operational_truth
python scripts/run_runtime_concurrency_test.py
python scripts/run_triade_verify.py
```

Operación y límites: `docs/operations/triade_verify.md`. Deuda vigente:
`TECHNICAL_DEBT.md`.
