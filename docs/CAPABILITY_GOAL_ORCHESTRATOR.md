# Capability Resolver y Goal Orchestrator

Las órdenes operativas explícitas pasan por `CapabilityResolver`. El resolver no ejecuta texto arbitrario: produce una capacidad, riesgo, modo de ejecución, aprobación requerida y un tipo de worker conocido.

`GoalOrchestrator` crea un objetivo raíz y un paso persistente en `planning_graph`. Las investigaciones y comandos de diagnóstico, test o build permitidos se encolan en `worker_tasks`. Instalaciones y modificaciones del repositorio permanecen en `awaiting_approval`; no se traducen a shell libre.

Los workers actualizan el paso y el objetivo a `completed`, `failed` o `blocked` y conservan el resultado como evidencia en la tarea. Estado:

```text
GET /api/goals
GET /api/goals/{goal_id}
GET /api/runtime/workers-always-on/status
```

El runtime recupera un lock de worker únicamente cuando contiene un PID válido que ya no existe. Los locks malformados y los propietarios vivos fallan de forma segura. Durante la recuperación, runs antiguos quedan `interrupted`, tareas que estaban ejecutándose vuelven a `pending` y duplicados lógicos se marcan `skipped`.
