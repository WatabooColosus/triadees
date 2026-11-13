# Always-On Runtime

> **Dos cosas distintas se llaman «Always-On», y confundirlas costó meses.**
>
> 1. **Always-On de proceso** (supervisión): que alguien vuelva a levantar el
>    proceso cuando muera, y que vuelva tras reiniciar la máquina. De eso se
>    ocupa systemd, y se documenta en [Arranque y supervisión](#arranque-y-supervisión-del-proceso).
> 2. **Always-On de runtime** (este documento): que *dentro* del proceso ya
>    encendido giren el bucle continuo, los workers y el metabolismo.
>
> Lo segundo estuvo cierto durante meses mientras lo primero era falso. El
> proceso lo arrancaba una persona con `nohup` desde una terminal: al cerrar la
> sesión no volvía nadie, y tras un reinicio del Studio tampoco. Como
> `/health/live` respondía 200 y este documento decía «Always-On activo», el
> hueco no aparecía en ninguna superficie. Medido el 2026-08-10, con la máquina
> 19 minutos arriba: cero units instaladas y nada escuchando en el 8010.
>
> Para saber cuál de las dos es cierta ahora mismo, mirar el bloque
> `supervision` de `/health/deep`, no el estado del runtime.

## Arranque y supervisión del proceso

La cadena es una sola, y la misma tanto si arranca la máquina como si la pide
una persona:

```
BOOT
  └─ ~/.lightning_studio/on_start.sh          (shim; lo invoca la plataforma)
       └─ deploy/lightning_studio/on_start.sh (lógica versionada)
            ├─ scripts/restore_file_modes.sh
            ├─ scripts/install_systemd_units.sh
            └─ systemctl start …
                 ├─ triade-ollama.service    modelo (recuperable aparte)
                 ├─ triade-api.service       API + workers en proceso → :8010
                 ├─ triade-watchdog.service  progreso interno, NO reinicia el proceso
                 └─ triade-backup.timer      copia diaria
```

**Por qué se reinstalan las units en cada arranque.** La raíz de este Studio es
un overlay de contenedor: sólo persiste `/teamspace/studios/this_studio`, y
`/etc/systemd/system` se recrea vacío. Una unit habilitada ayer no existe hoy.
Por eso la fuente de verdad son los ficheros de `deploy/systemd/` del repo, y
`install_systemd_units.sh` los instala y habilita en cada arranque. Es
idempotente.

**Un solo mecanismo.** `scripts/triade_runtime.sh up|down|restart|status` es
cliente de systemd, no un lanzador paralelo. Nada debe arrancar la API ni Ollama
con `nohup`: un proceso manual que gane la carrera por el puerto deja a la unit
reiniciándose en bucle mientras sirve tráfico algo que nadie supervisa. Pasó el
2026-07-30 con Ollama (150+ reinicios) y volvió a pasar el 2026-08-10 desde
`post_reboot_verify.sh`, que arrancaba procesos pese a anunciarse como verificador.

**Reinicio gobernado.** `Restart=always` con `StartLimitIntervalSec=300` y
`StartLimitBurst=5`: al sexto arranque en cinco minutos la unit queda en
`failed` en vez de tormentear. Un incidente visible, no un bucle.

**Ollama no tumba a Tríade.** La API declara `Wants=` y no `Requires=`: si el
modelo no está, el runtime queda vivo y degradado, y se recupera cuando Ollama
vuelve.

**Certificación.** `scripts/certify_always_on.py` mata el proceso con SIGKILL y
mide si vuelve solo, en cuánto y siendo el mismo organismo.
`scripts/certify_cold_boot.sh` reproduce la pérdida de `/etc/systemd/system` que
provoca la recreación del contenedor.

## Always-On de runtime (dentro del proceso)

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
