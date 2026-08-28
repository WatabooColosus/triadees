# Retirada de la isla legacy T-007..T-024

Fecha de decisión: 2026-08-28.

El grafo de imports mostró una isla de quince implementaciones enlazadas sólo
entre `triade/dashboard/routes.py`, `triade/integration/final_validator.py` y
`triade/os/triadeos_complete.py`. Ningún entrypoint arrancado alcanzaba la isla.

La comprobación sobre `triade/memory/triade.db` encontró ausentes las 42 tablas
que esos módulos habrían creado. Por tanto, no había filas ni historial que
migrar. Conectar la isla habría duplicado componentes que ya tienen tránsito:

| Retirado | Reemplazo canónico vivo |
|---|---|
| `core/system_monitor.py` | `runtime/service_health.py` + `hypothalamus/senses.py` |
| `dashboard/routes.py` | `apps/routes/api.py`, `health.py`, `ui.py` |
| `evaluation/advanced_evaluation.py` | `evaluation/runner.py` y suites medibles |
| `federation/federation_advanced.py` | `federation/federation.py` + transporte firmado |
| `integration/final_validator.py` | `verification/certification.py` y health vivo |
| `learning/causal_learning.py` | `learning/evidence_producer.py` + `retrieval.py` |
| `memory/replacement_tracker.py` | `memory/semantic_governance.py` |
| `models/smart_router.py` | `models/model_router.py` |
| `neuron_factory/design.py` | `neuron_factory/specification.py` |
| `neuron_factory/training.py` | `neuron_factory/execution.py` + `training/` |
| `os/autonomous_routines.py` | `core/life_pulse.py` + workers gobernados |
| `os/triadeos_complete.py` | `os.TriadeOS` canónico |
| `sandbox/enhanced_tool_registry.py` | `sandbox/policy.py` + executor vivo |
| `workers/advanced_scheduler.py` | `workers/scheduler.py` + `runtime/task_leases.py` |
| `workers/worker_supervisor.py` | `workers/state_store.py` + `runtime/service_health.py` |

El caso más peligroso era `advanced_scheduler.py`: declaraba su propia tabla
`task_leases` con un esquema distinto al almacén canónico. Importarlo para
“conectarlo” habría creado dos autoridades sobre el lease de una tarea.

La prueba `test_legacy_runtime_island_retired.py` fija ambas condiciones: los
gemelos no reaparecen y cada reemplazo canónico sigue presente.
