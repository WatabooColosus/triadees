# `neuron_certifications` — el lector apuntaba a un contrato que ya se sustituyó

Fecha: 2026-08-08 · bloque 2 del [plan de deuda](DEBT_TRIAGE_PLAN.md).

`alias_debt` la señalaba como `orphan_reader`, y con razón:

```text
neuron_certifications: 1 lector, 0 escritores, 0 filas
```

Es el único `orphan_reader` que suma al contador: los otros 27 hallazgos hablan
de tablas que ya cuentan otras categorías. Aquí el caso es distinto y más raro —
no es que el escritor no se ejecute, es que **no existe ninguno**.

## El lector actual

`NeuronCertifier.audit_stable()` (`triade/neuron_factory/certification.py:44`),
con un `LEFT JOIN` a la certificación más reciente de cada neurona `stable`.

Quién lo llamaba: **una sola cosa**,
`scripts/run_phase_12_neuron_certification.py`, marcado `legacy` en el grafo de
entrypoints con **0 lanzadores**. Y ese script no es un servicio: es el runner de
una fase que ya terminó.

```text
docs/audits/phase_12_neuron_certification.md
  Fecha UTC: 2026-07-29 · Estado: completed
  «La base runtime contenía 13 neuronas stable. Ninguna tenía manifest de
   certificación, por lo que las 13 se pusieron en quarantined.»
```

Las 13 transiciones siguen en la base. La condición de éxito del propio runner
—`before["stable_count"] == 13`— está escrita a mano en el fichero: es un
one-shot, no un bucle.

## La semántica esperada

Un **manifiesto firmado**: versión, owner, misión, dominio, fuentes y acciones
permitidas, benchmarks, baseline, evidencia, limitaciones, `rollback_ref`,
confianza, revisión, más seis puertas booleanas (`independent_evaluation`,
`regressions_green`, `rollback_verified`, `restart_verified`, `benchmark_passed`,
`evidence_complete`).

Alguien tenía que producir ese documento. Nadie lo produjo nunca, ni había por
dónde: no hay endpoint, ni handler, ni CLI que inserte una fila.

## El contrato canónico actual

`triade/core/stable_neuron_audit.py` responde la **misma pregunta** —¿esta
neurona `stable` se sostiene?— con otra fuente de verdad:

| | manifiesto (`NeuronCertifier`) | evidencia medida (`stable_neuron_audit`) |
|---|---|---|
| entrada | fila firmada a mano en `neuron_certifications` | activaciones, diagnósticos y planes de prueba reales |
| umbral | seis booleanos que alguien marca | `min_activations` 5, `min_diagnosis` 5, `min_test_plan` 3 |
| salida | `quarantined` | `experimental` o `needs_review` |
| registro | `neuron_certification_transitions` | evento `stable_neuron_audit_applied` |
| aplicar | `apply_quarantine()` | `apply=True` explícito, read-only por defecto |
| consumidores | 1, un script de fase `completed` | 5 vivos: `apps/routes/api.py` (×3), `neuron_dashboard`, `living_report`, `bodega_global_context` |

La función sobrevivió; lo que se sustituyó fue **de dónde sale la prueba**. Y el
cambio va en la dirección correcta para este repositorio: de un papel que alguien
firma a una medición que se puede repetir.

## Diferencia entre ambos, dicha sin rodeos

El viejo contrato preguntaba *«¿hay un documento?»*. El nuevo pregunta *«¿hay
actividad que lo respalde?»*. El viejo, con la tabla vacía, respondía siempre
`certification_manifest_missing` — es decir, habría puesto en cuarentena a
**cualquier** neurona `stable`, para siempre. Eso no es un gate: es un `False`
constante con pasos intermedios.

## Decisión: `REMOVE_READER`

No `RESTORE_CANONICAL_TABLE`: restaurarla exigiría construir el productor del
manifiesto, y la capacidad que ese productor daría **ya existe** medida de otra
forma. Construirla otra vez sería duplicar el juicio sobre `stable`, con dos
respuestas posibles y ninguna autoridad entre ellas.

No `MIGRATE_READER`: no hay a dónde migrarlo. El lector completo sobra, porque su
consumidor sobra.

Se retiran, en un solo acto:

- `triade/neuron_factory/certification.py` — nunca estuvo en el `__init__` del
  paquete; no formaba parte del contrato público de la fábrica de neuronas;
- `scripts/run_phase_12_neuron_certification.py` — runner de fase `completed`;
- `tests/test_neuron_certification.py` — probaba sólo lo retirado;
- la tabla `neuron_certifications`, con `035_retire_neuron_certifications.sql`.

## Lo que **no** se retira

`neuron_certification_transitions`, con sus 13 filas. Son el registro de un
cambio real de estado del organismo —13 neuronas pasaron a `quarantined` el
2026-07-29— y cada una conserva su `rollback_ref`. Borrar eso sería borrar
evidencia histórica.

Su `CREATE TABLE` se muda de `028` a `schemas.sql`, porque quien reejecutaba
`028` era justo el módulo retirado. `schemas.sql` sí se reejecuta en cada
arranque (`IdentityContinuity._ensure_base_schema`).

Al perder su escritor pasa a **bitácora histórica**: 13 filas, ningún escritor
vivo, ningún lector. El detector todavía no sabe decir eso —lo contará como
deuda hasta que exista la capa de contratos verificados— y esa es la pieza que
abre el bloque 5. Mientras tanto, **cuenta**, y está bien que cuente: una
categoría que se calla lo que no entiende es peor que una que se equivoca en voz
alta.

## Identidad

`035` sube `schema_version` de `034` a `035`, así que la retirada **es una
operación de identidad**, no sólo de esquema: sin rebasar el ancla por la vía
gobernada (`IdentityContinuity.migrate_anchor()`, con `approved_by` y `reason`),
el runtime arranca en `degraded_safe_identity_mismatch` —sin workers, sin
always-on, sin metabolismo— y responde 200 igualmente. Es la lección que costó
siete intentos en el bloque B.
