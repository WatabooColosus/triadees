# Estado vigente de Tríade Ω · corte 2026-07-30

SHA documental base: `8f44814`. Esta es la fuente vigente después de
`TECHNICAL_DEBT.md`; los reportes antiguos son históricos si la contradicen.

## Dictamen

Tríade es un prototipo integrado de agente local gobernado. No es AGI, no se ha
demostrado conciencia subjetiva y no es autosuficiente. TRIADE-VERIFY-v1 es
`PARTIAL_SAFE`, no `VERIFIED_LOCAL`: faltan las ventanas reales 24/72 h y CI
verde registrado sobre el mismo SHA final.

## Implemented

- Cola runtime v2, lease/fencing, cierre atómico, postcondiciones, artifacts,
  effect receipts, cuarentena y rollback.
- Continuidad de identidad, `TriadicCycleTrace`, memoria longitudinal gobernada,
  relational modulation state PV-7, metacognición, research y learning receipts.
- Utility Ledger, certificación neuronal, LoRA/PEFT canary gobernado, federación
  firmada, autenticación/RBAC, sesiones y cuotas distribuidas con Redis.
- **Autonomía Delegada (FASE 8):** marco de autonomía por niveles
  (`observe_only → safe_write → project_maintenance → repo_refactor →
  full_local_guarded`, `triade/core/autonomy_budget.py`) con presupuesto por
  ciclo (archivos/bytes máximos), clasificación de rutas en zonas
  green/yellow/red/forbidden (`triade/core/system_zones.py`), operaciones de
  archivo seguras con backup/restore (`triade/core/safe_file_ops.py`),
  papelera con manifest recuperable en vez de borrado directo
  (`triade/core/quarantine_trash.py`), verificación de integridad
  pre/post-cambio (`triade/core/integrity_verifier.py`) y planificación de
  acciones delegadas (`triade/core/delegated_action_planner.py`). Expuesto en
  producción vía `/api/autonomy/budget`, `/api/system/zones`,
  `/api/delegated/plan`, `/api/trash/*`, `/api/files/*`
  (`apps/routes/api.py`, montado en `single_port_app.py`). 46 tests en
  `tests/test_autonomy_delegation.py`. Ningún nivel, ni siquiera el máximo,
  permite `delete_permanently`, `modify_identity_core`, `modify_git` ni
  `run_shell_free` sin aprobación humana — es una regla dura del propio
  presupuesto (`_forbidden_actions`/`_human_approval` en
  `autonomy_budget.py`), no una política externa.
- Backups Fernet, restore drills semanales, retención recuperable y runners
  chaos/24 h/72 h con métricas completas y procedencia por SHA.
- Certificador reproducible que no abre CI o long-run con evidencia de otro SHA.

## Runtime verified

- Web local y pública HTTP 200; Ollama 0.32.5 HTTP 200 con seis modelos. Always-On
  opera en `full_local_guarded`, `degraded=false`, y el self-test confirma
  `can_reason=true`.
- Ruff cero y mypy cero en 332 archivos, re-verificado 2026-07-30 sobre este
  SHA (`git ls-files '*.py' | xargs ruff check` y `mypy triade`, no una
  muestra). **Corrección de precisión:** en esta misma fecha se encontraron
  y corrigieron 17 errores reales de Ruff y 2 de mypy que sí existían en el
  código ya commiteado pese a esta afirmación previa — ver `TECHNICAL_DEBT.md`
  para la evidencia y el detalle de qué se corrigió. "Pytest completo al
  100%" no se re-verificó en esta sesión (no se corrió la suite completa por
  costo de tiempo); dos fallas puntuales preexistentes sí se encontraron y
  corrigieron con evidencia
  (`test_pid_reuse_identity_mismatch_recovers_lock`,
  `test_status_current_mentions_autonomy_delegation` — esta última se cierra
  con la sección "Autonomía Delegada" añadida arriba). No se afirma 100%
  sin haber corrido la suite completa sobre este SHA.
- Concurrencia: 101 tareas, 90 efectos, cero duplicados, cero artifacts ausentes,
  lease recuperada, todo contabilizado e integridad SQLite `ok`.
- Chaos aislado completo 15/15 con procesos Tríade reales y métricas de seguridad
  en sus umbrales. Disponibilidad no se atribuye a esta prueba.
- A/B multi-modelo real superó calidad monomodelo y se adoptó con rollback.
- Redis real compartió rate limit, sesiones y revocación entre dos réplicas.
- Restore drill cifrado validó identidad, SQLite, estados y 455 refs sin fallos;
  restore productivo no fue ejecutado.
- GitHub Actions completo estuvo verde en `00a05aa`; no certifica commits
  posteriores.

## Partial

- Long-run: implementación completa; 24/72 h deben iniciarse desde el SHA final
  y terminar sin reinicio. `long_run_verified=false`.
- CI: gates locales verdes y evidencia remota intermedia verde; falta SHA final.
  `ci_verified=false`.
- Legacy: reconciliación idempotente disponible; falta ventana productiva antes
  de retiro definitivo.
- Backups: un drill real y scheduler implementado; falta observar periodicidad y
  crecimiento durante semanas.
- Observabilidad y fronteras arquitectónicas: funcionales, no maduras a escala.

## Pending / external authority

- Aprobación nominal y tráfico real LoRA canary.
- Federación prolongada entre dos hosts distintos.
- Auditoría externa de prompt injection, abuso y network egress.
- Dominio, TLS, ingress y supervisor persistente fuera del Cloudspace.
- Protección real de `main`; GitHub API indica que todavía no está activa.
- Corpus independiente/multilingüe de memoria, aprendizaje complejo anti-overfit,
  utilidad semanal, capacidad máxima y SLO/RTO/RPO medidos.

## Reproducción

```bash
python -m compileall -q triade apps scripts tests
ruff check .
ruff format --check .
mypy triade
pytest -q
pytest -q tests/operational_truth
python scripts/run_runtime_concurrency_test.py
python scripts/run_triade_chaos_validation.py
python scripts/record_ci_evidence.py
python scripts/run_triade_verify.py
```

Operación y límites: `docs/operations/`. Deuda vigente:
`TECHNICAL_DEBT.md`.
