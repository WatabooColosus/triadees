# Auditoría de verdad operacional — 2026-07-29

Base inspeccionada: servicio local y SQLite sobre la rama derivada de `8b82562`.

## Dictamen por órgano

| Órgano | Real | Límite actual |
|---|---|---|
| Central | Construye planes y respuestas; Ollama respondió correctamente en 37 eventos | Sus `PlanStep` no ejecutan herramientas; `_simulate_step` es solo un helper no conectado al runner |
| Hipotálamo | Produce y persiste `SignalPacket`; 70 señales observadas, con Ollama y fallback de reglas | Sus emociones son variables operacionales, no experiencia subjetiva |
| Cristal | Calcula y persiste Q, estabilidad, intensidad y estado temporal por run | Es una fórmula de regulación; no verifica verdad externa |
| Qualia | Enruta experiencias a señal, Central y almacenamiento | 904 experiencias provenían de workers; cantidad no equivale a aprendizaje |
| Bodega | Conserva runs, episodios, señales, cristal y artefactos entre sesiones | No había memoria semántica stable; además almacenó pulsos sintéticos como episodios/candidatos |
| Workers | Ejecutan tareas y generan artefactos reales | Gran parte era revisión repetida, heartbeat con Qualia o misión autorreferencial |
| Investigación | 5 investigaciones produjeron candidato | 30 terminaron sin evidencia; no existe investigación profunda fiable continua |
| Educación | 8 sesiones trazadas | 6 sin material y 2 inciertas; cero aprendizaje aprobado |

## Falsos positivos encontrados

- MissionExecutor puntuaba sus propios ciclos usando evidencia creada por él mismo; se observaron scores repetidos de 0,908.
- Los 523 candidatos `internally_checked` generaban revisiones recurrentes aunque no tenían evidencia de uso.
- Heartbeats y revisiones vacías publicaban paquetes Qualia.
- Runs `system_pulse_continuous` se convertían en memoria candidata y aprendizaje post-run.
- La activación `experimental_light_pulse` podía producir actividad sintética periódica.

## Correcciones de esta fase

- Las misiones solo se planifican al aparecer evidencia externa posterior al último ciclo.
- Solo `candidate` y `evaluated` producen revisión de aprendizaje.
- Consolidación se agenda desde `validated_in_runs`, no desde `internally_checked`.
- El scheduler descarta por intervalo antes de persistir tareas que terminarían `skipped`.
- Heartbeat y ciclos sin transición no publican Qualia.
- Fuentes sintéticas no producen memoria semántica ni candidatos post-run.
- Canary neuronal sintético queda deshabilitado salvo opt-in explícito.

Estas correcciones detienen simulación; no inventan aprendizaje nuevo. Para afirmar aprendizaje aún se requiere evidencia, uso en runs, mejora medida y ausencia de regresión.

## Canary sobre copia de producción

El planificador corregido se ejecutó contra una copia SQLite consistente. No
despachó `experimental_neuron_activity`, `pending_learning_review`,
`memory_consolidation_review` ni `neuron_autopromotion`. La cantidad de Qualia,
evidencias neuronales y candidatos permaneció idéntica. Las pruebas E2E ahora
inyectan una evidencia `user_run` explícita antes de esperar una misión.
# Cierre adicional: educación basada en evidencia (2026-07-29)

Se eliminaron dos señales que podían aparentar aprendizaje sin demostrarlo:

- El solapamiento de palabras ya no incrementa `run_use_count`; se conserva solo
  como `heuristic_observations[].counted=false`.
- El resultado de un run ya no parte de `0.5` ni aumenta por estado `ok`, longitud
  de respuesta o disponibilidad del modelo. Solo se registra si la salida aporta
  `learning_outcome_score` y `learning_outcome_evidence_ref`.

La educación neuronal ahora distingue cuatro hechos persistentes:

1. `lesson_prepared`: dos materiales relevantes en estados `cross_checked` o
   `externally_supported`; todavía no es aprendizaje.
2. `evaluated_candidate`: comparación independiente antes/después, con evaluador
   distinto del formador y evidencia referenciada; todavía no es aprendizaje.
3. Aplicaciones en runs: solo usos explícitos, medidos, trazables e idempotentes.
4. `validated_in_runs`: mínimo tres runs únicos y promedio mínimo `0.70`; solo aquí
   la competencia cambia a validada.

La migración `011_neuron_education_evidence.sql` conserva cada aplicación y evita
que un mismo run se cuente dos veces. Esta infraestructura no inventa el evaluador:
si ningún evaluador real entrega baseline, resultado y evidencia, la sesión queda
pendiente. Tampoco equivale a entrenamiento LoRA o modificación de pesos.
