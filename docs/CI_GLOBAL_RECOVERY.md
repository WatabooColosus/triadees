# Recuperación de CI global

## Contexto

La suite global presenta nueve fallos agrupados en cuatro subsistemas: nutrición de misiones, contadores del supervisor, workers de aprendizaje y contratos de estado expuestos por API.

Este trabajo se separa del PR del cuerpo cognitivo para evitar mezclar regresiones preexistentes con una funcionalidad nueva.

## Estrategia

1. Corregir primero comportamiento real y seguro.
2. Mantener degradación explícita cuando Ollama no está disponible.
3. Permitir solo ejecución local determinista sin modelo.
4. Prohibir escritura de memoria estable y aprendizaje validado sin evidencia.
5. Actualizar pruebas solo cuando el contrato nuevo sea intencional y documentado.
6. Resolver cada grupo en commits pequeños y verificables.

## Bloque 1 · Nutrición neuronal degradada

La ausencia de Ollama no debe convertir toda misión en observación cuando la misión usa acciones locales seguras como:

- `observe`;
- `diagnose`;
- `propose_learning`.

La ejecución degradada puede producir ciclos y evidencia operativa, pero no debe:

- afirmar que hubo razonamiento de modelo;
- consolidar memoria estable;
- validar aprendizaje automáticamente;
- modificar el núcleo de identidad.

## Bloque 2 · Supervisor y contadores

El supervisor debe mantener contadores consistentes para:

- tareas planificadas;
- tareas ejecutadas;
- misiones ejecutadas;
- candidatos creados.

Si el gobernador limita nutrición, la planificación aún debe reflejarse en `tasks_planned`.

## Bloque 3 · Workers de aprendizaje

Los workers deben procesar candidatos de forma explícita:

- contenido seguro y útil → evaluación y verificación;
- intento de modificar identidad → rechazo;
- ninguna transición sin evidencia registrada.

## Bloque 4 · Contratos de API

Los estados nuevos deben documentarse y conservar compatibilidad cuando sea posible:

- `degraded_no_ollama`;
- `light_background`;
- mensajes `heartbeat_truth` derivados del gobernador.

## Criterio de cierre

```bash
pytest -q
```

Además:

- `Python Tests` verde;
- `Tríade Tests` verde;
- cero debilitamiento artificial de pruebas;
- cambios de contrato documentados;
- identidad y memoria estable protegidas.
