# Ciclo de Vida de Neuronas · Tríade Ω

## Estado

Este documento describe el ciclo verificable de creación, formación, activación, evaluación y promoción de neuronas dentro de Tríade Ω.

## Principio central

Las neuronas pueden ser propuestas por el sistema, pero no pueden activarse ni estabilizarse sin gobernanza humana y evidencia verificable.

```text
sistema propone
→ N Creadora genera contrato
→ N Formadora evalúa
→ humano decide
→ experimental
→ runtime diagnóstico
→ evidence ledger
→ stable readiness
→ promotion gate humano
→ stable
```

## Estados

```text
raw_candidate
candidate
experimental
needs_changes
rejected
stable
```

## 1. Propuesta primaria

Las propuestas primarias nacen desde el ciclo `TriadeRunner.run()` cuando la Central detecta una necesidad de creación o actualización de neurona.

Archivo principal: `triade/core/primary_neuron_pipeline.py`.

La propuesta debe incluir `creator_spec`, `training_result`, `contracts`, `activation_policy`, `success_metrics`, `evidence_required` y `proposal_quality`.

Regla: ninguna propuesta primaria puede nacer como `stable`.

## 2. N Creadora y N Formadora

La N Creadora define nombre, misión, dominio, reglas, triggers, entradas permitidas, salidas permitidas, acciones prohibidas, métricas de éxito y evidencia requerida.

La N Formadora evalúa score, estado recomendado, fortalezas, advertencias, recomendaciones y revisión humana requerida.

## 3. Decision Gate humano

Script: `scripts/decide_primary_neuron.py`.

Acciones permitidas:

```text
approve          → experimental
reject           → rejected
request-changes  → needs_changes
```

Acción prohibida desde este gate: `stable`.

Política: `human_decision_required_no_auto_stable`.

## 4. Runtime experimental

Archivo: `triade/core/experimental_neuron_runtime.py`.

Una neurona experimental puede observar, diagnosticar, proponer `test_plan` y emitir `audit_summary`.

No puede modificar respuesta visible, modificar repositorio, escribir memoria estable, ejecutar acciones externas ni promoverse a sí misma.

Artifact por run: `experimental_neuron_activity.json`.

## 5. Evidence Ledger

Archivo: `triade/core/experimental_neuron_evidence.py`.

Script: `scripts/audit_experimental_neuron_evidence.py`.

Resume `activation_count`, `diagnosis_count`, `test_plan_count`, `last_run_id`, `policy` y `promotion_blockers`.

Política: `evidence_only_no_auto_promotion`.

## 6. Stable Readiness

Archivo: `triade/core/stable_promotion_readiness.py`.

Script: `scripts/audit_stable_promotion_readiness.py`.

Evalúa si una neurona experimental tiene evidencia suficiente para revisión estable.

Umbrales iniciales:

```text
min_activations = 5
min_diagnosis = 5
min_test_plan = 3
```

Política: `readiness_only_no_auto_stable`.

Este auditor no promueve neuronas.

## 7. Promotion Gate a stable

Script: `scripts/promote_neuron_stable.py`.

Requisitos:

```text
status actual = experimental
ready_for_stable_review = true
--confirm-human obligatorio
razón humana explícita
evidencia acumulada
```

Política: `stable_requires_evidence_and_explicit_human_confirmation`.

## 8. Pulso Vivo

`apps/single_port_app.py` expone en `/api/system/pulse`:

```text
experimental_neurons
stable_readiness
```

Esto permite ver neuronas experimentales con evidencia, última neurona activa, cantidad de activaciones, readiness para revisión stable y bloqueadores actuales.

## 9. Tests asociados

```text
tests/test_neuron_governance_cycle.py
tests/test_experimental_neuron_runtime.py
tests/test_stable_promotion_readiness.py
tests/test_promote_neuron_stable.py
```

Estos tests blindan contrato completo, no auto-stable, activación solo experimental, evidence ledger, readiness sin promoción y promotion gate con confirmación humana.

## Reglas rígidas

```text
1. Ninguna neurona se estabiliza automáticamente.
2. Ninguna neurona experimental ejecuta acciones externas.
3. Ninguna neurona escribe memoria estable por sí sola.
4. Toda promoción requiere evidencia + decisión humana.
5. Toda actividad debe dejar artifact auditable.
6. Toda nueva capacidad debe tener test.
```

## Baseline actual

La primera neurona aprobada como experimental es:

```text
neurona-verifica-estado-actual
domain: federation_android_edge
status: experimental
```

Su función inicial es auditar coherencia entre Android edge, pulse context, edge usage y deuda federada.
