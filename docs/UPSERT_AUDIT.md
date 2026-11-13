# Auditoría del patrón "asegurar que existe" que destruye estado

Origen: el defecto del registro neuronal (ver `docs/NEURON_FIELD_OWNERSHIP.md`).
Aquí se revisan los 21 `ON CONFLICT` de `triade/`, `apps/` y `scripts/` buscando
el mismo patrón: **una rutina que se ejecuta sola y periódicamente sobrescribe
estado que otro proceso aprendió, midió o aprobó**.

Criterio de clasificación:

- **Correcto** — última-escritura-gana sobre telemetría o instantáneas de
  estado, donde sobrescribir *es* la semántica deseada.
- **Dirección segura** — sobrescribe, pero sólo puede endurecer.
- **Riesgo** — puede degradar estado gobernado o borrar trabajo previo.

## Hallazgos

| módulo | fichero:línea | patrón | riesgo | severidad | acción |
|---|---|---|---|---|---|
| Neuron Registry | `core/neuron_registry.py:99` | `DO UPDATE` de las 14 columnas | borraba triggers, política y contrato en cada arranque | **P0** | **Arreglado** |
| Especializadas | `core/model_acquisition.py:308` | `register()` en bootstrap | idem, 2 neuronas | **P0** | **Arreglado** (`create_if_missing`) |
| Fundacionales | `core/foundational_neurons.py:119` | `register()` con triggers fijos en cada arranque | reescribía las 10 `stable` en cada reinicio | **P0** | **Arreglado** (`create_if_missing`) |
| Model Registry | `models/meta_orchestrator.py:334` | `status='discovered'` **fijo** en el conflicto | un redescubrimiento devuelve el modelo a `discovered`, perdiendo el estado del ciclo de vida | **P1** | Pendiente — mismo patrón, otro módulo |
| Federación | `federation/federation.py:210` | `status='active'` **fijo**; `trust_level` y `permissions` reemplazados | re-registrar un nodo lo reactiva y puede cambiar su confianza y permisos | **P1** | Pendiente — fuera del alcance declarado de este encargo |
| Semantic Store | `memory/semantic_store.py:138` | `status = excluded.status` al reingerir | un reingesta puede reponer el estado de gobernanza de un documento | **P2** | Revisar |
| Protection Registry | `regression/protection_registry.py:124` + `:255` | `install_core_defaults()` re-registra reglas | podría aflojar un umbral endurecido a mano | **P3** (latente) | **Sin caller de producción**; sólo se define |
| RegressionGate | `regression/gate.py:286` | `active=1, released_at=NULL` | dirección segura: re-poner en cuarentena | — | Correcto |
| Evidence Bridge | `learning/evidence_bridge.py:98` | update por `candidate_id` | dirigido por evento, no por arranque | — | Correcto |
| Learning validation | `learning/validation.py:131` | update por `learning_id` | idem | — | Correcto |
| Causal learning | `learning/causal_learning.py:270` | transición de estado con `previous_state` | append de transición explícita | — | Correcto |
| Metacognición | `capabilities/metacognition.py:76` | instantánea de disponibilidad | telemetría | — | Correcto |
| Scheduler / Workers | `workers/advanced_scheduler.py:566`, `workers/state_store.py` | heartbeat y clave-valor | telemetría | — | Correcto |
| Heartbeat / Event engine / Governed capability | `runtime/live_heartbeat.py`, `os/event_engine.py`, `runtime/governed_capability.py` | clave-valor singleton | telemetría | — | Correcto |
| System monitor | `core/system_monitor.py` | umbrales por `metric_name` | por revisar si hay bootstrap de defaults | **P3** | Revisar |
| LoRA / PEFT | `training/peft_canary.py`, `training/serving_governance.py` | slots de serving | fuera del alcance declarado | — | No tocado |

## Regla general que se deriva

Antes de escribir un `ON CONFLICT ... DO UPDATE`, responder tres preguntas:

1. **¿Quién ejecuta esto?** Si la respuesta incluye "el arranque" o "un bucle de
   fondo", no puede reemplazar campos que otro proceso enriquece.
2. **¿El valor entrante significa "esto es lo correcto" o "no me consta"?**
   Una dataclass que normaliza a `[]` o `{}` **no distingue** las dos cosas. Hace
   falta un sentinel explícito.
3. **¿Puede este UPSERT bajar un estado o aflojar una restricción?** Si sí, esa
   columna necesita una regla propia, no `excluded.*`.

Un literal fijo en el `DO UPDATE` (`status='active'`, `status='discovered'`,
`active=1`) es la señal más barata de este defecto: convierte cualquier
reescritura en una vuelta al estado de fábrica.

## Hallazgo adicional sobre la base de producción

Medido sobre copia de `triade/memory/triade.db`:

- `PRAGMA integrity_check` → `ok`.
- `PRAGMA foreign_keys` → **`0`** (la aplicación no fuerza claves ajenas por
  defecto; `NeuronRegistry._connect()` sí las activa en su conexión).
- `PRAGMA foreign_key_check` → **3435 violaciones** preexistentes.

No las introduce este cambio: el recuento es idéntico antes y después de las
operaciones auditadas. Queda anotado como deuda propia, no verificada en
detalle en este encargo.
