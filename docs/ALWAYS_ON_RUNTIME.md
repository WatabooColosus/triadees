# Always-On Runtime

Tríade Ω puede arrancar en modo **Always-On**: el runtime, self-test, neuron nutrition y procesos seguros se activan automáticamente al iniciar la API, sin necesidad de exportar variables de entorno manualmente.

## Configuración

Configuración persistente en `triade.yml` (sección `runtime`):

```yaml
runtime:
  always_on: true
  mode: full_local_guarded
  interval_seconds: 60
  start_delay_seconds: 3
  max_cycles: 0
  require_ollama: false
  safe_only: true
  self_test_on_start: true
  self_test_every_cycles: 5
  workers_always_on: true
  workers_autostart: true
  workers_watchdog: true
  worker_mode: full_local_guarded
```

En esta instalación local, el modo predeterminado es `full_local_guarded`.
Eso no equivale a acceso libre destructivo: Safety, Permission Governor,
Resource Governor, Integrity Verifier y Safe File Ops siguen bloqueando
`identity_core`, `.git`, `.env`, shell libre, borrado directo, installs y
acciones de zona roja sin aprobación.

### Variables de entorno (override)

| Variable | Descripción |
|---|---|
| `TRIADE_ALWAYS_ON` | `true`/`false` |
| `TRIADE_ALWAYS_ON_MODE` | `observe_only`, `light_background`, `balanced_background`, `full_local_guarded` |
| `TRIADE_ALWAYS_ON_INTERVAL_SECONDS` | Intervalo en segundos |
| `TRIADE_ALWAYS_ON_START_DELAY_SECONDS` | Delay inicial |
| `TRIADE_ALWAYS_ON_MAX_CYCLES` | Máximo de ciclos (0=infinito) |
| `TRIADE_ALWAYS_ON_REQUIRE_OLLAMA` | `true`/`false` |
| `TRIADE_ALWAYS_ON_SAFE_ONLY` | `true`/`false` |
| `TRIADE_SELF_TEST_ON_START` | `true`/`false` |
| `TRIADE_SELF_TEST_EVERY_CYCLES` | Cada N ciclos |
| `TRIADE_WORKERS_ALWAYS_ON` | `true`/`false` |
| `TRIADE_WORKERS_AUTOSTART` | `true`/`false` |
| `TRIADE_WORKERS_WATCHDOG` | `true`/`false` |
| `TRIADE_WORKER_MODE` | Modo configurado para workers |

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
curl http://localhost:8010/api/runtime/workers-always-on/status
curl -X POST http://localhost:8010/api/runtime/always-on/start   # requiere API key
curl -X POST http://localhost:8010/api/runtime/always-on/stop    # requiere API key
curl -X POST http://localhost:8010/api/runtime/workers/restart   # requiere API key si TRIADE_API_KEY existe
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
    "configured_mode": "full_local_guarded",
    "effective_mode": "balanced_background",
    "interval_seconds": 60,
    "status": "running",
    "background_thread_alive": true,
    "degraded_by_governor": true,
    "degradation_reason": "Modo solicitado excede permitido por recursos.",
    "self_test_on_start": true,
    "self_test_every_cycles": 5,
    "config_source": "triade.yml"
  }
}
```

La vida 24/7 se mide por `always_on.background_thread_alive`,
`workers_always_on.active`, `cycles_last_hour`, `self_test_last_status`,
`neurons_nourished_last_24h` y `runtime_continuity_score`. Si el gobernador no
permite `full_local_guarded`, el modo efectivo se degrada, pero el sistema
mantiene respiración operativa y workers supervisados cuando es seguro.
