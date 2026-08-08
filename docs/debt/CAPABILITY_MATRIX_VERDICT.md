# `CapabilityMatrix` — cada parte, duplicada o imposible

Fecha: 2026-08-08 · bloque 3 del [plan de deuda](DEBT_TRIAGE_PLAN.md).
Veredicto: **REMOVE**.

`triade/capabilities/matrix.py` era el único módulo de producción sin importador
(213 líneas), y el único del paquete `triade/capabilities/` que su propio
`__init__.py` no exporta. Los otros seis sí, y todos tienen consumidor.

## Por qué se puede decidir ahora y antes no

El veredicto anterior ([`ORPHAN_MODULES_TRIAGE.md`](ORPHAN_MODULES_TRIAGE.md))
fue **retener**, y era correcto con la evidencia de entonces:

> `CapabilityMatrix.build()` lee `capability_registry`, que tiene **0 filas**.
> Conectarlo hoy devolvería una matriz vacía, que es peor que no tenerla: parece
> una respuesta.

Esa premisa ya no se sostiene. El lifespan llama a `bootstrap_core_capabilities()`
—fijado por `tests/test_capabilities_bootstrap_at_boot.py`— y el registro vivo
tiene cuatro capacidades núcleo. Con datos reales, la matriz se puede **medir**
en vez de suponer. Eso es lo que cambió.

## La medición, sobre el registro vivo

```json
{"total": 4, "active": 4, "critical_count": 4,
 "critical_without_baseline": 4, "without_rollback": 0,
 "quarantined": 0, "dependency_cycles": [], "health_score": 0.4}
```

Y con eso delante, cada parte se cae por un motivo distinto.

### 1 · Ciclos de dependencias → **imposible por construcción**

Era la única función que ningún otro módulo hacía. Y busca una forma que **no
puede existir**: `CapabilityRegistry.register()` valida y rechaza antes de
guardar.

```python
# triade/capabilities/registry.py:99
if self._would_create_cycle(definition.capability_id, definition.dependencies):
    raise ValueError("ciclo de dependencias detectado")
```

Ya está probado en `tests/test_capability_registry_history_cycles.py::
test_indirect_dependency_cycle_is_rejected`. `_detect_cycles()` devuelve `[]`
siempre — la misma figura que este repositorio persigue bajo el nombre
`dead_status_value`: una condición cuya respuesta está decidida de antemano.

### 2 · `without_rollback` → **imposible por construcción, otra vez**

```python
# triade/capabilities/registry.py:49
if self.critical and (not self.evaluation_suites or not self.rollback_policy):
    raise ValueError("capacidad crítica requiere suite y rollback")
```

Una capacidad crítica sin `rollback_policy` no llega a registrarse. El contador
no podía pasar de cero por buena salud: no podía pasar de cero.

### 3 · `critical_without_baseline` → **duplicado, y en peor sitio**

`MandatoryRollbackEnforcer` calcula exactamente lo mismo
(`_has_stable_baseline`), y además **aplica** la regla: `enforce_before_promotion`
bloquea la promoción de una capacidad crítica sin baseline (Artículo III), y lo
llama el pipeline de aprendizaje. La matriz producía el número sin poder hacer
nada con él.

### 4 · Recuentos por estado, dominio y criticidad → **duplicado**

`CapabilityObservability.snapshot()`, con consumidor vivo:
`triade/core/observability_view.py` → `apps/routes/api.py`.

### 5 · `quarantined` → **constante**

`CapabilityNode.quarantined` es `False` por defecto y **nadie lo asigna nunca**.
El contador es cero por definición, y entra en `health_score` restando `0.1` por
cada uno: un término que no puede activarse.

### 6 · Una línea sin efecto

```python
len(nodes) or 1   # matrix.py:159 — el valor se descarta
```

Una expresión cuyo resultado no se usa. No cambia nada; lo que dice es que este
código no llegó a ejecutarse nunca donde alguien mirara.

## Lo que **no** es este veredicto

No es «sobra medir la salud de las capacidades». `critical_without_baseline: 4`
es un hallazgo **real y serio**: las cuatro capacidades núcleo declaran suite y
política de rollback, y ninguna tiene baseline al que volver. Eso es deuda, y se
trata en su sitio —`stable_capability_state`, bloque 7—, no aquí.

Lo que se retira es una **segunda implementación** de ese juicio, sin consumidor,
con dos de sus cinco contadores imposibles por construcción y uno constante.
Conectarla no habría añadido una medición: habría añadido una segunda voz sobre
lo mismo, sin autoridad entre las dos.

## Copia previa

`artifacts/dead_code_backup/capability-matrix-20260808T191629Z.tar.gz`, con
manifiesto JSON (SHA-256, bytes, líneas), siguiendo la misma convención que
`plan_step.py` y `hierarchical_pulse.py`. Git conserva además el historial: dos
vías de recuperación.

## Las razones, hechas prueba

`tests/test_capability_matrix_retired.py` no comprueba que el fichero no exista
—eso lo dice `git`— sino que **las tres razones siguen siendo ciertas hoy**: que
el registro rechaza ciclos al escribir, que rechaza una crítica sin rollback, y
que el juicio sobre baseline y los recuentos tienen dueño vivo. Si alguna deja de
cumplirse, la retirada deja de estar justificada y hay que volver a decidir.
