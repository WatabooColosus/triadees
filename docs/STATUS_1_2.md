# Tríade Ω · Estado 1.2

## Nombre de fase

```text
TRIADE_CRYSTAL_AND_NEURON_CORE_1.2
```

## Objetivo

Fortalecer los órganos internos de Tríade Ω:

```text
Cristal Morfológico
N Creadora
N Formadora
PV-7 operacional
Evaluación interna de neuronas
```

## Por qué esta fase existe

Hasta 1.1, Tríade ya tenía cuerpo operativo:

```text
SQLite + Runner + FastAPI + systemd + n8n + Ollama + runs auditables
```

Pero el Cristal y las neuronas internas seguían en modo MVP. Esta fase empieza a convertir el núcleo conceptual en módulos reales.

## Componentes esperados

### Cristal Morfológico ampliado

Debe calcular un estado regulador con:

```text
ethics
 depth
creativity
relation
pv7_score
stability
intensity
```

Y producir notas verificables sobre su decisión.

### N Creadora

Debe construir especificaciones de neuronas candidatas:

```text
name
mission
domain
rules
status
created_by
```

### N Formadora

Debe evaluar neuronas candidatas y decidir:

```text
candidate
experimental
stable
rejected
```

### Persistencia

La Bodega ya contiene tablas para:

```text
neurons
neuron_training
crystal_states
signal_states
```

Esta fase debe empezar a usar esas estructuras de forma más explícita.

## Criterio de cierre

La fase 1.2 se considera validada si:

- pytest pasa.
- El Cristal genera `pv7_score`, `stability` e `intensity`.
- N Creadora produce una especificación válida.
- N Formadora evalúa y asigna estado.
- Hay tests unitarios de Cristal, N Creadora y N Formadora.
- El Runner sigue funcionando sin romper API ni n8n.

## Siguiente fase sugerida

```text
TRIADE_LEARNING_QUEUE_1.3
```

Objetivo: empezar aprendizaje controlado usando `learning_queue` y `knowledge_patterns`.
