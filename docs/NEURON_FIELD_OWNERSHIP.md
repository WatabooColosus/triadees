# Propiedad de campos del registro neuronal

> Estado: vigente desde el arreglo de `register()` (rama
> `feat/governed-concurrency-and-self-improvement`).
> Código: `triade/core/neuron_registry.py`, constante `_FIELD_POLICY`.

## El problema que resuelve

`NeuronRegistry.register()` mezclaba tres operaciones distintas —crear,
actualizar y asegurar-que-existe— en un único `INSERT ... ON CONFLICT(name) DO
UPDATE` que reemplazaba **todas** las columnas con las del `NeuronSpec`
entrante.

`NeuronSpec` es una dataclass que normaliza cada lista ausente a `[]`. Por eso
un spec que no dice nada sobre `triggers` no llegaba a SQLite como "no tengo
opinión", sino como "ponlo vacío".

`ensure_specialized_model_neurons()` se ejecuta en cada arranque y re-registra
`Neurona Visual` y `Neurona de Código y Reparación` desde specs fijos que no
declaran triggers. El resultado, medido sobre una copia de la base real:

| momento | Neurona Visual | Neurona de Código y Reparación |
|---|---|---|
| tras aprender | 7 triggers | 8 triggers |
| tras **un** arranque | 0 | 0 |

Una rutina llamada "asegurar que existe" estaba devolviendo las neuronas al
estado de fábrica en cada reinicio.

## La regla

**Un campo omitido no es una orden de borrado.** El silencio de un llamante se
conserva; sólo una declaración explícita cambia estado.

## Tabla de propiedad

| campo | propietario | ¿puede tocarlo un arranque? | regla de merge |
|---|---|---|---|
| `id` | la base | no | inmutable |
| `name` | clave lógica | no | inmutable; identifica la fila |
| `created_at` | la base | no | inmutable |
| `created_by` | quien la creó | no | `KEEP_ORIGIN`: la procedencia no se reescribe, ni con `replace_definition` |
| `mission` | declarativo (spec) | sí | `DECLARATIVE`: el spec manda |
| `domain` | declarativo (spec) | sí | `DECLARATIVE`: el spec manda |
| `rules` | declarativo | sólo si las declara | `PRESERVE_IF_SILENT` |
| `triggers` | **aprendido** | no en silencio | `PRESERVE_IF_SILENT` |
| `activation_policy` | **aprendido** | no en silencio | `PRESERVE_IF_SILENT` |
| `contract_json` | pipeline enriquecedor | no en silencio | `PRESERVE_IF_SILENT`; el silencio lo marca `contract_payload is None`, no el valor |
| `success_metrics` | declarativo | sólo si los declara | `PRESERVE_IF_SILENT` |
| `inputs_allowed` | **permiso** | sólo si los declara | `PRESERVE_IF_SILENT`, **reemplazo y nunca unión**: unir ampliaría privilegios |
| `outputs_allowed` | **permiso** | sólo si los declara | igual que `inputs_allowed` |
| `forbidden_actions` | **seguridad** | sí, para añadir | `NEVER_REDUCE`: unión. Un arranque puede añadir restricciones, jamás quitarlas |
| `evidence_required` | **seguridad** | sí, para añadir | `NEVER_REDUCE`: unión |
| `status` | gobernanza | sólo hacia arriba | `NO_DOWNGRADE`: un re-registro mantiene o promueve; bajar exige `update_status()` |
| `updated_at` | la base | sólo si hubo cambio | se recalcula en SQL comparando el valor final con el existente |

### Orden de estados

`rejected` (0) · `quarantined` (5) · `candidate_detected` (10) · `candidate`
(15) · `candidate_reviewable` (20) · `needs_changes` (25) · `experimental` (30)
· `trusted_worker` (40) · `active_assistant` (45) · `stable` (50).

Un estado desconocido vale 10, de modo que no puede degradar a uno conocido y
superior por accidente.

## API

```python
registry.create_if_missing(spec)          # arranques: si existe, no toca nada
registry.register(spec)                    # por defecto: preserve_learned
registry.register(spec, conflict_policy="replace_definition")   # sobrescritura deliberada
registry.register(spec, explicit_fields={"triggers"})           # vaciar a propósito
registry.update_status(name, "quarantined")                     # única vía para degradar
```

`explicit_fields` existe porque `NeuronSpec` no puede distinguir por valor entre
«no tengo opinión» y «quiero que esté vacío». El sentinel es el nombre del campo,
no el contenido.

## Invariantes verificadas

`tests/test_neuron_registry_preserves_learning.py` (5 casos) y
`tests/test_neuron_registry_field_ownership.py` (18 casos). 15 de esos 18 fallan
contra el commit anterior al arreglo, así que no pasan en vacío.

Sobre copia de la base real (`runs/neuron-registry-preservation/`): tras dos
arranques consecutivos, **cero diferencias** en las 17 columnas de ambas
neuronas, con `PRAGMA integrity_check = ok`.

## Lo que este arreglo NO hace

- No recupera los triggers que producción ya perdió. Sólo evita la próxima
  pérdida; el aprendizaje debe volver a producirse.
- No toca las demás rutinas `ensure_*` del repositorio. La auditoría del mismo
  patrón está en `docs/UPSERT_AUDIT.md`.
- No cambia `update_status()`, que sigue siendo la ruta gobernada de promoción
  y degradación.
