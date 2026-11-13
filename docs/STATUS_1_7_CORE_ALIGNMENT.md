# Tríade Ω · Core Alignment 1.7

## Nombre de fase

```text
TRIADE_CORE_ALIGNMENT_1.7
```

## Objetivo

Crear una capa interna que audite si los órganos principales de Tríade cumplen la teoría operativa declarada:

```text
Central
Hipotálamo
Bodega
Cristal
Runner
```

## Archivos agregados/modificados

```text
triade/core/alignment.py
tests/test_core_alignment.py
triade_digimon.py
```

## Nuevo comando CLI

```bash
python triade_digimon.py align
```

Este comando devuelve:

```text
status
score
organs[]
summary
```

Cada órgano reporta:

```text
organ
score
status
fulfilled
missing
recommendations
```

## Evaluación de artefactos de run

También se puede evaluar si un run contiene todos los artefactos esperados:

```bash
python triade_digimon.py align --artifacts input.json signals.json memory.json crystal.json plan.json safety.json output.json memory_diff.json report.json integrity.json CLOSED
```

## Criterios actuales

### Central

Cumple:

```text
PlanPacket
OutputPacket
uso de señales/memoria/cristal
Ollama o fallback
```

Falta:

```text
plan dinámico profundo
Model Router automático
aprendizaje controlado
N Creadora/Formadora dentro del ciclo principal
```

### Hipotálamo

Cumple:

```text
intención
tono
urgencia
riesgo
PV-7
modelo local o fallback
```

Falta:

```text
estado emocional longitudinal
personalidad dinámica por neurona
aprendizaje afectivo
```

### Bodega

Cumple:

```text
SQLite
identidad
memoria episódica/semántica simple
persistencia de runs/señales/cristal/safety/reportes/modelos
```

Falta:

```text
embeddings reales
learning_queue activo
backups y rotación
```

### Cristal

Cumple:

```text
ética
profundidad
creatividad
relación
pv7_score
stability
intensity
```

Falta:

```text
Q_cristal completa
campos extendidos en CrystalPacket/SQLite
historial temporal del cristal
```

### Runner

Cumple:

```text
ciclo cognitivo ordenado
artefactos JSON
integrity.json
CLOSED
model_events
```

Falta:

```text
Model Router automático
aprendizaje controlado post-run
```

## Validación local

```bash
cd ~/triadees
git pull
source .venv/bin/activate
pytest
python triade_digimon.py align
```

## Siguiente fase sugerida

```text
TRIADE_MODEL_ROUTER_AUTO_RUNNER_1.7B
```

Objetivo: que Runner use el Model Router automáticamente cuando no se definan modelos manuales.
