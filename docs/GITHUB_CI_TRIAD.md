# GitHub CI recomendado · Tríade Ω

El conector no creó directamente `.github/workflows/triade-ci.yml`, pero esta es la definición recomendada para copiar manualmente en el repo local si se desea activar CI.

Ruta sugerida:

```text
.github/workflows/triade-ci.yml
```

Contenido:

```yaml
name: Triade CI

on:
  push:
    branches: ["main"]
  pull_request:
    branches: ["main"]
  workflow_dispatch:

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Run tests
        run: pytest

      - name: Smoke test CLI without Ollama
        run: |
          python triade_digimon.py run "CI smoke test" --no-ollama --db triade/memory/triade-ci.db --runs-dir runs-ci
          python triade_digimon.py doctor --no-ollama --db triade/memory/triade-ci.db --runs-dir runs-ci
```

## Qué valida

- Instalación de dependencias.
- Tests Python.
- CLI `run` sin Ollama.
- CLI `doctor` sin Ollama.

## Qué no valida

- Ollama local.
- Servicio systemd.
- n8n local.
- Firewall o red LAN.

Eso debe validarse en la PC local.
