# Always-On Runtime

Tríade Ω puede arrancar en modo **Always-On**: el runtime, self-test, neuron nutrition y procesos seguros se activan automáticamente al iniciar la API, sin necesidad de exportar variables de entorno manualmente.

## Configuración

Configuración persistente en `triade.yml` (sección `runtime`):

```yaml
runtime:
  always_on: false                  # Habilitar auto-arranque
  always_on_mode: execute_missions  # Modo por defecto
  always_on_interval_seconds: 60    # Intervalo entre ciclos
  always_on_start_delay_seconds: 2  # Espera antes de arrancar
  self_test_on_start: true          # Ejecutar self-test al arrancar
  self_test_every_cycles: 5         # Self-test cada N ciclos (0=desactivado)
  safe_only: true                   # Solo operaciones seguras
  require_ollama: false             # Exigir Ollama para arrancar
```

### Variables de entorno (override)

| Variable | Descripción |
|---|---|
| `TRIADE_ALWAYS_ON` | `true`/`false` |
| `TRIADE_ALWAYS_ON_MODE` | `observe_only`, `execute_missions`, `full_local` |
| `TRIADE_ALWAYS_ON_INTERVAL_SECONDS` | Intervalo en segundos |
| `TRIADE_ALWAYS_ON_START_DELAY_SECONDS` | Delay inicial |
| `TRIADE_ALWAYS_ON_MAX_CYCLES` | Máximo de ciclos (0=infinito) |
| `TRIADE_ALWAYS_ON_REQUIRE_OLLAMA` | `true`/`false` |
| `TRIADE_ALWAYS_ON_SAFE_ONLY` | `true`/`false` |
| `TRIADE_SELF_TEST_ON_START` | `true`/`false` |
| `TRIADE_SELF_TEST_EVERY_CYCLES` | Cada N ciclos |

Orden de precedencia: defaults → `triade.yml` → env vars.

## Uso

### CLI

```bash
python triade_digimon.py always-on status
python triade_digimon.py always-on enable        # Escribe en triade.yml
python triade_digimon.py always-on disable
python triade_digimon.py always-on start
python triade_digimon.py always-on stop
python triade_digimon.py self-test               # Safe mode
python triade_digimon.py self-test --mode full   # Full (requiere governor)
```

### API

```bash
curl http://localhost:8010/api/runtime/always-on/status
curl -X POST http://localhost:8010/api/runtime/always-on/start   # requiere API key
curl -X POST http://localhost:8010/api/runtime/always-on/stop    # requiere API key
curl -X POST http://localhost:8010/api/runtime/self-test         # safe mode, sin auth
```

## Self-Test Cycle

El self-test en modo **safe** ejecuta:
1. `check_ollama_blood` — verifica conectividad con Ollama
2. `build_runtime_heartbeat` — genera heartbeat actual
3. `build_learning_journal` — revisa journal de aprendizaje
4. `run_neuron_nutrition_cycle` — alimenta neuronas
5. `build_bodega_global_context` — contexto global de bodega
6. `build_technical_debt_audit` — auditoría de deuda técnica
7. `build_integrity_snapshot` (read-only) — snapshot de integridad
8. `resource_probe` — sondeo de recursos
9. `edge_context_fallback_test` — prueba de fallback

Nunca ejecuta operaciones destructivas (delete, git push, shell, modify .env/.git, etc.).

El modo **full** requiere aprobación del Resource Governor y puede ejecutar aprendizaje, evaluación y consolidación.

## Heartbeat

El heartbeat incluye un bloque `always_on`:

```json
{
  "always_on": {
    "enabled": true,
    "configured_mode": "execute_missions",
    "effective_mode": "observe_only",
    "interval_seconds": 60,
    "status": "running",
    "background_thread_alive": true,
    "self_test_on_start": true,
    "self_test_every_cycles": 5,
    "config_source": "triade.yml"
  }
}
```
