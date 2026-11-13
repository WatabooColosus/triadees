# Tríade Ω · Estado 1.2C

## Nombre de fase

```text
TRIADE_NEURON_REGISTRY_1.2C
```

## Objetivo

Hacer persistentes las neuronas internas creadas por N Creadora y evaluadas por N Formadora.

## Archivos agregados

```text
triade/core/neuron_registry.py
tests/test_neuron_registry.py
```

## Qué hace NeuronRegistry

Usa tablas existentes:

```text
neurons
neuron_training
```

Permite:

```text
register(spec)
store_training(neuron_id, result)
get_neuron(name)
list_neurons(limit)
list_training(neuron_id)
```

## Flujo interno

```text
NeuronCreator.create()
→ NeuronTrainer.evaluate()
→ NeuronRegistry.register()
→ NeuronRegistry.store_training()
→ SQLite
```

## Validación local

```bash
cd ~/triadees
git pull
source .venv/bin/activate
pytest
```

## Consulta manual SQLite

```bash
sqlite3 triade/memory/triade.db "SELECT id, name, domain, status FROM neurons ORDER BY id DESC LIMIT 10;"
sqlite3 triade/memory/triade.db "SELECT id, neuron_id, score, status, created_at FROM neuron_training ORDER BY id DESC LIMIT 10;"
```

## Siguiente paso

Integrar comandos CLI para crear/evaluar/registrar neuronas desde terminal.
