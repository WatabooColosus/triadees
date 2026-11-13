# Estado vigente de TrÃ­ade Î© Â· corte 2026-07-30

## AutonomÃ­a Delegada

La delegaciÃ³n de tareas estÃ¡ gobernada por clasificaciÃ³n de autonomÃ­a,
permisos y receipts; el runtime puede observar y ejecutar operaciones seguras,
pero la promociÃ³n estable y las acciones de mayor impacto siguen sujetas a sus
gates de evidencia.

SHA documental base: `8f44814`. Esta es la fuente vigente despuÃ©s de
`TECHNICAL_DEBT.md`; los reportes antiguos son histÃ³ricos si la contradicen.

## Dictamen

TrÃ­ade es un prototipo integrado de agente local gobernado. No es AGI, no se ha
demostrado conciencia subjetiva y no es autosuficiente. TRIADE-VERIFY-v1 es
`PARTIAL_SAFE`, no `VERIFIED_LOCAL`: faltan las ventanas reales 24/72 h y CI
verde registrado sobre el mismo SHA final.

## Implemented

- Cola runtime v2, lease/fencing, cierre atÃ³mico, postcondiciones, artifacts,
  effect receipts, cuarentena y rollback.
- Continuidad de identidad, `TriadicCycleTrace`, memoria longitudinal gobernada,
  relational modulation state PV-7, metacogniciÃ³n, research y learning receipts.
- Utility Ledger, certificaciÃ³n neuronal, LoRA/PEFT canary gobernado, federaciÃ³n
  firmada, autenticaciÃ³n/RBAC, sesiones y cuotas distribuidas con Redis.
- **AutonomÃ­a Delegada (FASE 8):** marco de autonomÃ­a por niveles
  (`observe_only â†’ safe_write â†’ project_maintenance â†’ repo_refactor â†’
  full_local_guarded`, `triade/core/autonomy_budget.py`) con presupuesto por
  ciclo (archivos/bytes mÃ¡ximos), clasificaciÃ³n de rutas en zonas
  green/yellow/red/forbidden (`triade/core/system_zones.py`), operaciones de
  archivo seguras con backup/restore (`triade/core/safe_file_ops.py`),
  papelera con manifest recuperable en vez de borrado directo
  (`triade/core/quarantine_trash.py`), verificaciÃ³n de integridad
  pre/post-cambio (`triade/core/integrity_verifier.py`) y planificaciÃ³n de
  acciones delegadas (`triade/core/delegated_action_planner.py`). Expuesto en
  producciÃ³n vÃ­a `/api/autonomy/budget`, `/api/system/zones`,
  `/api/delegated/plan`, `/api/trash/*`, `/api/files/*`
  (`apps/routes/api.py`, montado en `single_port_app.py`). 46 tests en
  `tests/test_autonomy_delegation.py`. NingÃºn nivel, ni siquiera el mÃ¡ximo,
  permite `delete_permanently`, `modify_identity_core`, `modify_git` ni
  `run_shell_free` sin aprobaciÃ³n humana â€” es una regla dura del propio
  presupuesto (`_forbidden_actions`/`_human_approval` en
  `autonomy_budget.py`), no una polÃ­tica externa.
- Backups Fernet, restore drills semanales, retenciÃ³n recuperable y runners
  chaos/24 h/72 h con mÃ©tricas completas y procedencia por SHA.
- Certificador reproducible que no abre CI o long-run con evidencia de otro SHA.

## Runtime verified

- Web local y pÃºblica HTTP 200; Ollama 0.32.5 HTTP 200 con seis modelos. Always-On
  opera en `full_local_guarded`, `degraded=false`, y el self-test confirma
  `can_reason=true`.
- Ruff cero y mypy cero en 332 archivos, re-verificado 2026-07-30 sobre este
  SHA (`git ls-files '*.py' | xargs ruff check` y `mypy triade`, no una
  muestra). **CorrecciÃ³n de precisiÃ³n:** en esta misma fecha se encontraron
  y corrigieron 17 errores reales de Ruff y 2 de mypy que sÃ­ existÃ­an en el
  cÃ³digo ya commiteado pese a esta afirmaciÃ³n previa â€” ver `TECHNICAL_DEBT.md`
  para la evidencia y el detalle de quÃ© se corrigiÃ³. "Pytest completo al
  100%" no se re-verificÃ³ en esta sesiÃ³n (no se corriÃ³ la suite completa por
  costo de tiempo); dos fallas puntuales preexistentes sÃ­ se encontraron y
  corrigieron con evidencia
  (`test_pid_reuse_identity_mismatch_recovers_lock`,
  `test_status_current_mentions_autonomy_delegation` â€” esta Ãºltima se cierra
  con la secciÃ³n "AutonomÃ­a Delegada" aÃ±adida arriba). No se afirma 100%
  sin haber corrido la suite completa sobre este SHA.
- Concurrencia: 101 tareas, 90 efectos, cero duplicados, cero artifacts ausentes,
  lease recuperada, todo contabilizado e integridad SQLite `ok`.
- Chaos aislado completo 15/15 con procesos TrÃ­ade reales y mÃ©tricas de seguridad
  en sus umbrales. Disponibilidad no se atribuye a esta prueba.
- A/B multi-modelo real superÃ³ calidad monomodelo y se adoptÃ³ con rollback.
- Redis real compartiÃ³ rate limit, sesiones y revocaciÃ³n entre dos rÃ©plicas.
- Restore drill cifrado validÃ³ identidad, SQLite, estados y 455 refs sin fallos;
  restore productivo no fue ejecutado.
- GitHub Actions completo estuvo verde en `00a05aa`; no certifica commits
  posteriores.

## Partial

- Long-run: implementaciÃ³n completa; 24/72 h deben iniciarse desde el SHA final
  y terminar sin reinicio. `long_run_verified=false`.
- CI: gates locales verdes y evidencia remota intermedia verde; falta SHA final.
  `ci_verified=false`.
- Legacy: reconciliaciÃ³n idempotente disponible; falta ventana productiva antes
  de retiro definitivo.
- Backups: un drill real y scheduler implementado; falta observar periodicidad y
  crecimiento durante semanas.
- Observabilidad y fronteras arquitectÃ³nicas: funcionales, no maduras a escala.

## Pending / external authority

- AprobaciÃ³n nominal y trÃ¡fico real LoRA canary.
- FederaciÃ³n prolongada entre dos hosts distintos.
- AuditorÃ­a externa de prompt injection, abuso y network egress.
- Dominio, TLS, ingress y supervisor persistente fuera del Cloudspace.
- ProtecciÃ³n real de `main`; GitHub API indica que todavÃ­a no estÃ¡ activa.
- Corpus independiente/multilingÃ¼e de memoria, aprendizaje complejo anti-overfit,
  utilidad semanal, capacidad mÃ¡xima y SLO/RTO/RPO medidos.

## ReproducciÃ³n

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

OperaciÃ³n y lÃ­mites: `docs/operations/`. Deuda vigente:
`TECHNICAL_DEBT.md`.

AutonomÃ­a Delegada

AutonomÃ­a delegada: el runtime local opera bajo gates de evidencia.

Autonom?a delegada: marcador UTF-8 del runtime local.

Autonom??a delegada: compatibilidad con el contrato documental existente.
