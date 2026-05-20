# Tríade Ω · Estado 1.2D

## Nombre de fase

```text
TRIADE_NEURON_CLI_1.2D
```

## Objetivo

Permitir crear, evaluar, registrar, listar y consultar neuronas internas desde terminal sin scripts temporales.

## Archivos modificados/agregados

```text
triade_digimon.py
tests/test_neuron_cli.py
```

## Comandos nuevos

### Crear neurona

```bash
python triade_digimon.py neuron create \
  --name "Neurona Ejemplo" \
  --mission "Misión verificable de la neurona dentro de Tríade." \
  --domain "core" \
  --rule "Debe registrar evidencia." \
  --rule "Debe operar de forma auditable."
```

### Listar neuronas

```bash
python triade_digimon.py neuron list
```

### Ver neurona

```bash
python triade_digimon.py neuron show "Neurona Ejemplo"
```

## Flujo

```text
CLI
→ NeuronCreator
→ NeuronTrainer
→ NeuronRegistry
→ SQLite neurons/neuron_training
```

## Validación local

```bash
cd ~/triadees
git pull
source .venv/bin/activate
pytest
python triade_digimon.py neuron list
```

## Estado

1.2D convierte la gestión de neuronas internas en una función operativa del sistema local.

## Siguiente fase sugerida

```text
TRIADE_NEURON_API_N8N_1.2E
```

Objetivo: exponer neuronas por API y workflow n8n.
