# Políticas explícitas de runtime

## Objetivo

Las capacidades degradadas y las compatibilidades públicas deben declararse en el módulo que las ejecuta. Los archivos `__init__.py` solo exponen símbolos y no modifican clases, funciones o estados globales durante el import.

## Workers

`WorkerLoop.READ_ONLY_TASKS_WITHOUT_BLOOD` declara de forma inmutable las tareas locales que pueden ejecutarse cuando Ollama Blood no está disponible. `pending_learning_review` puede operar en ese modo porque utiliza sandbox local determinista, mantiene bloqueo de cambios sobre `identity_core` y no consolida memoria estable automáticamente.

## Supervisor

`InternalRuntimeSupervisor._governed_mission_service` conserva el bloqueo total cuando el gobernador no permite workers. Cuando sí los permite, delega en el ciclo de nutrición, que decide si existe una misión activa y segura o si debe degradarse a `observe_only`.

## API

Los normalizadores `_legacy_ollama_status` y `_legacy_heartbeat_truth` viven en `apps.routes.api`. Las rutas públicas los aplican explícitamente y conservan los valores internos en `internal_status` e `internal_heartbeat_truth`.

## Garantías

- no hay monkey patching durante imports;
- no se habilitan shell ni red;
- no se modifica el núcleo de identidad;
- no se escribe memoria estable sin el pipeline de validación;
- los imports son idempotentes;
- la compatibilidad pública no presenta degradación como éxito.
