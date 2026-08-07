# Herramientas de `scripts/` que se ejecutan a mano

Cada fichero de `scripts/` con un guard `__main__` es un entrypoint. El grafo
distingue tres estados, y la diferencia la decide **este documento**:

| estado | qué significa |
|---|---|
| `active` | algo lo arranca: Procfile, Dockerfile, systemd, workflow o `[project.scripts]` |
| `legacy` | nadie lo arranca, pero la documentación explica cómo ejecutarlo: es manual |
| `disconnected` | nadie lo arranca **y** nadie explica cómo ejecutarlo: indistinguible de código muerto |

Sólo `disconnected` cuenta como deuda, y es correcto que cuente: una herramienta
que nadie lanza y que nadie sabe invocar no se puede distinguir de un fichero
olvidado. La salida no es rebajar el detector, es declarar la intención.

Medido el 2026-08-07: 7 entrypoints `active`, 50 `legacy` y 17 `disconnected`.
Estos son esos 17.

---

## Auditorías (solo lectura)

No escriben en producción. Se ejecutan cuando alguien quiere una medición, no en
ningún ciclo.

```bash
python scripts/audit_learning_baseline.py
python scripts/audit_runtime_truth.py --db triade/memory/triade.db
python scripts/audit_neuron_candidates.py --runs-dir runs --limit 50 --json
python scripts/audit_primary_neuron_proposals.py --runs-dir runs --limit 50 --json
python scripts/audit_repo_baseline.py --skip-tests --json
```

`audit_learning_baseline.py` trabaja sobre una copia consistente hecha con
`Connection.backup()` y abre la base en `mode=ro`: no toca la Bodega viva.

## Triaje de deuda

```bash
python scripts/triage_debt.py --root . --db triade/memory/triade.db --output artifacts/triage
```

Clasifica cada hallazgo del informe de deuda en cinco clases con su evidencia
(`confirmed_break`, `incomplete_subsystem`, `legacy_expected`,
`detector_false_positive`, `resolved`). El informe dice *qué* está roto; esto
dice *de qué clase* es cada rotura. Es la herramienta a usar antes de abrir
cualquier bloque de deuda: escribe en la base, así que no es una auditoría.

## Construcción de bandejas de entrada

Generan un artefacto para revisión humana a partir de los runs.

```bash
python scripts/build_neuron_formation_inbox.py --runs-dir runs --limit 50 --out artifacts/inbox
python scripts/build_primary_neuron_proposal_inbox.py --runs-dir runs --limit 50 --out artifacts/inbox
```

## Migraciones y reparaciones puntuales

**Escriben en la base.** Se ejecutan una vez, con la intención explícita de
quien las lanza, nunca en un ciclo automático.

```bash
python scripts/backfill_neuron_missions.py --db triade/memory/triade.db --runs-dir runs
python scripts/remediate_synthetic_evidence.py --db triade/memory/triade.db
python scripts/register_existing_lora.py
python scripts/rollback_phase_11_model_routing.py --rollback
```

`rollback_phase_11_model_routing.py` restaura el baseline monomodelo de la fase
11; `--active` deja el enrutado multimodelo. Es un interruptor de vuelta atrás,
no una tarea.

## Sondas manuales de edge

Imprimen JSON por pantalla para inspeccionar a ojo. **No son pruebas**, aunque
el nombre lo sugiera: `testpaths = ["tests"]` en `pyproject.toml`, así que pytest
no las recoge nunca. El nombre `test_*` en `scripts/` induce a error y conviene
no imitarlo.

```bash
python scripts/test_edge_context.py
python scripts/test_edge_processing.py
python scripts/test_android_edge_router.py
```

## Procesos que se levantan a mano

### `federation_real_node.py`

Proceso HTTP mínimo para validar transporte federado real entre dos nodos.
Escribe en la base que se le indique. Se levanta a mano para una prueba de
federación y se para al terminar.

```bash
python scripts/federation_real_node.py --node-id a --peer-id b --port 8020 \
  --db triade/memory/triade.db --private-key ... --peer-public-key ...
```

### `triade_daemon.py` — no lo arranques junto a la app

Runtime **alternativo**: mantiene el pulso vital y el registro de nodos
federados *sin servidor web*. Usa `LifePulseEngine` y `NodeLiveRegistry`, que es
exactamente lo que `apps/single_port_app.py` ya arranca en su `lifespan`.

En este Studio el runtime es la app Single Port
([`STATUS_CURRENT.md`](../../STATUS_CURRENT.md#2--cómo-se-levanta)), así que el
daemon **no debe correr a la vez**: habría dos pulsos latiendo sobre la misma
base. Que aparezca como entrypoint sin lanzador no es un lanzador que falte; es
la otra mitad de una elección que ya está tomada.

Sólo tiene sentido en un despliegue sin HTTP:

```bash
python scripts/triade_daemon.py --db triade/memory/triade.db --pulse-interval 60
python scripts/triade_daemon.py stop
```
