# Live Runtime Baseline — 8b82562

Fecha: 2026-07-29 UTC. Base: `8b825625f0a9284948cbfd016750d9cc7ef9c335`.

## Estado observado antes del cambio

- `triade.service` y `triade-ollama.service`: activos, sin reinicios registrados.
- `LifePulseEngine`: pulso y runner cognitivo cada 60 s.
- `WorkerLoop`: un único loop para todos los dominios y `time.sleep(60)` global.
- `AdaptiveScheduler`: recomienda intervalos usando tiempo de pared e historial, pero no despacha jobs independientes.
- La cola legacy no despertaba al worker al recibir trabajo.
- GPU: NVIDIA L4, 23.034 MiB reportados, driver 580.173.02.
- RAM: 31 GiB, 27 GiB disponibles durante la auditoría; CPU: 8 vCPU.
- Ollama 0.32.5 activo; seis modelos instalados y ninguno residente en la primera medición.

## Calidad base

- `compileall`: pasa.
- Ruff global: falla con 1.053 incidencias preexistentes.
- mypy global: falla con 237 errores en 72 archivos.
- pytest completo: pasa (una advertencia de deprecación Starlette/httpx).
- frontend: `npm ci && npm run build` pasa; `npm audit` reporta una vulnerabilidad alta preexistente.
- El baseline global no puede presentarse como verde.

## Medición posterior de los componentes introducidos

Comandos:

```bash
python scripts/benchmark_live_runtime.py --samples 500
python scripts/benchmark_scheduler.py --logical-hours 24
python scripts/benchmark_gpu_queue.py
```

Resultados de esta máquina:

| Métrica | Resultado |
|---|---:|
| heartbeat p50 | 1,63 ms |
| heartbeat p95 | 3,04 ms |
| heartbeat p99 | 3,25 ms |
| invocaciones LLM por heartbeat | 0 |
| 24 h lógicas | 0,117 s de pared |
| heartbeats simulados | 17.281 |
| despachos simulados | 4.321 |
| jobs al terminar | 2 |
| VRAM total | 23.034 MiB |
| VRAM libre durante medición | 19.736 MiB |
| temperatura GPU | 59 °C |

La simulación acelerada demuestra acotación y ausencia de deriva para dos jobs; no sustituye una prueba prolongada real bajo carga.

## Activación local

El intento de reiniciar `triade.service` fue rechazado por systemd con `Access denied`.
El servicio anterior permaneció activo, por lo que esta auditoría no afirma que el
nuevo heartbeat ya esté desplegado. Un operador autorizado debe ejecutar el paso
de reinicio documentado y comprobar tres ciclos consecutivos.
