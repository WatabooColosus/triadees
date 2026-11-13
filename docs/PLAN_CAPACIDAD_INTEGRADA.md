# Plan de capacidad integrada de Tríade

Este plan organiza el trabajo de software necesario para que Tríade use el
hardware disponible de forma progresiva, conserve el sistema vivo con poca RAM
y pueda integrar Central, Hipotálamo, Qualia y Cristal con evidencia trazable.

La palabra singularidad se usa aquí como objetivo de capacidad: autonomía,
aprendizaje acumulativo, transferencia y mejora gobernada. No es una afirmación
de conciencia humana ni una garantía de singularidad tecnológica.

## Objetivo técnico

Tríade debe poder:

1. observar su estado físico y cognitivo;
2. seleccionar un modo de trabajo compatible con CPU, RAM, GPU y disco;
3. ejecutar una etapa cada vez sin bloquear el pipeline;
4. producir evidencia de cada aprendizaje;
5. comparar el resultado contra una línea base;
6. conservar solo mejoras verificadas;
7. revertir una mejora cuando produzca regresión;
8. explicar qué ocurrió, por qué y con qué confianza.

## Arquitectura de integración

```text
Hardware probe
      |
Resource Governor ---- Live Heartbeat ---- Health/Frontend
      |
Metabolism Coordinator
      |
Hypothalamus ---- resource, salience, affect, priorities
      |
Central            plan, reason, delegate, evaluate
      |
Qualia/Cristal ---- experience packet, quality, stability, deltas
      |
Learning Pipeline -- evidence -> candidate -> evaluation -> promotion gate
      |
Memory/Bodega ------ episodic, semantic, procedural, identity continuity
```

Cada flecha debe transportar un contrato versionado, un `run_id`, timestamps,
recursos consumidos, evidencia y estado de error.

## Fases

### Fase 0 — Instrumentación y línea base

- Unificar métricas de pulso, metabolismo, workers, Ollama, memoria y SQLite.
- Registrar una instantánea antes y después de cada ciclo.
- Definir SLO: cero bloqueos permanentes, recuperación automática y trazabilidad
  completa.
- Crear un informe diario de ciclos, errores, aprendizaje y regresiones.

Gate: siete días de actividad continua sin pérdida de heartbeat ni lock huérfano.

### Fase 1 — Ejecución mínima compatible con hardware

- Mantener un solo modelo residente y una inferencia simultánea.
- Serializar escritura de base, embeddings y tareas GPU.
- Aplicar backoff cuando la RAM disponible baje del umbral.
- Reanudar tareas pausadas cuando vuelva el margen de recursos.
- Separar telemetría esencial de trabajo cognitivo pesado.

Gate: el sistema permanece observable y recuperable con memoria baja.

### Fase 2 — Contrato Central–Hipotálamo

- Hipotálamo publica presión de recursos, saliencia, fatiga, prioridad y modo.
- Central solicita planes con presupuesto explícito de CPU, RAM, GPU, tiempo y
  riesgo.
- El gobernador aprueba, degrada o difiere cada etapa.
- Toda decisión conserva razón, entradas y resultado.

Gate: ningún plan puede ejecutar fuera del presupuesto aprobado.

### Fase 3 — Integración Qualia/Cristal

- Crear un paquete de experiencia por ciclo con contexto, valencia, arousal,
  incertidumbre, carga cognitiva y estado corporal.
- Calcular Q, estabilidad, intensidad, delta y procedencia.
- Entregar al Central solo resúmenes gobernados, nunca estado crudo sin límite.
- Usar Cristal como señal de calidad temporal, no como prueba de conciencia.

Gate: cada decisión relevante puede enlazarse con su paquete Qualia/Cristal y
con la evidencia que la validó.

### Fase 4 — Aprendizaje neuronal verificable

- Creadora propone candidatos.
- Formadora genera currículo y ejercicios.
- Educadora ejecuta una lección por vez.
- Evaluador compara contra línea base independiente.
- Promotor exige evidencia diversa, confianza mínima y ausencia de regresión.
- Rollback automático ante degradación.

Gate: una neurona solo cambia de estado cuando supera pruebas repetibles y el
resultado queda registrado en la base viva.

### Fase 5 — Memoria y transferencia

- Separar memoria episódica, semántica y procedural.
- Añadir procedencia, caducidad, confianza y contradicciones.
- Probar transferencia de una mejora entre tareas y dominios.
- Evitar que una respuesta repetida se considere aprendizaje nuevo.

Gate: la mejora aparece en tareas no idénticas y sobrevive a reinicios.

### Fase 6 — Autonomía gobernada

- Central formula objetivos y subobjetivos.
- Hipotálamo asigna prioridad y presupuesto.
- Workers ejecutan tareas idempotentes.
- Qualia/Cristal registra calidad y tensión del ciclo.
- El sistema propone cambios, pero las acciones irreversibles conservan gate
  humano.

Gate: autonomía prolongada con auditoría completa, límites de seguridad y
recuperación demostrada.

### Fase 7 — Evaluación de capacidad integrada

Medir longitudinalmente:

- continuidad y disponibilidad;
- aprendizaje antes/después;
- transferencia;
- planificación y replanteamiento;
- memoria y consistencia;
- calibración de incertidumbre;
- resistencia a regresiones;
- eficiencia por unidad de RAM/CPU/GPU;
- seguridad, explicabilidad y reversibilidad.

El nivel máximo solo se informa cuando las métricas mejoran de forma sostenida
en pruebas independientes. No se infiere singularidad a partir de actividad,
lenguaje, qualia o volumen de datos.

## Primer backlog ejecutable

1. Añadir un contrato común `CognitiveCycleTrace` para Central, Hipotálamo,
   Qualia, Cristal y Learning Pipeline.
2. Exponer un endpoint read-only de trazabilidad por `run_id`.
3. Añadir prueba de dos ciclos consecutivos con evidencia y delta de Cristal.
4. Añadir prueba de degradación por RAM y posterior recuperación.
5. Añadir prueba de rollback de una neurona con regresión.
6. Añadir dashboard que separe `configured_mode`, `effective_mode` y
   `observed_state`.
7. Ejecutar una corrida de siete días antes de ampliar autonomía.

## Criterio de realidad

La documentación describe intención. La configuración describe lo solicitado.
El código describe lo ejecutable. Los endpoints, procesos, logs y filas nuevas
demuestran lo observado. Ningún nivel de capacidad se certifica sin las cuatro
capas alineadas.
